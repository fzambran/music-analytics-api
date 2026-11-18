"""Shared pytest configuration."""

import os

import pytest


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    """Append a one-line result summary to $PYTEST_RESULTS_LOG, if it is set."""
    log_path = os.environ.get("PYTEST_RESULTS_LOG")
    if not log_path:
        return

    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))

    if failed:
        title = "pytest FAILED"
        message = f"{failed} failed {passed} passed"
    else:
        title = "pytest PASSED"
        message = f"All {passed} tests passed!"

    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"{title}: {message}\n")
