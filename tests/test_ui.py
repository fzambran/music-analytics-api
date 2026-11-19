"""Tests for the /ui API explorer page."""

import json
import re
from urllib.parse import urlencode

import pytest

from music_analytics_api import ui
from music_analytics_api.app import create_app


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
        else:
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
        if rule.endpoint != "static" and not rule.endpoint.startswith("ui.")
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
    assert db_albums["query_params"] == []
    assert db_albums["group"] == "db"
    assert endpoints["/artists"]["group"] == "memory"


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


def test_ui_presets_cover_every_status_the_api_answers():
    assert {preset["status"] for preset in ui.PRESETS} == {200, 400, 404}


def test_ui_element_ids_are_unique(client):
    """The script looks elements up by id; a duplicate makes it read the wrong one."""
    html = client.get("/ui").get_data(as_text=True)

    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_ui_rejects_post(client):
    assert client.post("/ui").status_code == 405
