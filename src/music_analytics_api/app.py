"""Music Analytics API - Flask application factory."""

import os
from pathlib import Path

from cachelib import FileSystemCache
from flask import Flask
from flask_session import Session

from music_analytics_api.config import Config
from music_analytics_api.db_routes import db_bp
from music_analytics_api.routes import api_bp

SESSION_FILE_LIMIT = 500  # Max session files before cachelib prunes old ones


def create_app() -> Flask:
    """Create a configured Flask app with the in-memory and /db routes registered."""
    app = Flask("music_analytics_api")  # Not __name__: it is "__main__" under python -m
    app.config.from_object(Config)
    # Built here, not in Config: FileSystemCache creates its folder when constructed.
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        cache_dir=str(Path(app.instance_path) / "flask_session"),
        threshold=SESSION_FILE_LIMIT,
    )
    Session(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(db_bp)
    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
