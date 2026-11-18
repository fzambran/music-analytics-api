"""Unit tests for get_artist_albums with the database connection mocked."""

from unittest.mock import MagicMock

import pytest

from music_analytics_api import db_routes
from music_analytics_api.app import create_app


def make_fake_connection(artist_row, album_rows):
    """Fake sqlite3 connection: first execute() is the artist lookup, second the albums."""
    connection = MagicMock()
    artist_cursor = MagicMock()
    artist_cursor.fetchone.return_value = artist_row
    albums_cursor = MagicMock()
    albums_cursor.fetchall.return_value = album_rows
    connection.execute.side_effect = [artist_cursor, albums_cursor]
    return connection


@pytest.fixture
def fake_db(monkeypatch):
    """Replace get_db_connection with a factory returning the configured fake."""
    holder = {}

    def configure(artist_row, album_rows=()):
        holder["connection"] = make_fake_connection(artist_row, list(album_rows))
        monkeypatch.setattr(
            db_routes, "get_db_connection", lambda: holder["connection"]
        )
        return holder["connection"]

    return configure


def call_handler(artist_id):
    app = create_app()
    with app.test_request_context():
        response = app.make_response(db_routes.get_artist_albums(artist_id))
    return response.status_code, response.get_json()


def test_maps_rows_to_api_keys_in_query_order(fake_db):
    fake_db(
        {"ArtistId": 7},
        [
            {"AlbumId": 2, "Title": "A", "ArtistId": 7},
            {"AlbumId": 1, "Title": "B", "ArtistId": 7},
        ],
    )
    status, body = call_handler(7)
    assert status == 200
    assert body == [
        {"album_id": 2, "title": "A", "artist_id": 7},
        {"album_id": 1, "title": "B", "artist_id": 7},
    ]


def test_returns_404_and_skips_album_query_when_artist_missing(fake_db):
    connection = fake_db(None)
    status, body = call_handler(42)
    assert status == 404
    assert body == {"error": "Artist not found"}
    assert connection.execute.call_count == 1


def test_returns_empty_list_when_artist_has_no_albums(fake_db):
    fake_db({"ArtistId": 7}, [])
    assert call_handler(7) == (200, [])


def test_uses_parameterized_queries_and_closes_connection(fake_db):
    connection = fake_db({"ArtistId": 7}, [])
    call_handler(7)
    for call in connection.execute.call_args_list:
        sql, params = call.args
        assert "?" in sql
        assert params == (7,)
    connection.close.assert_called_once()


def test_closes_connection_when_query_fails(monkeypatch):
    connection = MagicMock()
    connection.execute.side_effect = db_routes.sqlite3.OperationalError("db locked")
    monkeypatch.setattr(db_routes, "get_db_connection", lambda: connection)
    with pytest.raises(db_routes.sqlite3.OperationalError):
        call_handler(7)
    connection.close.assert_called_once()


def test_closes_connection_when_artist_missing(fake_db):
    connection = fake_db(None)
    status, _ = call_handler(42)
    assert status == 404
    connection.close.assert_called_once()


@pytest.fixture
def api_client():
    """Test client of a fresh app, without TESTING so errors go through Flask's handlers."""
    return create_app().test_client()


def test_database_error_answers_json_500_and_closes_connection(monkeypatch, api_client):
    connection = MagicMock()
    connection.execute.side_effect = db_routes.sqlite3.OperationalError("db locked")
    monkeypatch.setattr(db_routes, "get_db_connection", lambda: connection)

    response = api_client.get("/db/artists/7/albums")

    assert response.status_code == 500
    assert response.mimetype == "application/json"
    assert response.get_json() == {"error": "Database unavailable"}
    connection.close.assert_called_once()


def test_invalid_row_answers_json_500(fake_db, api_client):
    fake_db({"ArtistId": 3}, [{"AlbumId": 5, "Title": None, "ArtistId": 3}])

    response = api_client.get("/db/artists/3/albums")

    assert response.status_code == 500
    assert response.mimetype == "application/json"
    assert response.get_json() == {"error": "Invalid data in database"}


def test_database_error_logs_traceback_but_hides_it_from_the_client(
    monkeypatch, api_client, caplog
):
    connection = MagicMock()
    connection.execute.side_effect = db_routes.sqlite3.OperationalError("secret detail")
    monkeypatch.setattr(db_routes, "get_db_connection", lambda: connection)

    response = api_client.get("/db/artists/7/albums")

    assert "secret detail" not in response.get_data(as_text=True)
    records = [r for r in caplog.records if r.name == "music_analytics_api"]
    assert len(records) == 1
    assert records[0].levelname == "ERROR"
    assert "secret detail" in caplog.text
