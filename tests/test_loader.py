"""aecb.loader: malformed documents fail cleanly; nothing is dropped silently."""

from __future__ import annotations

import json

import pytest

from aecb import context, loader
from aecb.render.page import render_page


def test_every_known_array_exists():
    data = loader.loads(b'{"summary": []}')
    for name in loader.ARRAYS:
        assert data[name] == []
    assert data["_unknownArrays"] == [] and data["_droppedRows"] == {}


def test_strings_are_trimmed_and_blank_becomes_none():
    data = loader.loads(json.dumps(
        {"applications": [{"Phase": "Requested ", "X": "  "}]}))
    assert data["applications"][0] == {"Phase": "Requested", "X": None}


def test_categories_are_canonicalised():
    data = loader.loads(json.dumps(
        {"contractsSummary": [{"ContractCategory": "Credit Cards"}]}))
    assert data["contractsSummary"][0]["ContractCategory"] == "C"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_refused(literal):
    with pytest.raises(ValueError, match="not a number"):
        loader.loads('{"summary": [{"Overdueamount": %s}]}' % literal)


def test_a_non_object_document_is_refused():
    with pytest.raises(ValueError, match="not a JSON object"):
        loader.loads("[]")


def test_non_object_rows_are_dropped_and_counted(archive_payload):
    archive_payload["contracts"].insert(0, None)
    archive_payload["addresses"].append(5)
    ctx = context.from_bytes(json.dumps(archive_payload).encode("utf-8"))
    assert ctx.dropped_rows == {"contracts": 1, "addresses": 1}
    render_page(ctx)  # and the report still renders


def test_unknown_top_level_arrays_are_surfaced():
    data = loader.loads('{"somethingNew": [], "summary": []}')
    assert data["_unknownArrays"] == ["somethingNew"]


def test_a_byte_order_mark_is_tolerated():
    assert loader.loads("﻿{}".encode("utf-8"))["summary"] == []


def test_require_aecb_payload():
    with pytest.raises(ValueError, match="does not look like an AECB payload"):
        context.require_aecb_payload(context.from_bytes(b'{"x": 1}'))
