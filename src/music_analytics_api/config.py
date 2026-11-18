"""Flask configuration for the Music Analytics API."""

import os
import secrets


class Config:
    """Flask-Session configuration; create_app() adds the cachelib session store."""

    # Random per-process fallback so the app never runs with a hardcoded secret.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_TYPE = "cachelib"
