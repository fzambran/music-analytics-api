"""Music Analytics API - Flask application factory."""

import os
from pathlib import Path

from cachelib import FileSystemCache
from flask import Flask
from flask_session import Session
from werkzeug.routing import IntegerConverter

from music_analytics_api.config import Config
from music_analytics_api.db_routes import db_bp
from music_analytics_api.routes import api_bp
from music_analytics_api.ui import ui_bp
from music_analytics_api.validation import SQLITE_MAX_INTEGER, parse_unsigned_int

SESSION_FILE_LIMIT = 500  # Max session files before cachelib prunes old ones


def _route_int(value: str) -> int:
    """Convert a route segment with the project's integer rule (validation.py).

    ASCII digits with an optional "-" (only matched with signed=True); a value
    beyond SQLITE_MAX_INTEGER is capped just above it instead of calling int()
    on thousands of digits.
    """
    magnitude = value.removeprefix("-")
    number = parse_unsigned_int(magnitude, SQLITE_MAX_INTEGER)
    if number is None:
        raise ValueError(value)  # Werkzeug turns this into "route does not match"
    return -number if magnitude != value else number


class AsciiIntConverter(IntegerConverter):
    """Flask's <int:...>, but with the same rule as limit, offset and the CLI.

    Werkzeug matches any Unicode digit (so /artists/٣ was artist 3) and calls int(),
    which rejects more than 4300 digits; Werkzeug then reports "no route", and the
    client got Flask's HTML 404 instead of the API's JSON one. fixed_digits, min and
    signed keep working. So does max, up to SQLITE_MAX_INTEGER: any larger value
    reaches the view as SQLITE_MAX_INTEGER + 1, so a max above that is not exact.
    """

    regex = r"[0-9]+"
    num_convert = staticmethod(_route_int)

    def to_url(self, value: object) -> str:
        """Build the segment for url_for() with Werkzeug's int(), as before.

        The ASCII rule is for reading URLs; url_for() gets Python values such as
        True or 3.0, which int() turns into "1" and "3".
        """
        value_str = str(int(value))  # type: ignore[call-overload]
        return value_str.zfill(self.fixed_digits) if self.fixed_digits else value_str


def create_app() -> Flask:
    """Create a configured Flask app with the in-memory, /db and /ui routes registered."""
    app = Flask("music_analytics_api")  # Not __name__: it is "__main__" under python -m
    app.config.from_object(Config)
    # Built here, not in Config: FileSystemCache creates its folder when constructed.
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        cache_dir=str(Path(app.instance_path) / "flask_session"),
        threshold=SESSION_FILE_LIMIT,
    )
    Session(app)
    # Before the Blueprints: their rules pick the converter when they are registered.
    app.url_map.converters["int"] = AsciiIntConverter
    app.register_blueprint(api_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(ui_bp)
    return app


def run_server() -> None:
    """Run the development server; FLASK_DEBUG=1 turns on debug mode."""
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")


if __name__ == "__main__":
    run_server()
