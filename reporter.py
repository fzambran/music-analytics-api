"""Per-artist statistics report from chinook.db, exportable to JSON or CSV.

Usage:
    uv run python reporter.py --format {json,csv} [--output PATH]
        [--artist-id N] [--top N] [--sort-by FIELD]
"""

import argparse
import csv
import json
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from typing import TextIO

from db_routes import get_db_connection


@dataclass(frozen=True, slots=True)
class ArtistStats:
    """Aggregated statistics for one artist."""

    artist_id: int
    name: str
    album_count: int
    track_count: int
    total_duration_ms: int
    avg_track_duration_ms: int
    revenue: float
    units_sold: int


FIELDS: tuple[str, ...] = tuple(field.name for field in fields(ArtistStats))

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

# Each subquery aggregates per artist before joining, so no join multiplies
# the rows of another (which would inflate album and track counts).
_STATS_SQL = """
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
    SELECT
        a.ArtistId,
        SUM(CAST(ROUND(il.UnitPrice * 100) AS INTEGER) * il.Quantity) AS revenue_cents,
        SUM(il.Quantity) AS units
    FROM InvoiceLine il
    JOIN Track tr ON tr.TrackId = il.TrackId
    JOIN Album a ON a.AlbumId = tr.AlbumId
    GROUP BY a.ArtistId
) s ON s.ArtistId = ar.ArtistId
"""


def get_artist_stats(
    connection: sqlite3.Connection,
    *,
    artist_id: int | None = None,
    top: int | None = None,
    sort_by: str = "revenue",
) -> list[ArtistStats]:
    """Return per-artist statistics, sorted by `sort_by` with ties broken by artist id.

    Artists without albums or sales are included with zeros. Returns an empty list
    if `artist_id` does not exist. Raises ValueError for an unknown `sort_by` or a
    `top` smaller than 1. The connection is neither opened nor closed here.
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

    return [
        ArtistStats(
            artist_id=row[0],
            name=row[1],
            album_count=row[2],
            track_count=row[3],
            total_duration_ms=row[4],
            avg_track_duration_ms=row[5],
            revenue=round(row[6] / 100, 2),
            units_sold=row[7],
        )
        for row in connection.execute(sql, params)
    ]


def to_json(stats: Iterable[ArtistStats], file: TextIO) -> None:
    """Write the statistics to `file` as a JSON list of objects (UTF-8, unescaped)."""
    json.dump([asdict(item) for item in stats], file, ensure_ascii=False, indent=2)
    file.write("\n")


def to_csv(stats: Iterable[ArtistStats], file: TextIO) -> None:
    """Write the statistics to `file` as CSV with a header; revenue has 2 decimals."""
    writer = csv.DictWriter(file, fieldnames=FIELDS)
    writer.writeheader()
    for item in stats:
        row = asdict(item)
        row["revenue"] = f"{item.revenue:.2f}"
        writer.writerow(row)


EXPORTERS = {"json": to_json, "csv": to_csv}


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
    parser.add_argument("--format", required=True, choices=EXPORTERS)
    parser.add_argument("--output", help="output file path (default: stdout)")
    parser.add_argument("--artist-id", type=_positive_int)
    parser.add_argument("--top", type=_positive_int)
    parser.add_argument("--sort-by", choices=SORT_COLUMNS, default="revenue")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the reporter CLI and return the process exit code."""
    args = parse_args(argv)

    try:
        with closing(get_db_connection()) as connection:
            stats = get_artist_stats(
                connection, artist_id=args.artist_id, top=args.top, sort_by=args.sort_by
            )
    except sqlite3.Error as error:
        print(f"error: no se pudo abrir la base de datos: {error}", file=sys.stderr)
        return 1

    if args.artist_id is not None and not stats:
        print(f"error: artist {args.artist_id} not found", file=sys.stderr)
        return 1

    export = EXPORTERS[args.format]
    if args.output is None:
        export(stats, sys.stdout)
        return 0
    try:
        with open(args.output, "w", encoding="utf-8", newline="") as file:
            export(stats, file)
    except OSError as error:
        print(f"error: no se pudo escribir {args.output}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
