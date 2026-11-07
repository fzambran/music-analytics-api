"""Blueprint with routes backed by the Chinook SQLite database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, jsonify

CHINOOK_DB_PATH = Path(__file__).resolve().parent / "chinook.db"

db_bp = Blueprint("db", __name__, url_prefix="/db")


def _connect() -> sqlite3.Connection:
    """Open a read-only connection to chinook.db with rows accessible by column name."""
    connection = sqlite3.connect(f"{CHINOOK_DB_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


@db_bp.route("/artists/<int:artist_id>/albums", methods=["GET"])
def get_artist_albums(artist_id: int):
    """Return the albums of an artist from chinook.db, ordered by title (404 if missing)."""
    with closing(_connect()) as connection:
        artist = connection.execute(
            "SELECT ArtistId FROM Artist WHERE ArtistId = ?", (artist_id,)
        ).fetchone()
        if artist is None:
            return jsonify({"error": "Artist not found"}), 404

        rows = connection.execute(
            "SELECT AlbumId, Title, ArtistId FROM Album "
            "WHERE ArtistId = ? ORDER BY Title",
            (artist_id,),
        ).fetchall()

    return jsonify(
        [
            {
                "album_id": row["AlbumId"],
                "title": row["Title"],
                "artist_id": row["ArtistId"],
            }
            for row in rows
        ]
    )
