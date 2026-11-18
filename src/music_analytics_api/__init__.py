"""Music Analytics API: Flask API and per-artist report over the Chinook database."""


def main() -> None:
    """Entry point of the `music-analytics-api` console script: run the API."""
    # Imported here so that importing the package does not load Flask and the app.
    from music_analytics_api.app import run_server

    run_server()
