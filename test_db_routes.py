"""Tests for the chinook.db-backed Blueprint routes."""

import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from app import app
from db_routes import CHINOOK_DB_PATH, AlbumOut, get_db_connection


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_db_artist_albums_sorted_by_title(client):
    response = client.get("/db/artists/1/albums")
    assert response.status_code == 200
    assert response.get_json() == [
        {
            "album_id": 1,
            "title": "For Those About To Rock We Salute You",
            "artist_id": 1,
        },
        {"album_id": 4, "title": "Let There Be Rock", "artist_id": 1},
    ]


def test_db_artist_albums_aerosmith(client):
    response = client.get("/db/artists/3/albums")
    assert response.status_code == 200
    assert [album["title"] for album in response.get_json()] == ["Big Ones"]


def test_db_artist_without_albums_returns_empty_list(client):
    response = client.get("/db/artists/25/albums")
    assert response.status_code == 200
    assert response.get_json() == []


def test_db_artist_albums_not_found(client):
    response = client.get("/db/artists/999999/albums")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Artist not found"}


def test_in_memory_route_still_served_without_prefix(client):
    response = client.get("/artists/1/albums")
    assert response.status_code == 200
    assert {album["title"] for album in response.get_json()} == {
        "For Those About To Rock",
        "Let There Be Rock",
    }


def test_db_artist_albums_returns_json_content_type(client):
    response = client.get("/db/artists/1/albums")
    assert response.status_code == 200
    assert response.mimetype == "application/json"


def test_db_artist_albums_items_have_exact_keys(client):
    response = client.get("/db/artists/90/albums")
    albums = response.get_json()
    assert albums
    for album in albums:
        assert set(album) == {"album_id", "title", "artist_id"}
        assert isinstance(album["album_id"], int)
        assert isinstance(album["title"], str)
        assert album["artist_id"] == 90


def test_db_artist_albums_many_albums_sorted_and_complete(client):
    response = client.get("/db/artists/90/albums")
    titles = [album["title"] for album in response.get_json()]
    assert len(titles) == 21
    assert titles == sorted(titles)


def test_db_artist_albums_artist_id_zero_not_found(client):
    response = client.get("/db/artists/0/albums")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Artist not found"}


@pytest.mark.parametrize("artist_id", ["abc", "-1", "1.5"])
def test_db_artist_albums_invalid_artist_id_not_routed(client, artist_id):
    response = client.get(f"/db/artists/{artist_id}/albums")
    assert response.status_code == 404
    assert response.get_json(silent=True) != {"error": "Artist not found"}


def test_db_artist_albums_rejects_post(client):
    response = client.post("/db/artists/1/albums")
    assert response.status_code == 405


def test_db_artist_albums_match_database_for_every_artist(client):
    """Every artist in chinook.db gets exactly its albums, sorted by title."""
    uri = f"{CHINOOK_DB_PATH.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        artist_ids = [
            row[0] for row in connection.execute("SELECT ArtistId FROM Artist")
        ]
        expected_by_artist = {
            artist_id: [
                {"album_id": album_id, "title": title, "artist_id": artist_id}
                for album_id, title in connection.execute(
                    "SELECT AlbumId, Title FROM Album "
                    "WHERE ArtistId = ? ORDER BY Title",
                    (artist_id,),
                )
            ]
            for artist_id in artist_ids
        }

    assert len(expected_by_artist) == 275
    for artist_id, expected in expected_by_artist.items():
        response = client.get(f"/db/artists/{artist_id}/albums")
        assert response.status_code == 200, artist_id
        assert response.get_json() == expected, artist_id


def test_album_out_maps_chinook_columns_to_api_keys():
    album = AlbumOut.model_validate({"AlbumId": 5, "Title": "Big Ones", "ArtistId": 3})
    assert album.model_dump() == {"album_id": 5, "title": "Big Ones", "artist_id": 3}


@pytest.mark.parametrize(
    "row",
    [
        {"AlbumId": 5, "Title": None, "ArtistId": 3},
        {"AlbumId": "not-a-number", "Title": "Big Ones", "ArtistId": 3},
        {"AlbumId": 5, "ArtistId": 3},
    ],
)
def test_album_out_rejects_invalid_rows(row):
    with pytest.raises(ValidationError):
        AlbumOut.model_validate(row)


def test_get_db_connection_is_read_only():
    """Writes through get_db_connection must fail; the no-op UPDATE is rolled back."""
    with closing(get_db_connection()) as connection:
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("UPDATE Artist SET Name = Name WHERE ArtistId = 1")
        finally:
            connection.rollback()


def test_get_db_connection_rows_accessible_by_column_name():
    with closing(get_db_connection()) as connection:
        row = connection.execute(
            "SELECT ArtistId, Name FROM Artist WHERE ArtistId = 1"
        ).fetchone()
    assert row["ArtistId"] == 1
    assert row["Name"] == "AC/DC"
