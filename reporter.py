"""Per-artist statistics report from chinook.db, exportable to JSON or CSV.

Usage:
    uv run python reporter.py --format {json,csv} [--output PATH] [--db PATH]
        [--artist-id N | --artist NAME] [--top N] [--sort-by FIELD] [--detail]
"""

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import TextIO

from db_routes import get_db_connection


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
    ar.Name AS name,
    COALESCE(al.album_count, 0) AS album_count,
    COALESCE(t.track_count, 0) AS track_count,
    COALESCE(t.total_ms, 0) AS total_duration_ms,
    CASE WHEN COALESCE(t.track_count, 0) = 0 THEN 0
         ELSE CAST(ROUND(1.0 * t.total_ms / t.track_count) AS INTEGER)
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
WHERE a.ArtistId IN ({placeholders})
ORDER BY a.ArtistId, g.Name
"""

_ALBUMS_SQL = f"""
SELECT
    al.ArtistId,
    al.AlbumId,
    al.Title,
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
WHERE al.ArtistId IN ({{placeholders}})
ORDER BY al.ArtistId, al.Title, al.AlbumId
"""


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
    for artist_id, artist_name in connection.execute(
        "SELECT ArtistId, Name FROM Artist ORDER BY ArtistId"
    ):
        if artist_name.casefold() == wanted:
            return artist_id
    return None


def _genres_by_artist(
    connection: sqlite3.Connection, artist_ids: list[int]
) -> dict[int, tuple[str, ...]]:
    """Map each artist id to the sorted distinct genres of its tracks."""
    sql = _GENRES_SQL.format(placeholders=", ".join("?" * len(artist_ids)))
    genres: dict[int, list[str]] = defaultdict(list)
    for artist_id, genre in connection.execute(sql, artist_ids):
        genres[artist_id].append(genre)
    return {artist_id: tuple(names) for artist_id, names in genres.items()}


def _albums_by_artist(
    connection: sqlite3.Connection, artist_ids: list[int]
) -> dict[int, tuple[AlbumStats, ...]]:
    """Map each artist id to its album statistics, ordered by title."""
    sql = _ALBUMS_SQL.format(placeholders=", ".join("?" * len(artist_ids)))
    albums: dict[int, list[AlbumStats]] = defaultdict(list)
    for row in connection.execute(sql, artist_ids):
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
    top: int | None = None,
    sort_by: str = "revenue",
    include_albums: bool = False,
) -> list[ArtistStats]:
    """Return per-artist statistics, sorted by `sort_by` with ties broken by artist id.

    Each artist includes its genres; with `include_albums=True` it also includes the
    per-album detail. Artists without albums or sales are included with zeros.
    Returns an empty list if `artist_id` does not exist. Raises ValueError for an
    unknown `sort_by` or a `top` smaller than 1. The connection is neither opened
    nor closed here.
    """
    if sort_by not in SORT_COLUMNS:
        raise ValueError(
            f"Invalid sort_by {sort_by!r}; expected one of {', '.join(SORT_COLUMNS)}"
        )
    if top is not None and top < 1:
        raise ValueError(f"top must be >= 1, got {top}")

    column, direction = SORT_COLUMNS[sort_by]
    sql = _STATS_SQL
    params: list[int] = []
    if artist_id is not None:
        sql += "WHERE ar.ArtistId = ?\n"
        params.append(artist_id)
    sql += f"ORDER BY {column} {direction}, ar.ArtistId\n"
    if top is not None:
        sql += "LIMIT ?\n"
        params.append(top)

    rows = connection.execute(sql, params).fetchall()
    if not rows:
        return []

    artist_ids = [row[0] for row in rows]
    genres = _genres_by_artist(connection, artist_ids)
    albums = _albums_by_artist(connection, artist_ids) if include_albums else None

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
    `include_albums=True`.
    """
    if detail:
        writer = csv.DictWriter(file, fieldnames=ALBUM_FIELDS)
        writer.writeheader()
        for item in stats:
            if item.albums is None:
                raise ValueError("detail=True requires stats with albums")
            for album in item.albums:
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


def _export(stats: list[ArtistStats], file: TextIO, args: argparse.Namespace) -> None:
    """Write `stats` to `file` in the format requested on the command line."""
    if args.format == "json":
        to_json(stats, file)
    else:
        to_csv(stats, file, detail=args.detail)


def _positive_int(value: str) -> int:
    """argparse type for integers >= 1."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be >= 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command-line arguments of the reporter."""
    parser = argparse.ArgumentParser(
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
    parser.add_argument("--top", type=_positive_int)
    parser.add_argument("--sort-by", choices=SORT_COLUMNS, default="revenue")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="include per-album detail (nested in JSON, one row per album in CSV)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the reporter CLI and return the process exit code."""
    args = parse_args(argv)

    try:
        with closing(get_db_connection(args.db)) as connection:
            artist_id = args.artist_id
            if args.artist is not None:
                artist_id = find_artist_id(connection, args.artist)
                if artist_id is None:
                    print(f"error: artist {args.artist!r} not found", file=sys.stderr)
                    return 1
            stats = get_artist_stats(
                connection,
                artist_id=artist_id,
                top=args.top,
                sort_by=args.sort_by,
                include_albums=args.detail,
            )
    except sqlite3.Error as error:
        print(f"error: no se pudo abrir la base de datos: {error}", file=sys.stderr)
        return 1

    if artist_id is not None and not stats:
        print(f"error: artist {artist_id} not found", file=sys.stderr)
        return 1

    if args.output is None:
        _export(stats, sys.stdout, args)
        return 0
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as file:
            _export(stats, file, args)
    except OSError as error:
        print(f"error: no se pudo escribir {args.output}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
