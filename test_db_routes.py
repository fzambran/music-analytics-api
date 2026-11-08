"""Tests for the chinook.db-backed Blueprint routes."""

import pytest
from pydantic import ValidationError

from app import app
from db_routes import AlbumOut


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
