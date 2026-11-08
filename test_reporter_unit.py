"""Unit tests for reporter.py with hand-built data, without chinook.db."""

import csv
import io
import json
import sqlite3
from contextlib import closing

import pytest

import reporter
from reporter import (
    ALBUM_FIELDS,
    FIELDS,
    AlbumStats,
    ArtistStats,
    SchemaError,
    export,
    find_artist_id,
    get_artist_stats,
    to_csv,
    to_json,
    validate_schema,
    write_output,
)

SAMPLE = [
    ArtistStats(1, "AC/DC", 2, 18, 4853674, 269649, 15.0, 16, ("Rock",)),
    ArtistStats(
        2, 'Earth, Wind & "Fire"', 1, 3, 600000, 200000, 138.6, 140, ("Pop", "R&B/Soul")
    ),
    ArtistStats(3, "Antônio Carlos Jobim", 0, 0, 0, 0, 0.0, 0),
]

DETAILED = [
    ArtistStats(
        1,
        "AC/DC",
        2,
        18,
        4853674,
        269649,
        15.84,
        16,
        ("Rock",),
        (
            AlbumStats(
                1, "For Those About To Rock, We Salute You", 10, 2400000, 9.9, 10
            ),
            AlbumStats(4, "Let There Be Rock", 8, 2453674, 5.94, 6),
        ),
    ),
    ArtistStats(25, "Milton Nascimento & Bebeto", 0, 0, 0, 0, 0.0, 0, (), ()),
]

# Minimal Chinook-like schema: artist 1 has 2 albums, repeated sales and two
# genres; artist 2 has no albums; artist 3 has one album and no sales.
SAMPLE_SQL = """
CREATE TABLE Artist (ArtistId INTEGER PRIMARY KEY, Name TEXT);
CREATE TABLE Album (AlbumId INTEGER PRIMARY KEY, Title TEXT, ArtistId INTEGER);
CREATE TABLE Genre (GenreId INTEGER PRIMARY KEY, Name TEXT);
CREATE TABLE Track (
    TrackId INTEGER PRIMARY KEY, Name TEXT, AlbumId INTEGER, GenreId INTEGER,
    Milliseconds INTEGER, UnitPrice NUMERIC
);
CREATE TABLE InvoiceLine (
    InvoiceLineId INTEGER PRIMARY KEY, InvoiceId INTEGER, TrackId INTEGER,
    UnitPrice NUMERIC, Quantity INTEGER
);
INSERT INTO Artist VALUES (1, 'Band'), (2, 'Silent'), (3, 'Ünsold');
INSERT INTO Album VALUES (10, 'Second', 1), (11, 'First', 1), (12, 'Only', 3);
INSERT INTO Genre VALUES (1, 'Rock'), (2, 'Blues');
INSERT INTO Track VALUES
    (100, 'a', 10, 1, 1000, 0.99),
    (101, 'b', 10, 1, 2000, 0.99),
    (102, 'c', 11, 2, 4000, 0.99),
    (103, 'd', 12, 1, 3000, 0.99);
INSERT INTO InvoiceLine VALUES
    (1, 1, 100, 0.99, 1),
    (2, 2, 100, 0.99, 1),
    (3, 3, 100, 0.99, 1),
    (4, 3, 102, 0.99, 2);
"""


def csv_rows(text: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return tuple(reader.fieldnames or ()), rows


# JSON exporter


def test_json_keys_in_field_order():
    buffer = io.StringIO()
    to_json(SAMPLE, buffer)
    data = json.loads(buffer.getvalue())
    assert [list(row) for row in data] == [list(FIELDS)] * len(SAMPLE)
    assert data[1]["revenue"] == 138.6
    assert data[1]["genres"] == ["Pop", "R&B/Soul"]
    assert data[2]["genres"] == []


def test_json_keeps_non_ascii_unescaped():
    buffer = io.StringIO()
    to_json(SAMPLE, buffer)
    assert "Antônio" in buffer.getvalue()
    assert buffer.getvalue().endswith("\n")


def test_json_empty_list():
    buffer = io.StringIO()
    to_json([], buffer)
    assert json.loads(buffer.getvalue()) == []


def test_json_detail_nests_albums():
    buffer = io.StringIO()
    to_json(DETAILED, buffer)
    data = json.loads(buffer.getvalue())
    assert list(data[0]) == [*FIELDS, "albums"]
    assert data[0]["albums"][1] == {
        "album_id": 4,
        "title": "Let There Be Rock",
        "track_count": 8,
        "total_duration_ms": 2453674,
        "revenue": 5.94,
        "units_sold": 6,
    }
    assert data[1]["albums"] == []


# CSV exporter


def test_csv_header_revenue_and_genres():
    buffer = io.StringIO()
    to_csv(SAMPLE, buffer)
    header, rows = csv_rows(buffer.getvalue())
    assert header == FIELDS
    assert [row["revenue"] for row in rows] == ["15.00", "138.60", "0.00"]
    assert [row["genres"] for row in rows] == ["Rock", "Pop; R&B/Soul", ""]


def test_csv_round_trips_names_with_commas_and_quotes():
    buffer = io.StringIO()
    to_csv(SAMPLE, buffer)
    _, rows = csv_rows(buffer.getvalue())
    assert [row["name"] for row in rows] == [item.name for item in SAMPLE]


def test_csv_empty_list_writes_only_header():
    buffer = io.StringIO()
    to_csv([], buffer)
    assert buffer.getvalue().strip() == ",".join(FIELDS)


def test_csv_detail_has_one_row_per_album():
    buffer = io.StringIO()
    to_csv(DETAILED, buffer, detail=True)
    header, rows = csv_rows(buffer.getvalue())
    assert header == ALBUM_FIELDS
    assert rows == [
        {
            "artist_id": "1",
            "artist_name": "AC/DC",
            "album_id": "1",
            "title": "For Those About To Rock, We Salute You",
            "track_count": "10",
            "total_duration_ms": "2400000",
            "revenue": "9.90",
            "units_sold": "10",
        },
        {
            "artist_id": "1",
            "artist_name": "AC/DC",
            "album_id": "4",
            "title": "Let There Be Rock",
            "track_count": "8",
            "total_duration_ms": "2453674",
            "revenue": "5.94",
            "units_sold": "6",
        },
    ]


def test_csv_detail_requires_albums():
    with pytest.raises(ValueError, match="albums"):
        to_csv(SAMPLE, io.StringIO(), detail=True)


# Aggregation on a small in-memory database


@pytest.fixture
def memory_db():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(SAMPLE_SQL)
        yield conn


def test_repeated_sales_do_not_inflate_counts(memory_db):
    stats = {item.artist_id: item for item in get_artist_stats(memory_db)}
    assert stats[1] == ArtistStats(
        1, "Band", 2, 3, 7000, 2333, 4.95, 5, ("Blues", "Rock")
    )


def test_three_sales_at_099_are_exactly_297(memory_db):
    memory_db.execute("DELETE FROM InvoiceLine WHERE TrackId = 102")
    (band,) = get_artist_stats(memory_db, artist_id=1)
    assert band.revenue == 2.97
    assert band.units_sold == 3


def test_artists_without_albums_or_sales_get_zeros(memory_db):
    stats = {item.artist_id: item for item in get_artist_stats(memory_db)}
    assert stats[2] == ArtistStats(2, "Silent", 0, 0, 0, 0, 0.0, 0, ())
    assert stats[3] == ArtistStats(3, "Ünsold", 1, 1, 3000, 3000, 0.0, 0, ("Rock",))


def test_album_detail(memory_db):
    stats = {
        item.artist_id: item
        for item in get_artist_stats(memory_db, include_albums=True)
    }
    assert stats[1].albums == (
        AlbumStats(11, "First", 1, 4000, 1.98, 2),
        AlbumStats(10, "Second", 2, 3000, 2.97, 3),
    )
    assert stats[2].albums == ()
    assert stats[3].albums == (AlbumStats(12, "Only", 1, 3000, 0.0, 0),)


def test_find_artist_id_folds_non_ascii(memory_db):
    assert find_artist_id(memory_db, "ÜNSOLD") == 3
    assert find_artist_id(memory_db, "unsold") is None


def test_works_without_row_factory_and_does_not_close(memory_db):
    get_artist_stats(memory_db, include_albums=True)
    assert memory_db.execute("SELECT 1").fetchone() == (1,)


# CLI end to end against a small database file passed with --db


@pytest.fixture
def sample_db_path(tmp_path):
    path = tmp_path / "sample.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SAMPLE_SQL)
    return path


def test_cli_reads_the_database_given_with_db(sample_db_path, capsys):
    assert reporter.main(["--format", "json", "--db", str(sample_db_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(row["artist_id"], row["revenue"]) for row in data] == [
        (1, 4.95),
        (2, 0.0),
        (3, 0.0),
    ]


def test_cli_search_and_detail_on_sample_db(sample_db_path, tmp_path):
    output = tmp_path / "out" / "band.csv"
    argv = [
        "--format",
        "csv",
        "--db",
        str(sample_db_path),
        "--artist",
        "BAND",
        "--detail",
        "--output",
        str(output),
    ]
    assert reporter.main(argv) == 0
    _, rows = csv_rows(output.read_text(encoding="utf-8"))
    assert [(row["title"], row["revenue"]) for row in rows] == [
        ("First", "1.98"),
        ("Second", "2.97"),
    ]


def test_cli_never_writes_to_the_database(sample_db_path):
    before = sample_db_path.read_bytes()
    reporter.main(["--format", "json", "--db", str(sample_db_path), "--detail"])
    assert sample_db_path.read_bytes() == before


# Schema validation


def test_validate_schema_accepts_sample_db(memory_db):
    validate_schema(memory_db)


def test_validate_schema_lists_every_missing_table():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE Unrelated (x)")
        with pytest.raises(SchemaError) as excinfo:
            validate_schema(conn)
    message = str(excinfo.value)
    for table in reporter.REQUIRED_SCHEMA:
        assert f"falta la tabla {table}" in message


def test_validate_schema_lists_missing_columns(memory_db):
    memory_db.executescript(
        """
        DROP TABLE Track;
        CREATE TABLE Track (TrackId INTEGER, AlbumId INTEGER);
        DROP TABLE Genre;
        """
    )
    with pytest.raises(SchemaError) as excinfo:
        validate_schema(memory_db)
    assert str(excinfo.value) == (
        "faltan columnas en Track: GenreId, Milliseconds; falta la tabla Genre"
    )


def test_validate_schema_ignores_name_case():
    with closing(sqlite3.connect(":memory:")) as conn:
        for table, columns in reporter.REQUIRED_SCHEMA.items():
            conn.execute(
                f"CREATE TABLE {table.lower()} ({', '.join(c.upper() for c in columns)})"
            )
        validate_schema(conn)


def test_validate_schema_does_not_require_extra_tables(memory_db):
    """Customer, Invoice, Playlist... are not read by the report."""
    validate_schema(memory_db)
    assert "Invoice" not in reporter.REQUIRED_SCHEMA


# export / write_output


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_export_matches_the_exporters(fmt):
    expected = io.StringIO()
    (to_json if fmt == "json" else to_csv)(SAMPLE, expected)
    buffer = io.StringIO()
    export(SAMPLE, buffer, fmt=fmt)
    assert buffer.getvalue() == expected.getvalue()


def test_export_csv_detail():
    buffer = io.StringIO()
    export(DETAILED, buffer, fmt="csv", detail=True)
    header, rows = csv_rows(buffer.getvalue())
    assert header == ALBUM_FIELDS
    assert len(rows) == 2


def test_export_rejects_unknown_format():
    with pytest.raises(ValueError, match="format"):
        export(SAMPLE, io.StringIO(), fmt="xml")


def test_write_output_creates_directories_and_writes_utf8(tmp_path):
    path = tmp_path / "a" / "b" / "artists.json"
    write_output(path, SAMPLE, fmt="json")
    data = json.loads(path.read_bytes().decode("utf-8"))
    assert data[2]["name"] == "Antônio Carlos Jobim"


def test_write_output_csv_has_no_blank_lines(tmp_path):
    path = tmp_path / "artists.csv"
    write_output(path, SAMPLE, fmt="csv")
    raw = path.read_bytes()
    assert b"\r\r" not in raw and b"\n\n" not in raw
    assert raw.count(b"\r\n") == len(SAMPLE) + 1  # csv module line endings


def test_write_output_overwrites_existing_file(tmp_path):
    path = tmp_path / "artists.json"
    path.write_text("old content that is longer than the new one" * 100)
    write_output(path, [], fmt="json")
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_write_output_raises_oserror_when_path_is_a_directory(tmp_path):
    with pytest.raises(OSError):
        write_output(tmp_path, SAMPLE, fmt="json")


def test_write_output_raises_oserror_when_parent_is_a_file(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(OSError):
        write_output(blocker / "artists.json", SAMPLE, fmt="json")


def test_cli_rejects_database_without_chinook_schema(tmp_path, capsys):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE Unrelated (x)")
    assert reporter.main(["--format", "json", "--db", str(path)]) == 1
    err = capsys.readouterr().err
    assert f"{path} no es una base Chinook válida" in err
    assert "falta la tabla Artist" in err
    assert "no se pudo abrir" not in err


def test_cli_partial_schema_names_missing_columns(sample_db_path, capsys):
    with closing(sqlite3.connect(sample_db_path)) as conn:
        conn.executescript(
            """
            ALTER TABLE InvoiceLine RENAME TO InvoiceLine_old;
            CREATE TABLE InvoiceLine (TrackId INTEGER, Quantity INTEGER);
            """
        )
    assert reporter.main(["--format", "json", "--db", str(sample_db_path)]) == 1
    assert "faltan columnas en InvoiceLine: UnitPrice" in capsys.readouterr().err
