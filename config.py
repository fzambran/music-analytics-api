"""Flask configuration for the Music Analytics API."""

import os
import secrets

from cachelib import FileSystemCache


class Config:
    """Filesystem-based (cachelib) Flask-Session configuration."""

    # Random per-process fallback so the app never runs with a hardcoded secret.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_TYPE = "cachelib"
    SESSION_CACHELIB = FileSystemCache(cache_dir="flask_session", threshold=500)
