"""Blueprint serving /ui, an HTML form to try the API from the browser."""

import re

from flask import Blueprint, current_app, render_template

from music_analytics_api.routes import MAX_QUERY_LENGTH

ui_bp = Blueprint("ui", __name__, template_folder="templates")

# Query-string parameters each endpoint reads; path parameters come from the URL rule.
QUERY_PARAMS: dict[str, list[str]] = {"api.search_artists": ["q"]}

# Quick test cases shown as buttons. The label starts with the status code they get;
# tests/test_ui.py sends each one and checks it.
PRESETS: list[dict] = [
    {
        "label": "200 · Todos los artistas",
        "rule": "/artists",
        "params": {},
        "status": 200,
    },
    {
        "label": "200 · Buscar «ac»",
        "rule": "/artists/search",
        "params": {"q": "ac"},
        "status": 200,
    },
    {
        "label": "200 · /stats/albums",
        "rule": "/stats/albums",
        "params": {},
        "status": 200,
    },
    {
        "label": "200 · /db/artists/1/albums",
        "rule": "/db/artists/<int:artist_id>/albums",
        "params": {"artist_id": "1"},
        "status": 200,
    },
    {
        "label": "400 · q vacío",
        "rule": "/artists/search",
        "params": {"q": ""},
        "status": 400,
    },
    {
        "label": f"400 · q de {MAX_QUERY_LENGTH + 1} caracteres",
        "rule": "/artists/search",
        "params": {"q": "a" * (MAX_QUERY_LENGTH + 1)},
        "status": 400,
    },
    {
        "label": "404 · /artists/999",
        "rule": "/artists/<int:artist_id>",
        "params": {"artist_id": "999"},
        "status": 404,
    },
    {
        "label": "404 · /db/artists/999999/albums",
        "rule": "/db/artists/<int:artist_id>/albums",
        "params": {"artist_id": "999999"},
        "status": 404,
    },
    {
        "label": "404 HTML · /artists/abc",
        "rule": "/artists/<int:artist_id>",
        "params": {"artist_id": "abc"},
        "status": 404,
    },
]

_CONVERTER = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")  # <int:artist_id> -> artist_id


def api_endpoints() -> list[dict]:
    """Describe every GET route of the current app except /ui, in registration order.

    Each item has the Flask rule, a path template with {name} placeholders, its path
    and query parameters, and its group: "db" for the /db Blueprint, else "memory".
    """
    endpoints = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.endpoint.startswith("ui."):
            continue
        if "GET" not in (rule.methods or set()):
            continue
        endpoints.append(
            {
                "rule": rule.rule,
                "path": _CONVERTER.sub(r"{\1}", rule.rule),
                "path_params": _CONVERTER.findall(rule.rule),
                "query_params": QUERY_PARAMS.get(rule.endpoint, []),
                "group": "db" if rule.endpoint.startswith("db.") else "memory",
            }
        )
    return endpoints


@ui_bp.route("/ui", methods=["GET"])
def explorer():
    """Render the API explorer: a request form and a response panel."""
    return render_template(
        "ui.html",
        endpoints=api_endpoints(),
        presets=PRESETS,
        limits={"max_query_length": MAX_QUERY_LENGTH},
    )
