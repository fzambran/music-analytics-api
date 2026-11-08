"""Blueprint with routes backed by the Chinook SQLite database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, jsonify

CHINOOK_DB_PATH = Path(__file__).resolve().parent / "chinook.db"

db_bp = Blueprint("db", __name__, url_prefix="/db")


def get_db_connection(path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only connection with rows accessible by column name.

    Uses chinook.db unless another SQLite file `path` is given. Raises
    sqlite3.OperationalError if the file does not exist (it is never created).
    """
    db_path = Path(path).resolve() if path is not None else CHINOOK_DB_PATH
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


@db_bp.route("/artists/<int:artist_id>/albums", methods=["GET"])
def get_artist_albums(artist_id: int):
    """Return the albums of an artist from chinook.db, ordered by title (404 if missing)."""
    with closing(get_db_connection()) as connection:
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
