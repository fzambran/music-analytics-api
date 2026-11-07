"""Tests for the Music Analytics API routes."""

import pytest

import routes
from analytics import calculate_average_tracks
from app import app
from models import Album, Artist, MusicStore


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_get_artist_not_found(client):
    response = client.get("/artists/999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Artist not found"}


def test_get_artist_albums_not_found(client):
    response = client.get("/artists/999/albums")
    assert response.status_code == 404


def test_get_artist_albums(client):
    response = client.get("/artists/1/albums")
    assert response.status_code == 200
    assert {album["title"] for album in response.get_json()} == {
        "For Those About To Rock",
        "Let There Be Rock",
    }


@pytest.mark.parametrize("query", ["", "   "])
def test_search_requires_query(client, query):
    response = client.get("/artists/search", query_string={"q": query})
    assert response.status_code == 400


def test_search_rejects_long_query(client):
    response = client.get("/artists/search", query_string={"q": "a" * 101})
    assert response.status_code == 400


def test_search_artists(client):
    response = client.get("/artists/search", query_string={"q": "  ac  "})
    assert response.status_code == 200
    assert {artist["name"] for artist in response.get_json()} == {"AC/DC", "Accept"}


def test_average_tracks(client):
    response = client.get("/stats/average-tracks")
    assert response.status_code == 200
    # Sample data: (10 + 8 + 10 + 9 + 15 + 13 + 12 + 13) / 8 = 90 / 8
    assert response.get_json() == {"average_tracks": pytest.approx(11.25)}


def test_calculate_average_tracks_empty():
    assert calculate_average_tracks([]) == 0.0


def test_get_artists_returns_all_sample_artists(client):
    response = client.get("/artists")

    assert response.status_code == 200
    artists = response.get_json()
    assert len(artists) == 5
    assert artists[0] == {"artist_id": 1, "name": "AC/DC", "album_count": 2}


def test_get_artist_existing_id_returns_artist(client):
    response = client.get("/artists/4")

    assert response.status_code == 200
    assert response.get_json() == {
        "artist_id": 4,
        "name": "Alanis Morissette",
        "album_count": 1,
    }


@pytest.mark.parametrize("path", ["/artists/abc", "/artists/-1", "/artists/abc/albums"])
def test_artist_routes_non_integer_id_returns_404(client, path):
    response = client.get(path)

    assert response.status_code == 404


def test_search_missing_query_param_returns_400(client):
    response = client.get("/artists/search")

    assert response.status_code == 400
    assert response.get_json() == {"error": "Query parameter 'q' is required"}


def test_search_query_at_max_length_is_accepted(client):
    response = client.get("/artists/search", query_string={"q": "a" * 100})

    assert response.status_code == 200
    assert response.get_json() == []


def test_search_long_query_error_message(client):
    response = client.get("/artists/search", query_string={"q": "a" * 101})

    assert response.get_json() == {
        "error": "Query parameter 'q' must be at most 100 characters"
    }


def test_search_is_case_insensitive(client):
    response = client.get("/artists/search", query_string={"q": "ALICE"})

    assert response.status_code == 200
    assert [artist["name"] for artist in response.get_json()] == ["Alice In Chains"]


def test_search_no_matches_returns_empty_list(client):
    response = client.get("/artists/search", query_string={"q": "zzz"})

    assert response.status_code == 200
    assert response.get_json() == []


def test_get_albums_returns_all_sample_albums(client):
    response = client.get("/albums")

    assert response.status_code == 200
    albums = response.get_json()
    assert len(albums) == 8
    assert albums[4] == {
        "album_id": 5,
        "title": "Big Ones",
        "artist_id": 3,
        "track_count": 15,
    }


def test_album_stats_returns_top_five_by_adjusted_popularity(client):
    response = client.get("/stats/albums")

    assert response.status_code == 200
    stats = response.get_json()
    # popularity = tracks * 5, adjusted = popularity * 1.2; ties keep store order
    assert [album["album_id"] for album in stats] == [5, 6, 8, 7, 1]


def test_album_stats_top_album_values_and_tier(client):
    response = client.get("/stats/albums")

    top = response.get_json()[0]
    assert top["title"] == "Big Ones"
    assert top["original_popularity"] == 75
    assert top["adjusted_popularity"] == pytest.approx(90.0)
    assert top["tier"] == "platinum"


def test_album_stats_below_threshold_is_gold(client):
    response = client.get("/stats/albums")

    second = response.get_json()[1]
    assert second["adjusted_popularity"] == pytest.approx(78.0)
    assert second["tier"] == "gold"


@pytest.fixture
def custom_store(monkeypatch):
    """Replace the routes' shared store with a fresh, empty MusicStore."""
    store = MusicStore()
    store._artists.clear()
    store._albums.clear()
    monkeypatch.setattr(routes, "music_store", store)
    return store


def add_album(store: MusicStore, album_id: int, track_count: int) -> None:
    """Add an album with the given track count to the store."""
    store._albums[album_id] = Album(album_id, f"Album {album_id}", 1, track_count)


def test_get_artists_empty_store_returns_empty_list(client, custom_store):
    response = client.get("/artists")

    assert response.status_code == 200
    assert response.get_json() == []


def test_get_albums_empty_store_returns_empty_list(client, custom_store):
    response = client.get("/albums")

    assert response.status_code == 200
    assert response.get_json() == []


def test_get_artist_albums_artist_without_albums_returns_empty_list(
    client, custom_store
):
    custom_store._artists[42] = Artist(42, "Solo Artist")

    response = client.get("/artists/42/albums")

    assert response.status_code == 200
    assert response.get_json() == []


def test_average_tracks_empty_store_returns_zero(client, custom_store):
    response = client.get("/stats/average-tracks")

    assert response.status_code == 200
    assert response.get_json() == {"average_tracks": 0.0}


def test_album_stats_empty_store_returns_empty_list(client, custom_store):
    response = client.get("/stats/albums")

    assert response.status_code == 200
    assert response.get_json() == []


@pytest.mark.parametrize(("track_count", "included"), [(5, False), (6, True)])
def test_album_stats_min_tracks_boundary(client, custom_store, track_count, included):
    add_album(custom_store, 1, track_count)

    response = client.get("/stats/albums")

    assert (len(response.get_json()) == 1) is included


def test_album_stats_popularity_is_five_points_per_track(client, custom_store):
    add_album(custom_store, 1, 6)

    response = client.get("/stats/albums")

    album = response.get_json()[0]
    # 6 tracks * 5 = 30; 30 * 1.2 = 36
    assert album["original_popularity"] == 30
    assert album["adjusted_popularity"] == pytest.approx(36.0)
    assert album["tier"] == "gold"


def test_album_stats_limits_results_to_five(client, custom_store):
    for album_id in range(1, 8):
        add_album(custom_store, album_id, 10 + album_id)

    response = client.get("/stats/albums")

    assert [album["album_id"] for album in response.get_json()] == [7, 6, 5, 4, 3]


def test_search_max_length_query_with_surrounding_spaces_is_accepted(client):
    response = client.get("/artists/search", query_string={"q": f"  {'a' * 100}  "})

    assert response.status_code == 200


def test_search_query_with_special_characters(client):
    response = client.get("/artists/search", query_string={"q": "c/d"})

    assert response.status_code == 200
    assert [artist["name"] for artist in response.get_json()] == ["AC/DC"]


@pytest.mark.parametrize("path", ["/artists", "/albums", "/stats/albums"])
def test_routes_reject_post_with_405(client, path):
    response = client.post(path)

    assert response.status_code == 405


@pytest.fixture
def spy_album_stats(monkeypatch):
    """Replace calculate_album_stats in routes with a stub that records its input."""
    calls = []

    def fake_calculate_album_stats(albums: list[dict]) -> list[dict]:
        calls.append(albums)
        return [{"stub": True}]

    monkeypatch.setattr(routes, "calculate_album_stats", fake_calculate_album_stats)
    return calls


@pytest.fixture
def spy_average_tracks(monkeypatch):
    """Replace calculate_average_tracks in routes with a stub that records its input."""
    calls = []

    def fake_calculate_average_tracks(albums: list[dict]) -> float:
        calls.append(albums)
        return 7.5

    monkeypatch.setattr(
        routes, "calculate_average_tracks", fake_calculate_average_tracks
    )
    return calls


def test_album_stats_passes_album_dicts_with_popularity_to_analytics(
    client, custom_store, spy_album_stats
):
    add_album(custom_store, 1, 4)

    client.get("/stats/albums")

    assert spy_album_stats == [
        [{"album_id": 1, "title": "Album 1", "track_count": 4, "popularity": 20}]
    ]


def test_album_stats_returns_analytics_result_as_json(
    client, custom_store, spy_album_stats
):
    response = client.get("/stats/albums")

    assert response.status_code == 200
    assert response.get_json() == [{"stub": True}]


def test_average_tracks_passes_only_track_counts_to_analytics(
    client, custom_store, spy_average_tracks
):
    add_album(custom_store, 1, 4)
    add_album(custom_store, 2, 9)

    client.get("/stats/average-tracks")

    assert spy_average_tracks == [[{"track_count": 4}, {"track_count": 9}]]


def test_average_tracks_wraps_analytics_result_in_object(
    client, custom_store, spy_average_tracks
):
    response = client.get("/stats/average-tracks")

    assert response.get_json() == {"average_tracks": 7.5}


def test_get_artist_zero_id_returns_404(client):
    response = client.get("/artists/0")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Artist not found"}


@pytest.mark.parametrize(
    "path",
    [
        "/artists",
        "/artists/1",
        "/artists/1/albums",
        "/artists/search?q=ac",
        "/artists/search",
        "/artists/999",
        "/albums",
        "/stats/albums",
        "/stats/average-tracks",
    ],
)
def test_routes_respond_with_json_content_type(client, path):
    response = client.get(path)

    assert response.mimetype == "application/json"
