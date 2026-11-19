"""Tests for the integer parsing shared by the /db routes and the reporter CLI."""

import pytest

from music_analytics_api.validation import SQLITE_MAX_INTEGER, parse_unsigned_int


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5", 5),
        ("0", 0),
        ("005", 5),
        ("0" * 5000, 0),
        ("0" * 5000 + "40", 40),
        (str(SQLITE_MAX_INTEGER), SQLITE_MAX_INTEGER),
    ],
)
def test_parses_ascii_digits(raw, expected):
    assert parse_unsigned_int(raw, SQLITE_MAX_INTEGER) == expected


@pytest.mark.parametrize(
    "raw",
    ["", " 5", "5 ", "+5", "-5", "-0", "1_000", "5.0", "1e3", "٥", "５", "abc"],
)
def test_rejects_anything_but_ascii_digits(raw):
    """int() would accept several of these (" 5", "+5", "1_000", "٥"); this does not."""
    assert parse_unsigned_int(raw, SQLITE_MAX_INTEGER) is None


@pytest.mark.parametrize(
    "raw",
    [str(SQLITE_MAX_INTEGER + 1), "99999999999999999999999", "9" * 5000],
)
def test_values_above_maximum_come_back_as_maximum_plus_one(raw):
    """Too large, however long: no int() of thousands of digits, no exception."""
    assert parse_unsigned_int(raw, SQLITE_MAX_INTEGER) == SQLITE_MAX_INTEGER + 1


def test_small_maximum():
    assert parse_unsigned_int("100", 100) == 100
    assert parse_unsigned_int("101", 100) == 101
    assert parse_unsigned_int("1000", 100) == 101
