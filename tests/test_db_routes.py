"""Tests for the chinook.db-backed Blueprint routes."""

import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from pydantic import ValidationError

from music_analytics_api import reporter
from music_analytics_api.app import create_app
from music_analytics_api.db_routes import (
    CHINOOK_DB_PATH,
    DEFAULT_PAGE_SIZE,
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    AlbumOut,
    ArtistOut,
    get_db_connection,
)


@pytest.fixture
def client():
    app = create_app()
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


def test_artist_out_maps_chinook_columns_to_api_keys():
    artist = ArtistOut.model_validate({"ArtistId": 1, "Name": "AC/DC"})
    assert artist.model_dump() == {"artist_id": 1, "name": "AC/DC"}


def test_artist_out_accepts_a_null_name():
    """Artist.Name is nullable in Chinook; a NULL name is data, not an error."""
    assert ArtistOut.model_validate({"ArtistId": 1, "Name": None}).name is None


@pytest.mark.parametrize(
    "row",
    [
        {"ArtistId": "x", "Name": "AC/DC"},
        {"ArtistId": 1, "Name": 123},
        {"Name": "AC/DC"},
    ],
)
def test_artist_out_rejects_invalid_rows(row):
    with pytest.raises(ValidationError):
        ArtistOut.model_validate(row)


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


def test_get_db_connection_expands_the_home_directory(tmp_path, monkeypatch):
    """A path with `~`, as given to --db, opens the file in the home directory."""
    with closing(sqlite3.connect(tmp_path / "home.db")) as connection:
        connection.execute("CREATE TABLE Marker (Value TEXT)")
        connection.execute("INSERT INTO Marker VALUES ('home')")
        connection.commit()
    monkeypatch.setenv("HOME", str(tmp_path))

    with closing(get_db_connection("~/home.db")) as connection:
        assert (
            connection.execute("SELECT Value FROM Marker").fetchone()["Value"] == "home"
        )


def test_reporter_cli_accepts_a_db_path_with_tilde(tmp_path, monkeypatch, capsys):
    """`--db ~/chinook.db` reads the database instead of failing to open it."""
    shutil.copy(CHINOOK_DB_PATH, tmp_path / "chinook.db")
    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = reporter.main(
        ["--format", "csv", "--artist-id", "1", "--db", "~/chinook.db"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines()[1].startswith("1,AC/DC,2,18,")


def test_missing_database_answers_json_500(tmp_path):
    """With CHINOOK_DB_PATH pointing nowhere, /db answers a JSON 500, not HTML."""
    code = (
        "from music_analytics_api.app import create_app\n"
        "response = create_app().test_client().get('/db/artists/1/albums')\n"
        "print(response.status_code, response.mimetype, response.get_json())"
    )
    env = {**os.environ, "CHINOOK_DB_PATH": str(tmp_path / "missing.db")}

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert (
        result.stdout.strip()
        == "500 application/json {'error': 'Database unavailable'}"
    )


# --- GET /db/artists (paginated) --------------------------------------------


LIMIT_ERROR = "Query parameter 'limit' must be an integer from 1 to 100"
OFFSET_ERROR = (
    "Query parameter 'offset' must be an integer from 0 to 9223372036854775807"
)


def _chinook_artists() -> list[dict]:
    """Every artist in chinook.db as the API returns it, ordered by ArtistId."""
    uri = f"{CHINOOK_DB_PATH.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return [
            {"artist_id": artist_id, "name": name}
            for artist_id, name in connection.execute(
                "SELECT ArtistId, Name FROM Artist ORDER BY ArtistId"
            )
        ]


def test_db_artists_first_page_by_default(client):
    response = client.get("/db/artists")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert body["total"] == 275
    assert body["limit"] == DEFAULT_PAGE_SIZE == 20
    assert body["offset"] == 0
    assert body["items"] == _chinook_artists()[:20]
    assert body["items"][0] == {"artist_id": 1, "name": "AC/DC"}


def test_db_artists_pages_cover_every_artist_once(client):
    """Walking the pages with limit/offset returns all 275 artists, in order."""
    seen = []
    offset = 0
    while True:
        body = client.get(
            "/db/artists", query_string={"limit": 50, "offset": offset}
        ).get_json()
        if not body["items"]:
            break
        seen.extend(body["items"])
        offset += 50

    assert seen == _chinook_artists()
    assert offset == 300


def test_db_artists_last_partial_page(client):
    body = client.get("/db/artists?limit=20&offset=260").get_json()

    assert [artist["artist_id"] for artist in body["items"]] == list(range(261, 276))
    assert (body["total"], body["limit"], body["offset"]) == (275, 20, 260)


@pytest.mark.parametrize("offset", ["275", "1000", str(MAX_OFFSET)])
def test_db_artists_offset_past_the_end_is_an_empty_page(client, offset):
    """Past the last artist there is nothing left, up to SQLite's largest integer."""
    response = client.get("/db/artists", query_string={"offset": offset})

    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    assert body["total"] == 275
    assert body["offset"] == int(offset)


@pytest.mark.parametrize("limit", ["1", str(MAX_PAGE_SIZE)])
def test_db_artists_accepts_limit_bounds(client, limit):
    body = client.get("/db/artists", query_string={"limit": limit}).get_json()

    assert len(body["items"]) == int(limit)


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"limit": "0"}, LIMIT_ERROR),
        ({"limit": "101"}, LIMIT_ERROR),
        ({"limit": "abc"}, LIMIT_ERROR),
        ({"limit": ""}, LIMIT_ERROR),
        ({"limit": "-5"}, LIMIT_ERROR),
        ({"limit": "2.5"}, LIMIT_ERROR),
        ({"offset": "-1"}, OFFSET_ERROR),
        ({"offset": "x"}, OFFSET_ERROR),
        ({"offset": " 5"}, OFFSET_ERROR),
        ({"offset": "+5"}, OFFSET_ERROR),
        ({"offset": "٥"}, OFFSET_ERROR),
        ({"offset": str(MAX_OFFSET + 1)}, OFFSET_ERROR),
        ({"offset": "99999999999999999999999"}, OFFSET_ERROR),
        # Past Python's 4300-digit int() limit: the message stays the API's own.
        ({"offset": "9" * 5000}, OFFSET_ERROR),
        ({"limit": "1" * 5000}, LIMIT_ERROR),
    ],
)
def test_db_artists_rejects_invalid_paging_params(client, params, message):
    response = client.get("/db/artists", query_string=params)

    assert response.status_code == 400
    assert response.get_json() == {"error": message}


@pytest.mark.parametrize(
    ("params", "limit", "offset"),
    [
        ({"limit": "005"}, 5, 0),
        ({"limit": "0" * 5000 + "5"}, 5, 0),
        ({"offset": "0" * 5000}, 20, 0),
        ({"offset": "0" * 5000 + "40"}, 20, 40),
    ],
)
def test_db_artists_ignores_leading_zeros(client, params, limit, offset):
    """Leading zeros do not change the value, however many there are."""
    response = client.get("/db/artists", query_string=params)

    assert response.status_code == 200
    body = response.get_json()
    assert (body["limit"], body["offset"]) == (limit, offset)
    assert body["items"][0]["artist_id"] == offset + 1


def test_db_artists_rejects_post(client):
    assert client.post("/db/artists").status_code == 405
