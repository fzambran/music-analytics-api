"""Unit tests for reporter.py exporters and aggregation, without chinook.db."""

import csv
import io
import json
import sqlite3
from contextlib import closing

import pytest

from reporter import FIELDS, ArtistStats, get_artist_stats, to_csv, to_json

SAMPLE = [
    ArtistStats(1, "AC/DC", 2, 18, 4853674, 269649, 15.0, 16),
    ArtistStats(2, 'Earth, Wind & "Fire"', 1, 3, 600000, 200000, 138.6, 140),
    ArtistStats(3, "Antônio Carlos Jobim", 0, 0, 0, 0, 0.0, 0),
]


def test_json_keys_in_field_order():
    buffer = io.StringIO()
    to_json(SAMPLE, buffer)
    data = json.loads(buffer.getvalue())
    assert [list(row) for row in data] == [list(FIELDS)] * len(SAMPLE)
    assert data[1]["revenue"] == 138.6


def test_json_keeps_non_ascii_unescaped():
    buffer = io.StringIO()
    to_json(SAMPLE, buffer)
    assert "Antônio" in buffer.getvalue()
    assert buffer.getvalue().endswith("\n")


def test_json_empty_list():
    buffer = io.StringIO()
    to_json([], buffer)
    assert json.loads(buffer.getvalue()) == []


def test_csv_header_and_revenue_format():
    buffer = io.StringIO()
    to_csv(SAMPLE, buffer)
    buffer.seek(0)
    reader = csv.DictReader(buffer)
    rows = list(reader)
    assert tuple(reader.fieldnames) == FIELDS
    assert [row["revenue"] for row in rows] == ["15.00", "138.60", "0.00"]


def test_csv_round_trips_names_with_commas_and_quotes():
    buffer = io.StringIO()
    to_csv(SAMPLE, buffer)
    buffer.seek(0)
    names = [row["name"] for row in csv.DictReader(buffer)]
    assert names == [item.name for item in SAMPLE]


def test_csv_empty_list_writes_only_header():
    buffer = io.StringIO()
    to_csv([], buffer)
    assert buffer.getvalue().strip() == ",".join(FIELDS)


@pytest.fixture
def memory_db():
    """Minimal Chinook-like schema: artist 1 has 2 albums and repeated sales."""
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(
            """
            CREATE TABLE Artist (ArtistId INTEGER PRIMARY KEY, Name TEXT);
            CREATE TABLE Album (AlbumId INTEGER PRIMARY KEY, Title TEXT, ArtistId INTEGER);
            CREATE TABLE Track (
                TrackId INTEGER PRIMARY KEY, Name TEXT, AlbumId INTEGER,
                Milliseconds INTEGER, UnitPrice NUMERIC
            );
            CREATE TABLE InvoiceLine (
                InvoiceLineId INTEGER PRIMARY KEY, InvoiceId INTEGER, TrackId INTEGER,
                UnitPrice NUMERIC, Quantity INTEGER
            );
            INSERT INTO Artist VALUES (1, 'Band'), (2, 'Silent'), (3, 'Unsold');
            INSERT INTO Album VALUES (10, 'First', 1), (11, 'Second', 1), (12, 'Only', 3);
            INSERT INTO Track VALUES
                (100, 'a', 10, 1000, 0.99),
                (101, 'b', 10, 2000, 0.99),
                (102, 'c', 11, 4000, 0.99),
                (103, 'd', 12, 3000, 0.99);
            INSERT INTO InvoiceLine VALUES
                (1, 1, 100, 0.99, 1),
                (2, 2, 100, 0.99, 1),
                (3, 3, 100, 0.99, 1),
                (4, 3, 102, 0.99, 2);
            """
        )
        yield conn


def test_repeated_sales_do_not_inflate_counts(memory_db):
    stats = {item.artist_id: item for item in get_artist_stats(memory_db)}
    assert stats[1] == ArtistStats(1, "Band", 2, 3, 7000, 2333, 4.95, 5)


def test_three_sales_at_099_are_exactly_297(memory_db):
    memory_db.execute("DELETE FROM InvoiceLine WHERE TrackId = 102")
    (band,) = get_artist_stats(memory_db, artist_id=1)
    assert band.revenue == 2.97
    assert band.units_sold == 3


def test_artists_without_albums_or_sales_get_zeros(memory_db):
    stats = {item.artist_id: item for item in get_artist_stats(memory_db)}
    assert stats[2] == ArtistStats(2, "Silent", 0, 0, 0, 0, 0.0, 0)
    assert stats[3] == ArtistStats(3, "Unsold", 1, 1, 3000, 3000, 0.0, 0)


def test_works_without_row_factory_and_does_not_close(memory_db):
    get_artist_stats(memory_db)
    assert memory_db.execute("SELECT 1").fetchone() == (1,)
