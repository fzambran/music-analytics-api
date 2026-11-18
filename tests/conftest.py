def pytest_terminal_summary(terminalreporter, exitstatus, config):
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))

    if failed:
        title = "pytest FAILED"
        message = f"{failed} failed {passed} passed"
    else:
        title = "pytest PASSED"
        message = f"All {passed} tests passed!"

    with open("/tmp/pytest_results.log", "a") as f:
        f.write(f"{title}: {message}\n")
