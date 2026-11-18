"""Tests for the Flask application factory and the app's entry point."""

import runpy
import sys

import pytest
from flask import Flask

from music_analytics_api.app import create_app

IN_MEMORY_RULES = {
    "/artists",
    "/artists/search",
    "/artists/<int:artist_id>",
    "/artists/<int:artist_id>/albums",
    "/albums",
    "/stats/albums",
    "/stats/average-tracks",
}
DB_RULES = {"/db/artists/<int:artist_id>/albums"}


def _rules(app: Flask) -> set[str]:
    """Return the URL rules registered on app, without Flask's static route."""
    return {rule.rule for rule in app.url_map.iter_rules() if rule.endpoint != "static"}


def test_running_module_as_main_serves_every_route(monkeypatch):
    """`python -m music_analytics_api.app` must serve the in-memory routes too."""
    served = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: served.append(self))

    # Like `python -m`: the module has not been imported before it runs.
    monkeypatch.delitem(sys.modules, "music_analytics_api.app", raising=False)
    runpy.run_module("music_analytics_api.app", run_name="__main__")

    assert len(served) == 1
    assert _rules(served[0]) == IN_MEMORY_RULES | DB_RULES


@pytest.mark.parametrize("debug_env, expected", [("1", True), (None, False)])
def test_running_module_as_main_reads_flask_debug(monkeypatch, debug_env, expected):
    """FLASK_DEBUG=1 turns on debug mode; anything else leaves it off."""
    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: calls.append(kwargs))
    if debug_env is None:
        monkeypatch.delenv("FLASK_DEBUG", raising=False)
    else:
        monkeypatch.setenv("FLASK_DEBUG", debug_env)

    # Like `python -m`: the module has not been imported before it runs.
    monkeypatch.delitem(sys.modules, "music_analytics_api.app", raising=False)
    runpy.run_module("music_analytics_api.app", run_name="__main__")

    assert calls == [{"debug": expected}]


def test_create_app_returns_independent_apps_with_every_route():
    """Each call builds a new app; configuring one does not touch the other."""
    first, second = create_app(), create_app()
    first.config["TESTING"] = True

    assert first is not second
    assert second.config["TESTING"] is False
    assert _rules(first) == _rules(second) == IN_MEMORY_RULES | DB_RULES
