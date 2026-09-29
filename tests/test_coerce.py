"""aecb.coerce: one set of rules for reading untyped payload scalars."""

from __future__ import annotations

import pytest

from aecb.coerce import flag, integer, nonzero, number, truncated


@pytest.mark.parametrize("value, expected", [
    (12500, 12500.0), (12500.5, 12500.5), ("12500", 12500.0),
    ("12,500", 12500.0), (" 57 ", 57.0), ("-3", -3.0), (0, 0.0),
    (None, None), ("", None), ("  ", None), ("N/A", None),
    (True, None), (False, None),
    ("nan", None), ("inf", None), (float("inf"), None), (float("nan"), None),
])
def test_number(value, expected):
    assert number(value) == expected


@pytest.mark.parametrize("value, expected", [
    (732, 732), ("732", 732), ("732.0", 732), (732.0, 732),
    (732.9, None), ("732.9", None), (None, None), ("x", None),
])
def test_integer_accepts_whole_numbers_only(value, expected):
    assert integer(value) == expected


@pytest.mark.parametrize("value, expected", [
    (12, 12), ("12.9", 12), (12.9, 12), ("-1.5", -1), (None, None), ("x", None),
])
def test_truncated(value, expected):
    assert truncated(value) == expected


@pytest.mark.parametrize("value, expected", [
    (True, True), (False, False), (1, True), (0, False), (2, True),
    ("Y", True), ("yes", True), ("TRUE", True), ("1", True), ("t", True),
    ("N", False), ("no", False), ("false", False), ("0", False), ("f", False),
    (None, None), ("", None), ("maybe", None), ("Open", None),
])
def test_flag_is_three_state(value, expected):
    assert flag(value) is expected


@pytest.mark.parametrize("value, expected", [
    (0, False), ("0", False), ("0.00", False), (" 0 ", False), (None, False),
    ("", False), ("  ", False), (False, False),
    (1, True), ("12,500", True), ("-3", True), ("N/A", True), (True, True),
])
def test_nonzero(value, expected):
    assert nonzero(value) is expected
