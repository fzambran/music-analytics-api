"""Integration tests for reporter.py against the real chinook.db."""

import csv
import json
from contextlib import closing

import pytest

import db_routes
import reporter
from db_routes import get_db_connection
from reporter import ArtistStats, get_artist_stats


@pytest.fixture
def connection():
    with closing(get_db_connection()) as conn:
        yield conn


@pytest.fixture
def stats_by_id(connection):
    return {item.artist_id: item for item in get_artist_stats(connection)}


def test_one_row_per_artist(connection, stats_by_id):
    (artist_count,) = connection.execute("SELECT COUNT(*) FROM Artist").fetchone()
    assert artist_count == 275
    assert len(stats_by_id) == artist_count


def test_no_metric_is_none(stats_by_id):
    for item in stats_by_id.values():
        assert None not in vars_of(item).values(), item


def test_known_artists(stats_by_id):
    assert stats_by_id[1] == ArtistStats(
        artist_id=1,
        name="AC/DC",
        album_count=2,
        track_count=18,
        total_duration_ms=4853674,
        avg_track_duration_ms=269649,
        revenue=15.84,
        units_sold=16,
    )
    assert stats_by_id[90] == ArtistStats(
        artist_id=90,
        name="Iron Maiden",
        album_count=21,
        track_count=213,
        total_duration_ms=71844745,
        avg_track_duration_ms=337299,
        revenue=138.6,
        units_sold=140,
    )


def test_artist_without_albums_has_zeros(stats_by_id):
    item = stats_by_id[25]
    assert (
        item.album_count,
        item.track_count,
        item.total_duration_ms,
        item.avg_track_duration_ms,
        item.revenue,
        item.units_sold,
    ) == (0, 0, 0, 0, 0.0, 0)


def test_totals_match_source_tables(connection, stats_by_id):
    """Totals equal the raw tables, so no join inflated any count."""
    rows = stats_by_id.values()
    (albums,) = connection.execute("SELECT COUNT(*) FROM Album").fetchone()
    (tracks, total_ms) = connection.execute(
        "SELECT COUNT(*), SUM(Milliseconds) FROM Track WHERE AlbumId IS NOT NULL"
    ).fetchone()
    (units,) = connection.execute("SELECT SUM(Quantity) FROM InvoiceLine").fetchone()

    assert albums == 347
    assert sum(item.album_count for item in rows) == albums
    assert sum(item.track_count for item in rows) == tracks
    assert sum(item.total_duration_ms for item in rows) == total_ms
    assert sum(item.units_sold for item in rows) == units
    assert round(sum(item.revenue for item in rows), 2) == 2328.60


def test_revenue_has_at_most_two_decimals(stats_by_id):
    for item in stats_by_id.values():
        assert round(item.revenue, 2) == item.revenue


def test_default_sort_is_revenue_desc_with_id_tiebreak(connection):
    stats = get_artist_stats(connection)
    assert stats[0].artist_id == 90
    keys = [(-item.revenue, item.artist_id) for item in stats]
    assert keys == sorted(keys)


def test_top_three_by_revenue(connection):
    assert [item.artist_id for item in get_artist_stats(connection, top=3)] == [
        90,
        150,
        50,
    ]


def test_sort_by_name_is_case_insensitive(connection):
    def ascii_casefold(name: str) -> str:
        return "".join(char.lower() if char.isascii() else char for char in name)

    names = [item.name for item in get_artist_stats(connection, sort_by="name")]
    assert names == sorted(names, key=ascii_casefold)
    assert names.index("Aaron Copland & London Symphony Orchestra") < names.index(
        "AC/DC"
    )


@pytest.mark.parametrize("sort_by", ["album_count", "track_count", "units_sold"])
def test_numeric_sorts_are_descending(connection, sort_by):
    values = [
        getattr(item, sort_by) for item in get_artist_stats(connection, sort_by=sort_by)
    ]
    assert values == sorted(values, reverse=True)


def test_filter_by_artist_id(connection):
    stats = get_artist_stats(connection, artist_id=1)
    assert [item.name for item in stats] == ["AC/DC"]


def test_unknown_artist_returns_empty_list(connection):
    assert get_artist_stats(connection, artist_id=999999) == []


def test_invalid_sort_by_raises(connection):
    with pytest.raises(ValueError, match="sort_by"):
        get_artist_stats(connection, sort_by="bogus")


def test_invalid_top_raises(connection):
    with pytest.raises(ValueError, match="top"):
        get_artist_stats(connection, top=0)


# CLI


def test_cli_json_to_stdout(capsys):
    assert reporter.main(["--format", "json", "--top", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [row["artist_id"] for row in data] == [90, 150]
    assert list(data[0]) == list(reporter.FIELDS)


def test_cli_csv_to_file(tmp_path):
    output = tmp_path / "artists.csv"
    assert reporter.main(["--format", "csv", "--output", str(output)]) == 0
    with output.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 275
    assert rows[0]["name"] == "Iron Maiden"
    assert rows[0]["revenue"] == "138.60"


def test_cli_unknown_artist_exits_1(capsys):
    assert reporter.main(["--format", "json", "--artist-id", "999999"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "artist 999999 not found" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["--format", "xml"],
        ["--format", "json", "--sort-by", "bogus"],
        ["--format", "json", "--top", "0"],
        ["--format", "json", "--artist-id", "-1"],
        ["--format", "json", "--top", "abc"],
        [],
    ],
)
def test_cli_invalid_arguments_exit_2(argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        reporter.main(argv)
    assert excinfo.value.code == 2


def test_cli_missing_database_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(db_routes, "CHINOOK_DB_PATH", tmp_path / "missing.db")
    assert reporter.main(["--format", "json"]) == 1
    assert "no se pudo abrir la base de datos" in capsys.readouterr().err


def test_cli_unwritable_output_exits_1(tmp_path, capsys):
    output = tmp_path / "missing-dir" / "artists.json"
    assert reporter.main(["--format", "json", "--output", str(output)]) == 1
    assert "no se pudo escribir" in capsys.readouterr().err


def vars_of(item: ArtistStats) -> dict:
    """Field values of an ArtistStats (slots dataclasses have no __dict__)."""
    return {name: getattr(item, name) for name in reporter.FIELDS}
