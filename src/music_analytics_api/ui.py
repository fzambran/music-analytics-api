"""Blueprint serving /ui, an HTML form to try the API from the browser."""

import re
from typing import Literal, TypedDict

from flask import Blueprint, current_app, render_template

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
    param_types: dict[str, str]  # Converter of each path parameter: "int", "string"...
    query_params: list[str]
    group: Literal["memory", "db"]


# Query-string parameters each endpoint reads; path parameters come from the URL rule.
QUERY_PARAMS: dict[str, list[str]] = {"api.search_artists": ["q"]}

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
    parameters with their converter ("int", "string"...), its query parameters, and
    its group: "db" for the /db Blueprint, else "memory".
    """
    endpoints: list[EndpointInfo] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.endpoint.startswith("ui."):
            continue
        if "GET" not in (rule.methods or set()):
            continue
        variables = _RULE_VARIABLE.findall(rule.rule)
        endpoints.append(
            {
                "rule": rule.rule,
                "path": _RULE_VARIABLE.sub(r"{\2}", rule.rule),
                "path_params": [name for _, name in variables],
                "param_types": {name: conv or "string" for conv, name in variables},
                "query_params": QUERY_PARAMS.get(rule.endpoint, []),
                "group": "db" if rule.endpoint.startswith("db.") else "memory",
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
        limits={"max_query_length": MAX_QUERY_LENGTH},
    )
