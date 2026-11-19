"""Blueprint with routes backed by the Chinook SQLite database."""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, Field, ValidationError

# src/music_analytics_api/db_routes.py -> <repo>/data/chinook.db (development checkout).
# The wheel does not ship the database: set CHINOOK_DB_PATH when the package is installed.
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chinook.db"
# Absolute, like --db: sqlite3 needs a file URI, and as_uri() rejects relative paths.
CHINOOK_DB_PATH = (
    Path(os.environ.get("CHINOOK_DB_PATH") or _DEFAULT_DB_PATH).expanduser().resolve()
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_OFFSET = 2**63 - 1  # SQLite's largest integer: a bigger value cannot be bound
# Plain ASCII digits only: int() would also accept " 5", "+5", "1_000" or "٥".
_UNSIGNED_INT = re.compile(r"[0-9]+")

db_bp = Blueprint("db", __name__, url_prefix="/db")


# Handled errors are not logged by Flask, so each handler logs the traceback itself;
# the client only gets a generic message, never paths, SQL or validation details.
@db_bp.errorhandler(sqlite3.Error)
def _database_error(error: sqlite3.Error):
    """Answer a failure to open or query chinook.db with a JSON 500."""
    current_app.logger.exception("Chinook query failed")
    return jsonify({"error": "Database unavailable"}), 500


@db_bp.errorhandler(ValidationError)
def _invalid_row_error(error: ValidationError):
    """Answer a Chinook row that fails AlbumOut or ArtistOut validation with a JSON 500."""
    current_app.logger.exception("Invalid Chinook row")
    return jsonify({"error": "Invalid data in database"}), 500


class AlbumOut(BaseModel):
    """Album as returned by the API, validated from a Chinook `Album` row."""

    album_id: int = Field(validation_alias="AlbumId")
    title: str = Field(validation_alias="Title")
    artist_id: int = Field(validation_alias="ArtistId")


class ArtistOut(BaseModel):
    """Artist as returned by the API, validated from a Chinook `Artist` row."""

    artist_id: int = Field(validation_alias="ArtistId")
    name: str | None = Field(validation_alias="Name")  # Artist.Name is nullable


def get_db_connection(path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only connection with rows accessible by column name.

    Uses chinook.db unless another SQLite file `path` is given. Raises
    sqlite3.OperationalError if the file does not exist (it is never created).
    """
    db_path = Path(path).expanduser().resolve() if path is not None else CHINOOK_DB_PATH
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _parse_unsigned_int(raw: str, maximum: int) -> int | None:
    """Return raw as an int if it is ASCII digits worth at most maximum, else None.

    Leading zeros are dropped and the length checked before int(): Python refuses to
    convert strings of more than 4300 digits, and its message must not reach clients.
    """
    if not _UNSIGNED_INT.fullmatch(raw):
        return None
    digits = raw.lstrip("0") or "0"
    if len(digits) > len(str(maximum)):
        return None
    value = int(digits)
    return value if value <= maximum else None


def _paging_param(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer query parameter from minimum to maximum, or raise ValueError.

    A missing parameter gives `default`; an empty, non-numeric or out-of-range one
    raises ValueError with the message for the client.
    """
    raw = request.args.get(name)
    if raw is None:
        return default
    value = _parse_unsigned_int(raw, maximum)
    if value is None or value < minimum:
        raise ValueError(
            f"Query parameter '{name}' must be an integer from {minimum} to {maximum}"
        )
    return value


@db_bp.route("/artists", methods=["GET"])
def list_artists():
    """Return one page of chinook.db artists, ordered by ArtistId.

    Query parameters: `limit` (1 to MAX_PAGE_SIZE, default DEFAULT_PAGE_SIZE) and
    `offset` (0 to MAX_OFFSET, default 0). Responds `{"items", "total", "limit", "offset"}`;
    an offset past the last artist gives an empty `items`. Invalid values answer 400.
    """
    try:
        limit = _paging_param("limit", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        offset = _paging_param("offset", 0, 0, MAX_OFFSET)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    with closing(get_db_connection()) as connection:
        total = connection.execute("SELECT COUNT(*) FROM Artist").fetchone()[0]
        rows = connection.execute(
            "SELECT ArtistId, Name FROM Artist ORDER BY ArtistId LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    artists = [ArtistOut.model_validate(dict(row)) for row in rows]
    return jsonify(
        {
            "items": [artist.model_dump() for artist in artists],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


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
