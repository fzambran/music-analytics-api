"""Blueprint with routes backed by the Chinook SQLite database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, jsonify
from pydantic import BaseModel, Field

CHINOOK_DB_PATH = Path(__file__).resolve().parent / "chinook.db"

db_bp = Blueprint("db", __name__, url_prefix="/db")


class AlbumOut(BaseModel):
    """Album as returned by the API, validated from a Chinook `Album` row."""

    album_id: int = Field(validation_alias="AlbumId")
    title: str = Field(validation_alias="Title")
    artist_id: int = Field(validation_alias="ArtistId")


def get_db_connection() -> sqlite3.Connection:
    """Open a read-only connection to chinook.db with rows accessible by column name."""
    connection = sqlite3.connect(f"{CHINOOK_DB_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


@db_bp.route("/artists/<int:artist_id>/albums", methods=["GET"])
def get_artist_albums(artist_id: int):
    """Return the albums of an artist from chinook.db, ordered by title.

    Responds 404 if the artist does not exist and 200 with `[]` if it has no albums.
    """
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

    albums = [AlbumOut.model_validate(dict(row)) for row in rows]
    return jsonify([album.model_dump() for album in albums])
