"""API Routes for Music Analytics."""

from flask import jsonify, request

from analytics import calculate_album_stats, calculate_average_tracks
from app import app
from models import Album, music_store

MAX_QUERY_LENGTH = 100
POPULARITY_PER_TRACK = 5  # Simple popularity metric: each track adds 5 points


def _error_response(message: str, status: int):
    """Return a JSON error body of the form {"error": message} with the given status."""
    return jsonify({"error": message}), status


def _artist_not_found():
    """Return the 404 response used when an artist ID does not exist."""
    return _error_response("Artist not found", 404)


def _jsonify_all(items: list):
    """Return a JSON response with the dict form of each item."""
    return jsonify([item.to_dict() for item in items])


def _album_stats_input(album: Album) -> dict:
    """Build the dict calculate_album_stats expects, with a track-based popularity."""
    return {
        "album_id": album.album_id,
        "title": album.title,
        "track_count": album.track_count,
        "popularity": album.track_count * POPULARITY_PER_TRACK,
    }


@app.route("/artists", methods=["GET"])
def get_artists():
    """Return all artists."""
    artists = music_store.get_all_artists()
    return _jsonify_all(artists)


@app.route("/artists/search", methods=["GET"])
def search_artists():
    """Return artists whose name matches the 'q' query parameter (case-insensitive substring)."""
    query = request.args.get("q", "").strip()
    if not query:
        return _error_response("Query parameter 'q' is required", 400)
    if len(query) > MAX_QUERY_LENGTH:
        return _error_response(
            f"Query parameter 'q' must be at most {MAX_QUERY_LENGTH} characters", 400
        )
    artists = music_store.search_artists(query)
    return _jsonify_all(artists)


@app.route("/artists/<int:artist_id>", methods=["GET"])
def get_artist(artist_id: int):
    """Return a single artist by ID."""
    artist = music_store.get_artist(artist_id)
    if artist is None:
        return _artist_not_found()
    return jsonify(artist.to_dict())


@app.route("/artists/<int:artist_id>/albums", methods=["GET"])
def get_artist_albums(artist_id: int):
    """Return all albums for an artist."""
    artist = music_store.get_artist(artist_id)
    if artist is None:
        return _artist_not_found()
    return _jsonify_all(artist.albums)


@app.route("/albums", methods=["GET"])
def get_albums():
    """Return all albums."""
    albums = music_store.get_all_albums()
    return _jsonify_all(albums)


@app.route("/stats/albums", methods=["GET"])
def get_album_stats():
    """Return album statistics."""
    albums = music_store.get_all_albums()
    stats = calculate_album_stats([_album_stats_input(album) for album in albums])
    return jsonify(stats)


@app.route("/stats/average-tracks", methods=["GET"])
def get_average_tracks():
    """Return average tracks per album."""
    albums = music_store.get_all_albums()
    album_dicts = [{"track_count": album.track_count} for album in albums]
    average_tracks = calculate_average_tracks(album_dicts)
    return jsonify({"average_tracks": average_tracks})
