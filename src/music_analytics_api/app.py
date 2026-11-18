"""Music Analytics API - Flask application factory."""

import os

from flask import Flask
from flask_session import Session

from music_analytics_api.config import Config
from music_analytics_api.db_routes import db_bp
from music_analytics_api.routes import api_bp


def create_app() -> Flask:
    """Create a configured Flask app with the in-memory and /db routes registered."""
    app = Flask(__name__)
    app.config.from_object(Config)
    Session(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(db_bp)
    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
