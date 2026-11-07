"""Tests for the chinook.db-backed Blueprint routes."""

import pytest

from app import app


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
