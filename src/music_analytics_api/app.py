"""Music Analytics API - Flask Application."""

import os

from flask import Flask
from flask_session import Session

from music_analytics_api.config import Config
from music_analytics_api.db_routes import db_bp

app = Flask(__name__)
app.config.from_object(Config)
Session(app)
app.register_blueprint(db_bp)

# Imported after `app` exists: routes.py does `from app import app` to register routes.
from music_analytics_api import routes  # noqa: F401

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
