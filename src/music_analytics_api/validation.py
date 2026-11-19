"""Integer parsing shared by the API (routes and query parameters) and the reporter CLI.

It imports neither Flask nor Pydantic, so it has no web dependencies of its own. The
reporter still loads both today through db_routes (get_db_connection); see "Riesgos"
in docs/PLAN.md. Each caller builds its own message: the API answers in English
JSON, the CLI in Spanish through argparse.
"""

import re

# SQLite's largest integer: a bigger Python int cannot be bound to a query
# (sqlite3 raises OverflowError, not sqlite3.Error), and no row can hold it.
SQLITE_MAX_INTEGER = 2**63 - 1

# Plain ASCII digits only: int() would also accept " 5", "+5", "1_000" or "٥".
_UNSIGNED_INT = re.compile(r"[0-9]+")


def parse_unsigned_int(raw: str, maximum: int) -> int | None:
    """Parse raw as a non-negative integer made only of ASCII digits.

    Returns None if raw is anything else (empty, signed, spaced, "1_000", "٥").
    Leading zeros are ignored. A value above maximum comes back as maximum + 1, so
    the caller reports it as too large: the length is checked before int(), which
    refuses strings of more than 4300 digits with a message clients must not see.
    """
    if not _UNSIGNED_INT.fullmatch(raw):
        return None
    digits = raw.lstrip("0") or "0"
    if len(digits) > len(str(maximum)):
        return maximum + 1
    return min(int(digits), maximum + 1)
