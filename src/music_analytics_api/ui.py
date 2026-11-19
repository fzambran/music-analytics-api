"""Blueprint serving /ui, an HTML form to try the API from the browser."""

import re
from typing import Literal, TypedDict

from flask import Blueprint, current_app, render_template

from music_analytics_api.db_routes import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from music_analytics_api.routes import MAX_QUERY_LENGTH

ui_bp = Blueprint("ui", __name__, template_folder="templates")


class Preset(TypedDict):
    """A quick test case: the request it sends and the status code it gets."""

    label: str  # Starts with the expected status code
    rule: str  # Flask rule of a listed endpoint, e.g. "/artists/<int:artist_id>"
    params: dict[str, str]  # Path and query parameter values
    status: int


class EndpointInfo(TypedDict):
    """What the page's JavaScript needs to know about one API route."""

    rule: str  # Flask rule, e.g. "/db/artists/<int:artist_id>/albums"
    path: str  # Same path with {name} placeholders: "/db/artists/{artist_id}/albums"
    path_params: list[str]
    param_types: dict[str, str]  # Type of each path and query parameter: "int"...
    query_params: list[str]
    group: Literal["memory", "db"]
    paginated_alternative: str | None  # Rule of a paginated route with the same data


# Query-string parameters each endpoint reads, with their type ("int" or "string");
# path parameters and their types come from the URL rule.
QUERY_PARAMS: dict[str, dict[str, str]] = {
    "api.search_artists": {"q": "string"},
    "db.list_artists": {"limit": "int", "offset": "int"},
}

# Unpaginated routes whose data is only a sample of a paginated route. The page shows
# a note with a button to switch, because /artists (5 sample artists) and /db/artists
# (275 Chinook artists, by page) are easy to confuse.
PAGINATED_ALTERNATIVES: dict[str, str] = {"/artists": "/db/artists"}

# Quick test cases shown as buttons. The label starts with the status code they get;
# tests/test_ui.py sends each one and checks it.
PRESETS: list[Preset] = [
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
        "label": "200 · /db/artists (página 1)",
        "rule": "/db/artists",
        "params": {},
        "status": 200,
    },
    {
        "label": "200 · /db/artists (última página)",
        "rule": "/db/artists",
        "params": {"limit": "20", "offset": "260"},
        "status": 200,
    },
    {
        "label": "400 · limit=0",
        "rule": "/db/artists",
        "params": {"limit": "0"},
        "status": 400,
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

# A rule variable: <artist_id>, <int:artist_id> or <int(min=1):artist_id>.
# Group 1 is the converter name (absent means "string"), group 2 the parameter name.
_RULE_VARIABLE = re.compile(r"<(?:([^:<>(]+)(?:\([^<>]*\))?:)?([^<>]+)>")


def api_endpoints() -> list[EndpointInfo]:
    """Describe every GET route of the current app except /ui, in registration order.

    Each item has the Flask rule, a path template with {name} placeholders, its path
    and query parameters, the type of each one (the converter for path parameters,
    QUERY_PARAMS for query parameters), and its group: "db" for the /db Blueprint,
    else "memory".
    """
    endpoints: list[EndpointInfo] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.endpoint.startswith("ui."):
            continue
        if "GET" not in (rule.methods or set()):
            continue
        variables = _RULE_VARIABLE.findall(rule.rule)
        query = QUERY_PARAMS.get(rule.endpoint, {})
        endpoints.append(
            {
                "rule": rule.rule,
                "path": _RULE_VARIABLE.sub(r"{\2}", rule.rule),
                "path_params": [name for _, name in variables],
                "param_types": {
                    **{name: conv or "string" for conv, name in variables},
                    **query,
                },
                "query_params": list(query),
                "group": "db" if rule.endpoint.startswith("db.") else "memory",
                "paginated_alternative": PAGINATED_ALTERNATIVES.get(rule.rule),
            }
        )
    return endpoints


@ui_bp.route("/ui", methods=["GET"])
def explorer() -> str:
    """Render the API explorer: a request form and a response panel."""
    return render_template(
        "ui.html",
        endpoints=api_endpoints(),
        presets=PRESETS,
        limits={
            "max_query_length": MAX_QUERY_LENGTH,
            "default_page_size": DEFAULT_PAGE_SIZE,
            "max_page_size": MAX_PAGE_SIZE,
        },
    )
