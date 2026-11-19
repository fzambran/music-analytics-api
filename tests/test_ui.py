"""Tests for the /ui API explorer page."""

import json
import re
from urllib.parse import urlencode

import pytest
from flask import Flask

from music_analytics_api import ui
from music_analytics_api.app import create_app
from music_analytics_api.db_routes import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from music_analytics_api.routes import MAX_QUERY_LENGTH


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


def _page_data(html: str, element_id: str):
    """Return the JSON embedded in <script id=element_id type="application/json">."""
    match = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, element_id
    return json.loads(match.group(1))


def _fill(path_template: str, params: dict[str, str]) -> str:
    """Build the URL the page sends: path parameters in the path, the rest as query."""
    path = path_template
    query = {}
    for name, value in params.items():
        placeholder = "{" + name + "}"
        if placeholder in path:
            path = path.replace(placeholder, value)
        elif value:  # Like the page: empty query parameters are left out.
            query[name] = value
    return f"{path}?{urlencode(query)}" if query else path


def test_ui_page_answers_html(client):
    response = client.get("/ui")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Explorador de la API" in response.get_data(as_text=True)


def test_ui_lists_every_api_route_but_itself(app, client):
    html = client.get("/ui").get_data(as_text=True)

    listed = {endpoint["rule"] for endpoint in _page_data(html, "endpoints-data")}
    api_rules = {
        rule.rule
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
        and not rule.endpoint.startswith("ui.")
        and "GET" in rule.methods
    }
    assert listed == api_rules


def test_ui_endpoint_parameters_match_the_routes(client):
    html = client.get("/ui").get_data(as_text=True)
    endpoints = {e["rule"]: e for e in _page_data(html, "endpoints-data")}

    search = endpoints["/artists/search"]
    assert search["path"] == "/artists/search"
    assert search["path_params"] == []
    assert search["query_params"] == ["q"]

    db_albums = endpoints["/db/artists/<int:artist_id>/albums"]
    assert db_albums["path"] == "/db/artists/{artist_id}/albums"
    assert db_albums["path_params"] == ["artist_id"]
    assert db_albums["param_types"] == {"artist_id": "int"}
    assert search["param_types"] == {"q": "string"}

    db_artists = endpoints["/db/artists"]
    assert db_artists["path_params"] == []
    assert db_artists["query_params"] == ["limit", "offset"]
    assert db_artists["param_types"] == {"limit": "int", "offset": "int"}
    assert db_artists["group"] == "db"
    assert db_albums["query_params"] == []
    assert db_albums["group"] == "db"
    assert endpoints["/artists"]["group"] == "memory"


def test_ui_points_unpaginated_artists_to_the_paginated_route(client):
    """/artists returns only the 5 sample artists; the page suggests /db/artists."""
    html = client.get("/ui").get_data(as_text=True)
    endpoints = {e["rule"]: e for e in _page_data(html, "endpoints-data")}

    assert endpoints["/artists"]["paginated_alternative"] == "/db/artists"
    assert endpoints["/db/artists"]["paginated_alternative"] is None


def test_ui_paginated_alternatives_are_listed_paginated_routes(client):
    """Every suggested route exists in the page and takes limit and offset."""
    html = client.get("/ui").get_data(as_text=True)
    endpoints = {e["rule"]: e for e in _page_data(html, "endpoints-data")}

    alternatives = {
        e["paginated_alternative"]
        for e in endpoints.values()
        if e["paginated_alternative"]
    }
    assert alternatives
    for rule in alternatives:
        assert {"limit", "offset"} <= set(endpoints[rule]["query_params"])


def test_api_endpoints_reads_each_converter_from_the_rule():
    """A new route gets its parameter types without changes to ui.py or the page."""
    app = Flask("converters")

    def view(**kwargs):
        return ""

    app.add_url_rule("/albums/<int(min=1):album_id>/<float:score>/<name>", "a", view)
    app.add_url_rule("/upload", "b", view, methods=["POST"])

    with app.test_request_context():
        endpoints = ui.api_endpoints()

    assert endpoints == [
        {
            "rule": "/albums/<int(min=1):album_id>/<float:score>/<name>",
            "path": "/albums/{album_id}/{score}/{name}",
            "path_params": ["album_id", "score", "name"],
            "param_types": {"album_id": "int", "score": "float", "name": "string"},
            "query_params": [],
            "group": "memory",
            "paginated_alternative": None,
        }
    ]


def test_ui_presets_point_to_listed_endpoints(client):
    html = client.get("/ui").get_data(as_text=True)
    listed = {endpoint["rule"] for endpoint in _page_data(html, "endpoints-data")}

    presets = _page_data(html, "presets-data")
    assert presets
    assert {preset["rule"] for preset in presets} <= listed


@pytest.mark.parametrize("preset", ui.PRESETS, ids=lambda preset: preset["label"])
def test_ui_preset_answers_its_expected_status(app, client, preset):
    """Each quick test case really produces the status code its label promises."""
    with app.test_request_context():
        endpoints = {e["rule"]: e for e in ui.api_endpoints()}

    response = client.get(_fill(endpoints[preset["rule"]]["path"], preset["params"]))

    assert response.status_code == preset["status"]
    assert preset["label"].startswith(str(preset["status"]))


def test_ui_presets_cover_200_400_and_404():
    assert {preset["status"] for preset in ui.PRESETS} == {200, 400, 404}


def test_ui_uses_the_api_limits(client):
    """The form validates q and limit with the API's limits, not copies that can drift."""
    html = client.get("/ui").get_data(as_text=True)

    assert _page_data(html, "limits-data") == {
        "max_query_length": MAX_QUERY_LENGTH,
        "default_page_size": DEFAULT_PAGE_SIZE,
        "max_page_size": MAX_PAGE_SIZE,
    }
    too_long = [p for p in ui.PRESETS if p["status"] == 400 and p["params"].get("q")]
    assert [len(p["params"]["q"]) for p in too_long] == [MAX_QUERY_LENGTH + 1]


def test_ui_element_ids_are_unique(client):
    """The script looks elements up by id; a duplicate makes it read the wrong one."""
    html = client.get("/ui").get_data(as_text=True)

    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_ui_rejects_post(client):
    assert client.post("/ui").status_code == 405
