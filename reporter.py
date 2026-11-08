"""Per-artist statistics report from chinook.db, exportable to JSON or CSV.

Usage:
    uv run python reporter.py --format {json,csv} [--output PATH] [--db PATH]
        [--artist-id N | --artist NAME | --artist-contains TEXT]
        [--top N] [--sort-by FIELD] [--detail]
"""

import argparse
import csv
import errno
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import NoReturn, TextIO

from db_routes import CHINOOK_DB_PATH, get_db_connection

# Tables and columns the report reads. validate_schema checks them up front so a
# SQLite file that is not a Chinook database gets a clear error.
REQUIRED_SCHEMA: dict[str, tuple[str, ...]] = {
    "Artist": ("ArtistId", "Name"),
    "Album": ("AlbumId", "Title", "ArtistId"),
    "Track": ("TrackId", "AlbumId", "GenreId", "Milliseconds"),
    "Genre": ("GenreId", "Name"),
    "InvoiceLine": ("TrackId", "UnitPrice", "Quantity"),
}


class SchemaError(Exception):
    """The database opened but lacks tables or columns the report needs."""


@dataclass(frozen=True, slots=True)
class AlbumStats:
    """Aggregated statistics for one album."""

    album_id: int
    title: str
    track_count: int
    total_duration_ms: int
    revenue: float
    units_sold: int


@dataclass(frozen=True, slots=True)
class ArtistStats:
    """Aggregated statistics for one artist.

    `albums` is None unless the per-album detail was requested.
    """

    artist_id: int
    name: str
    album_count: int
    track_count: int
    total_duration_ms: int
    avg_track_duration_ms: int
    revenue: float
    units_sold: int
    genres: tuple[str, ...] = ()
    albums: tuple[AlbumStats, ...] | None = None


# Columns of the per-artist CSV (albums are nested, so they only appear in JSON
# or in the per-album CSV).
FIELDS: tuple[str, ...] = tuple(
    field.name for field in fields(ArtistStats) if field.name != "albums"
)
# Columns of the per-album CSV produced with detail=True.
ALBUM_FIELDS: tuple[str, ...] = (
    "artist_id",
    "artist_name",
    *(field.name for field in fields(AlbumStats)),
)
GENRE_SEPARATOR = "; "

# ORDER BY cannot be parameterized, so sort columns come from this allowlist.
SORT_COLUMNS: dict[str, tuple[str, str]] = {
    "artist_id": ("ar.ArtistId", "ASC"),
    "name": ("ar.Name COLLATE NOCASE", "ASC"),
    "album_count": ("album_count", "DESC"),
    "track_count": ("track_count", "DESC"),
    "total_duration_ms": ("total_duration_ms", "DESC"),
    "avg_track_duration_ms": ("avg_track_duration_ms", "DESC"),
    "revenue": ("revenue_cents", "DESC"),
    "units_sold": ("units_sold", "DESC"),
}

# Revenue is summed in integer cents to avoid floating-point drift.
_REVENUE_CENTS = "SUM(CAST(ROUND(il.UnitPrice * 100) AS INTEGER) * il.Quantity)"

# Each subquery aggregates per artist before joining, so no join multiplies
# the rows of another (which would inflate album and track counts).
_STATS_SQL = f"""
SELECT
    ar.ArtistId AS artist_id,
    COALESCE(ar.Name, '') AS name,
    COALESCE(al.album_count, 0) AS album_count,
    COALESCE(t.track_count, 0) AS track_count,
    COALESCE(t.total_ms, 0) AS total_duration_ms,
    CASE WHEN COALESCE(t.track_count, 0) = 0 THEN 0
         ELSE CAST(ROUND(1.0 * COALESCE(t.total_ms, 0) / t.track_count) AS INTEGER)
    END AS avg_track_duration_ms,
    COALESCE(s.revenue_cents, 0) AS revenue_cents,
    COALESCE(s.units, 0) AS units_sold
FROM Artist ar
LEFT JOIN (
    SELECT ArtistId, COUNT(*) AS album_count FROM Album GROUP BY ArtistId
) al ON al.ArtistId = ar.ArtistId
LEFT JOIN (
    SELECT a.ArtistId, COUNT(*) AS track_count, SUM(tr.Milliseconds) AS total_ms
    FROM Track tr
    JOIN Album a ON a.AlbumId = tr.AlbumId
    GROUP BY a.ArtistId
) t ON t.ArtistId = ar.ArtistId
LEFT JOIN (
    SELECT a.ArtistId, {_REVENUE_CENTS} AS revenue_cents, SUM(il.Quantity) AS units
    FROM InvoiceLine il
    JOIN Track tr ON tr.TrackId = il.TrackId
    JOIN Album a ON a.AlbumId = tr.AlbumId
    GROUP BY a.ArtistId
) s ON s.ArtistId = ar.ArtistId
"""

_GENRES_SQL = """
SELECT DISTINCT a.ArtistId, g.Name
FROM Track tr
JOIN Album a ON a.AlbumId = tr.AlbumId
JOIN Genre g ON g.GenreId = tr.GenreId
WHERE a.ArtistId IN (SELECT value FROM json_each(?)) AND g.Name IS NOT NULL
ORDER BY a.ArtistId, g.Name
"""

_ALBUMS_SQL = f"""
SELECT
    al.ArtistId,
    al.AlbumId,
    COALESCE(al.Title, ''),
    COALESCE(t.track_count, 0),
    COALESCE(t.total_ms, 0),
    COALESCE(s.revenue_cents, 0),
    COALESCE(s.units, 0)
FROM Album al
LEFT JOIN (
    SELECT AlbumId, COUNT(*) AS track_count, SUM(Milliseconds) AS total_ms
    FROM Track
    GROUP BY AlbumId
) t ON t.AlbumId = al.AlbumId
LEFT JOIN (
    SELECT tr.AlbumId, {_REVENUE_CENTS} AS revenue_cents, SUM(il.Quantity) AS units
    FROM InvoiceLine il
    JOIN Track tr ON tr.TrackId = il.TrackId
    GROUP BY tr.AlbumId
) s ON s.AlbumId = al.AlbumId
WHERE al.ArtistId IN (SELECT value FROM json_each(?))
ORDER BY al.ArtistId, al.Title, al.AlbumId
"""


# Artist.Name is nullable in the Chinook schema; nameless artists never match.
_NAMED_ARTISTS_SQL = (
    "SELECT ArtistId, Name FROM Artist WHERE Name IS NOT NULL ORDER BY ArtistId"
)


def validate_schema(connection: sqlite3.Connection) -> None:
    """Raise SchemaError if any table or column in REQUIRED_SCHEMA is missing.

    The message lists every missing table and column, not just the first one.
    Table and column names are compared case-insensitively, as SQLite does.
    sqlite3.DatabaseError propagates if the file is not a SQLite database.
    """
    problems = []
    for table, columns in REQUIRED_SCHEMA.items():
        existing = {
            name.casefold()
            for (name,) in connection.execute(
                "SELECT name FROM pragma_table_info(?)", (table,)
            )
        }
        if not existing:
            problems.append(f"falta la tabla {table}")
            continue
        missing = [column for column in columns if column.casefold() not in existing]
        if missing:
            problems.append(f"faltan columnas en {table}: {', '.join(missing)}")
    if problems:
        raise SchemaError("; ".join(problems))


def _cents_to_amount(cents: int) -> float:
    """Convert integer cents to an amount rounded to 2 decimals."""
    return round(cents / 100, 2)


def find_artist_id(connection: sqlite3.Connection, name: str) -> int | None:
    """Return the id of the artist whose name matches `name`, ignoring case.

    Unlike SQLite's LOWER/NOCASE, the comparison also folds non-ASCII letters
    ("ANTÔNIO" matches "Antônio"). Surrounding whitespace is ignored. If several
    artists match, the lowest id wins. Returns None if there is no match.
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None
    for artist_id, artist_name in connection.execute(_NAMED_ARTISTS_SQL):
        if artist_name.casefold() == wanted:
            return artist_id
    return None


def normalize_for_search(text: str) -> str:
    """Reduce `text` to lowercase letters and digits without accents.

    Case, accents, spaces and punctuation are dropped, so "AC/DC", "ac-dc" and
    "acdc" all become "acdc", and "Antônio" becomes "antonio". Letters of other
    scripts are kept.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        char
        for char in decomposed
        if char.isalnum() and not unicodedata.combining(char)
    )


def find_artist_ids_containing(connection: sqlite3.Connection, text: str) -> list[int]:
    """Return the ids of the artists whose name contains `text`, in ascending order.

    Both sides go through normalize_for_search, so the match ignores case, accents,
    spaces and punctuation: "acdc" matches "AC/DC", "guns n roses" matches
    "Guns N' Roses" and "nacao" matches "Nação Zumbi". Returns an empty list when
    `text` has no letters or digits instead of matching every artist.
    """
    wanted = normalize_for_search(text)
    if not wanted:
        return []
    return [
        artist_id
        for artist_id, artist_name in connection.execute(_NAMED_ARTISTS_SQL)
        if wanted in normalize_for_search(artist_name)
    ]


def _genres_by_artist(
    connection: sqlite3.Connection, artist_ids: list[int]
) -> dict[int, tuple[str, ...]]:
    """Map each artist id to the sorted distinct genres of its tracks."""
    genres: dict[int, list[str]] = defaultdict(list)
    for artist_id, genre in connection.execute(_GENRES_SQL, (json.dumps(artist_ids),)):
        genres[artist_id].append(genre)
    return {artist_id: tuple(names) for artist_id, names in genres.items()}


def _albums_by_artist(
    connection: sqlite3.Connection, artist_ids: list[int]
) -> dict[int, tuple[AlbumStats, ...]]:
    """Map each artist id to its album statistics, ordered by title."""
    albums: dict[int, list[AlbumStats]] = defaultdict(list)
    for row in connection.execute(_ALBUMS_SQL, (json.dumps(artist_ids),)):
        albums[row[0]].append(
            AlbumStats(
                album_id=row[1],
                title=row[2],
                track_count=row[3],
                total_duration_ms=row[4],
                revenue=_cents_to_amount(row[5]),
                units_sold=row[6],
            )
        )
    return {artist_id: tuple(items) for artist_id, items in albums.items()}


def get_artist_stats(
    connection: sqlite3.Connection,
    *,
    artist_id: int | None = None,
    artist_ids: Iterable[int] | None = None,
    top: int | None = None,
    sort_by: str = "revenue",
    include_albums: bool = False,
) -> list[ArtistStats]:
    """Return per-artist statistics, sorted by `sort_by` with ties broken by artist id.

    Each artist includes its genres; with `include_albums=True` it also includes the
    per-album detail. Artists without albums or sales are included with zeros.
    `artist_id` restricts the result to one artist and `artist_ids` to several (an
    empty `artist_ids` returns []); unknown ids are simply absent from the result.
    `top` applies after that filter. Raises ValueError for an unknown `sort_by`, a
    `top` smaller than 1 or both `artist_id` and `artist_ids`. The connection is
    neither opened nor closed here.
    """
    if sort_by not in SORT_COLUMNS:
        raise ValueError(
            f"Invalid sort_by {sort_by!r}; expected one of {', '.join(SORT_COLUMNS)}"
        )
    if top is not None and top < 1:
        raise ValueError(f"top must be >= 1, got {top}")
    if artist_id is not None and artist_ids is not None:
        raise ValueError("Pass artist_id or artist_ids, not both")

    column, direction = SORT_COLUMNS[sort_by]
    sql = _STATS_SQL
    params: list[int | str] = []
    if artist_id is not None:
        sql += "WHERE ar.ArtistId = ?\n"
        params.append(artist_id)
    elif artist_ids is not None:
        ids = list(artist_ids)
        if not ids:
            return []
        # A single JSON parameter: SQLite limits the number of bound variables.
        sql += "WHERE ar.ArtistId IN (SELECT value FROM json_each(?))\n"
        params.append(json.dumps(ids))
    sql += f"ORDER BY {column} {direction}, ar.ArtistId\n"
    if top is not None:
        sql += "LIMIT ?\n"
        params.append(top)

    rows = connection.execute(sql, params).fetchall()
    if not rows:
        return []

    result_ids = [row[0] for row in rows]
    genres = _genres_by_artist(connection, result_ids)
    albums = _albums_by_artist(connection, result_ids) if include_albums else None

    return [
        ArtistStats(
            artist_id=row[0],
            name=row[1],
            album_count=row[2],
            track_count=row[3],
            total_duration_ms=row[4],
            avg_track_duration_ms=row[5],
            revenue=_cents_to_amount(row[6]),
            units_sold=row[7],
            genres=genres.get(row[0], ()),
            albums=None if albums is None else albums.get(row[0], ()),
        )
        for row in rows
    ]


def to_json(stats: Iterable[ArtistStats], file: TextIO) -> None:
    """Write the statistics to `file` as a JSON list of objects (UTF-8, unescaped).

    `genres` is a list; `albums` is included only when the detail was requested.
    """
    data = []
    for item in stats:
        row = asdict(item)
        if item.albums is None:
            del row["albums"]
        data.append(row)
    json.dump(data, file, ensure_ascii=False, indent=2)
    file.write("\n")


def to_csv(stats: Iterable[ArtistStats], file: TextIO, *, detail: bool = False) -> None:
    """Write the statistics to `file` as CSV with a header; revenue has 2 decimals.

    By default there is one row per artist, with genres joined by "; ". With
    `detail=True` there is one row per album (columns ALBUM_FIELDS); artists
    without albums produce no rows. Detail requires stats built with
    `include_albums=True`; otherwise ValueError is raised before anything is written.
    """
    if detail:
        stats = list(stats)
        _check_export(stats, fmt="csv", detail=True)
        writer = csv.DictWriter(file, fieldnames=ALBUM_FIELDS)
        writer.writeheader()
        for item in stats:
            for album in item.albums or ():
                row = {"artist_id": item.artist_id, "artist_name": item.name}
                row.update(asdict(album))
                row["revenue"] = f"{album.revenue:.2f}"
                writer.writerow(row)
        return

    writer = csv.DictWriter(file, fieldnames=FIELDS)
    writer.writeheader()
    for item in stats:
        row = {name: getattr(item, name) for name in FIELDS}
        row["revenue"] = f"{item.revenue:.2f}"
        row["genres"] = GENRE_SEPARATOR.join(item.genres)
        writer.writerow(row)


def _check_export(stats: list[ArtistStats], *, fmt: str, detail: bool) -> None:
    """Raise ValueError if `stats` cannot be exported as requested."""
    if fmt not in ("json", "csv"):
        raise ValueError(f"Invalid format {fmt!r}; expected 'json' or 'csv'")
    if fmt == "csv" and detail and any(item.albums is None for item in stats):
        raise ValueError("detail=True requires stats with albums")


def export(
    stats: Iterable[ArtistStats], file: TextIO, *, fmt: str, detail: bool = False
) -> None:
    """Write `stats` to an open text `file` as "json" or "csv".

    `detail` only affects CSV (one row per album); JSON nests albums whenever the
    stats include them. Raises ValueError for an unknown format, or for CSV detail
    without albums, before anything is written.
    """
    stats = list(stats)
    _check_export(stats, fmt=fmt, detail=detail)
    if fmt == "json":
        to_json(stats, file)
    else:
        to_csv(stats, file, detail=detail)


def write_output(
    path: Path, stats: Iterable[ArtistStats], *, fmt: str, detail: bool = False
) -> None:
    """Write `stats` to the file at `path` (UTF-8), creating missing directories.

    The arguments are validated before touching the disk, and the content is written
    to a temporary file in the same directory that then replaces `path`, so an
    error never leaves an empty or half-written report. An existing file keeps its
    permissions, a symlink is written through, and a read-only file is not replaced.
    The file is opened with newline="" so CSV rows get no extra blank lines on
    Windows. ValueError and OSError propagate.
    """
    stats = list(stats)
    _check_export(stats, fmt=fmt, detail=detail)

    target = path.resolve()
    if target.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    if target.exists() and not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as file:
            export(stats, file, fmt=fmt, detail=detail)
        if target.exists():
            shutil.copymode(target, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


# Largest integer SQLite can bind; larger values raise OverflowError, not sqlite3.Error.
_SQLITE_MAX_INTEGER = 2**63 - 1


def _positive_int(value: str) -> int:
    """argparse type for integers between 1 and the largest SQLite integer."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} no es un número entero") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} debe ser mayor o igual que 1")
    if number > _SQLITE_MAX_INTEGER:
        raise argparse.ArgumentTypeError(
            f"{value!r} debe ser menor o igual que {_SQLITE_MAX_INTEGER}"
        )
    return number


def _search_text(value: str) -> str:
    """argparse type for a search text with at least one letter or digit."""
    if not value.strip():
        raise argparse.ArgumentTypeError("el texto de búsqueda no puede estar vacío")
    if not normalize_for_search(value):
        raise argparse.ArgumentTypeError(
            f"{value!r} debe contener al menos una letra o un número"
        )
    return value


# argparse's own error messages (Python 3.12 templates) translated to Spanish.
# Anything not listed here is shown untranslated rather than hidden.
_ARGPARSE_TRANSLATIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), replacement)
    for pattern, replacement in (
        (
            r"^invalid choice: (?P<value>.+) \(choose from (?P<choices>.+)\)$",
            r"valor inválido: \g<value> (opciones: \g<choices>)",
        ),
        (r"^expected one argument$", "se esperaba un valor"),
        (
            r"^not allowed with argument (?P<other>.+)$",
            r"no se puede combinar con \g<other>",
        ),
        (r"^invalid \S+ value: (?P<value>.+)$", r"valor inválido: \g<value>"),
        (
            r"^the following arguments are required: (?P<args>.+)$",
            r"faltan argumentos obligatorios: \g<args>",
        ),
        (
            r"^unrecognized arguments: (?P<args>.+)$",
            r"argumentos no reconocidos: \g<args>",
        ),
        (
            r"^ambiguous option: (?P<option>\S+) could match (?P<matches>.+)$",
            r"opción ambigua: \g<option> puede ser \g<matches>",
        ),
    )
)
_ARGUMENT_PREFIX = re.compile(r"^argument (?P<argument>[^:]+): (?P<message>.+)$")


def _translate_argparse_message(message: str) -> str:
    """Translate an argparse error message to Spanish, keeping unknown ones as is."""
    prefix = ""
    match = _ARGUMENT_PREFIX.match(message)
    if match:
        prefix = f"argumento {match['argument']}: "
        message = match["message"]
    for pattern, replacement in _ARGPARSE_TRANSLATIONS:
        if pattern.match(message):
            return prefix + pattern.sub(replacement, message)
    return prefix + message


class _SpanishArgumentParser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors are printed in Spanish."""

    def error(self, message: str) -> NoReturn:
        """Print the usage and the translated error to stderr, then exit with 2."""
        usage = self.format_usage().replace("usage: ", "uso: ", 1)
        self.exit(2, f"{usage}error: {_translate_argparse_message(message)}\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command-line arguments of the reporter."""
    parser = _SpanishArgumentParser(
        description="Per-artist statistics from chinook.db exported to JSON or CSV."
    )
    parser.add_argument("--format", required=True, choices=("json", "csv"))
    parser.add_argument(
        "--output",
        type=Path,
        help="output file path; missing directories are created (default: stdout)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="SQLite database to read, opened read-only (default: chinook.db)",
    )
    artist = parser.add_mutually_exclusive_group()
    artist.add_argument("--artist-id", type=_positive_int)
    artist.add_argument("--artist", help="artist name, case-insensitive exact match")
    artist.add_argument(
        "--artist-contains",
        type=_search_text,
        help=(
            "text contained in the artist name, ignoring case, accents, spaces and "
            "punctuation (all matches)"
        ),
    )
    parser.add_argument("--top", type=_positive_int)
    parser.add_argument("--sort-by", choices=SORT_COLUMNS, default="revenue")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="include per-album detail (nested in JSON, one row per album in CSV)",
    )
    return parser.parse_args(argv)


class _ArtistNotFound(Exception):
    """The artist filter given on the command line matched nothing."""


def _select_stats(
    connection: sqlite3.Connection, args: argparse.Namespace
) -> list[ArtistStats]:
    """Resolve the artist filter of the CLI and return the requested statistics.

    Raises _ArtistNotFound (with the Spanish message) if the filter matches nothing.
    """
    artist_id = args.artist_id
    artist_ids = None
    if args.artist is not None:
        artist_id = find_artist_id(connection, args.artist)
        if artist_id is None:
            raise _ArtistNotFound(f"no se encontró el artista {args.artist!r}")
    elif args.artist_contains is not None:
        artist_ids = find_artist_ids_containing(connection, args.artist_contains)
        if not artist_ids:
            raise _ArtistNotFound(
                f"ningún artista contiene {args.artist_contains!r} en el nombre"
            )
    stats = get_artist_stats(
        connection,
        artist_id=artist_id,
        artist_ids=artist_ids,
        top=args.top,
        sort_by=args.sort_by,
        include_albums=args.detail,
    )
    if artist_id is not None and not stats:
        raise _ArtistNotFound(f"no se encontró el artista con ID {artist_id}")
    return stats


def _write_stdout(stats: list[ArtistStats], args: argparse.Namespace) -> int:
    """Export to stdout; return 1 quietly if the reader closes the pipe early."""
    try:
        export(stats, sys.stdout, fmt=args.format, detail=args.detail)
        sys.stdout.flush()
    except BrokenPipeError:
        # e.g. `reporter.py ... | head`: point stdout at devnull so the interpreter's
        # final flush does not print a second BrokenPipeError on exit.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the reporter CLI and return the process exit code."""
    args = parse_args(argv)
    db_path = args.db if args.db is not None else CHINOOK_DB_PATH

    try:
        connection = get_db_connection(args.db)
    except sqlite3.Error as error:
        print(f"error: no se pudo abrir la base de datos: {error}", file=sys.stderr)
        return 1

    with closing(connection):
        try:
            validate_schema(connection)
        except SchemaError as error:
            print(
                f"error: {db_path} no es una base Chinook válida: {error}",
                file=sys.stderr,
            )
            return 1
        except sqlite3.Error as error:
            # The first read fails when the file is not a SQLite database.
            print(f"error: no se pudo abrir la base de datos: {error}", file=sys.stderr)
            return 1

        try:
            stats = _select_stats(connection, args)
        except _ArtistNotFound as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        except sqlite3.Error as error:
            print(
                f"error: no se pudo consultar la base de datos {db_path}: {error}",
                file=sys.stderr,
            )
            return 1

    if args.output is None:
        return _write_stdout(stats, args)
    try:
        write_output(args.output, stats, fmt=args.format, detail=args.detail)
    except OSError as error:
        print(f"error: no se pudo escribir {args.output}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
