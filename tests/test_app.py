"""Tests for the Flask application factory and the app's entry point."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

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
DB_RULES = {"/db/artists", "/db/artists/<int:artist_id>/albums"}
UI_RULES = {"/ui"}
ALL_RULES = IN_MEMORY_RULES | DB_RULES | UI_RULES


def _rules(app: Flask) -> set[str]:
    """Return the URL rules registered on app, without Flask's static route."""
    return {rule.rule for rule in app.url_map.iter_rules() if rule.endpoint != "static"}


def test_running_module_as_main_serves_every_route(monkeypatch):
    """`python -m music_analytics_api.app` must serve the in-memory and /ui routes too."""
    served = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: served.append(self))

    # Like `python -m`: the module has not been imported before it runs.
    monkeypatch.delitem(sys.modules, "music_analytics_api.app", raising=False)
    runpy.run_module("music_analytics_api.app", run_name="__main__")

    assert len(served) == 1
    assert _rules(served[0]) == ALL_RULES


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
    assert _rules(first) == _rules(second) == ALL_RULES


def _run_python(code: str, cwd, env_overrides: dict[str, str] | None = None) -> str:
    """Run `python -c code` in a fresh interpreter and return its stdout."""
    env = {**os.environ, **(env_overrides or {})}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_importing_config_creates_nothing_in_the_working_directory(tmp_path):
    """Importing the package must not leave a flask_session/ wherever it runs."""
    _run_python("import music_analytics_api.app", cwd=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_create_app_keeps_sessions_in_its_instance_folder():
    """Sessions go to <instance_path>/flask_session, one cache per app."""
    first, second = create_app(), create_app()
    session_dir = Path(first.instance_path) / "flask_session"

    assert first.config["SESSION_CACHELIB"]._path == str(session_dir)
    assert first.config["SESSION_CACHELIB"] is not second.config["SESSION_CACHELIB"]


def test_chinook_db_path_reads_the_environment_variable(tmp_path):
    """CHINOOK_DB_PATH in the environment replaces the default database path."""
    custom = tmp_path / "other.db"
    code = "from music_analytics_api.db_routes import CHINOOK_DB_PATH; print(CHINOOK_DB_PATH)"

    output = _run_python(
        code, cwd=tmp_path, env_overrides={"CHINOOK_DB_PATH": str(custom)}
    )

    assert output.strip() == str(custom)


def test_chinook_db_path_defaults_to_the_repository_data_folder(tmp_path):
    """Without the variable, the database is data/chinook.db in the repository."""
    env = {key: value for key, value in os.environ.items() if key != "CHINOOK_DB_PATH"}
    code = "from music_analytics_api.db_routes import CHINOOK_DB_PATH; print(CHINOOK_DB_PATH)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(
        Path(__file__).resolve().parents[1] / "data" / "chinook.db"
    )


def test_running_module_as_main_uses_the_package_instance_folder(monkeypatch):
    """Run as __main__, the app keeps the same instance folder, not one in the CWD."""
    served = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: served.append(self))

    monkeypatch.delitem(sys.modules, "music_analytics_api.app", raising=False)
    runpy.run_module("music_analytics_api.app", run_name="__main__")

    assert served[0].instance_path == create_app().instance_path


@pytest.mark.parametrize("debug_env, expected", [("1", True), (None, False)])
def test_console_script_main_runs_the_full_api(monkeypatch, debug_env, expected):
    """`music-analytics-api` serves every route and reads FLASK_DEBUG."""
    from music_analytics_api import main

    served = []
    monkeypatch.setattr(
        Flask, "run", lambda self, **kwargs: served.append((_rules(self), kwargs))
    )
    if debug_env is None:
        monkeypatch.delenv("FLASK_DEBUG", raising=False)
    else:
        monkeypatch.setenv("FLASK_DEBUG", debug_env)

    main()

    assert served == [(ALL_RULES, {"debug": expected})]


@pytest.mark.parametrize("relative", ["other.db", "nested/../other.db"])
def test_chinook_db_path_resolves_a_relative_variable(tmp_path, relative):
    """A relative CHINOOK_DB_PATH is resolved against the working directory."""
    code = "from music_analytics_api.db_routes import CHINOOK_DB_PATH; print(CHINOOK_DB_PATH)"

    output = _run_python(
        code, cwd=tmp_path, env_overrides={"CHINOOK_DB_PATH": relative}
    )

    assert output.strip() == str(tmp_path.resolve() / "other.db")


def test_db_route_works_with_a_relative_chinook_db_path(tmp_path):
    """GET /db/artists/1/albums answers 200, not 500, with a relative path."""
    db_path = Path(__file__).resolve().parents[1] / "data" / "chinook.db"
    relative = os.path.relpath(db_path, tmp_path)
    code = (
        "from music_analytics_api.app import create_app\n"
        "response = create_app().test_client().get('/db/artists/1/albums')\n"
        "print(response.status_code, len(response.get_json()))"
    )

    output = _run_python(
        code, cwd=tmp_path, env_overrides={"CHINOOK_DB_PATH": relative}
    )

    assert output.split() == ["200", "2"]


def test_chinook_db_path_expands_the_home_directory(tmp_path):
    """`~` in CHINOOK_DB_PATH expands to the user's home directory."""
    code = "from music_analytics_api.db_routes import CHINOOK_DB_PATH; print(CHINOOK_DB_PATH)"
    env = {"CHINOOK_DB_PATH": "~/other.db", "HOME": str(tmp_path)}

    output = _run_python(code, cwd=tmp_path, env_overrides=env)

    assert output.strip() == str(tmp_path.resolve() / "other.db")
