"""Payload data must never become markup or script (CWE-79).

The fuzz test appends a markup marker to EVERY scalar in a payload -- strings,
numbers, dates alike -- renders the page, and requires that the marker never
appears unescaped: not in the HTML body, and not inside the inline data
script. A new section that forgets to escape a field fails here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest

from aecb.render import js
from aecb.render.page import render_page
from conftest import context_of, fixture_payload, FIXTURES

MARK = "\"'><x-inj>"


def _poison(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                _poison(value)
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                node[key] = "%s%s" % (value, MARK)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                _poison(value)


def _split(html):
    start = html.index("<script>")
    return html[:start], html[start:]


@pytest.mark.parametrize("path", FIXTURES, ids=("synthetic", "archive"))
def test_no_payload_value_reaches_the_page_unescaped(path):
    payload = fixture_payload(path)
    _poison(payload)
    body, script = _split(render_page(context_of(payload)))
    assert "<x-inj>" not in body
    assert "<x-inj>" not in script


def test_data_blob_cannot_close_or_comment_out_the_script():
    data = {"a": "</script><!--<script>", "b": "  ", "c": "&"}
    text = js.json_for_script(data)
    for forbidden in ("<", ">", "&", " ", " "):
        assert forbidden not in text
    assert json.loads(text) == data


def test_page_carries_a_csp_that_admits_only_its_own_script(fixture_path):
    from aecb import context
    html = render_page(context.from_file(fixture_path))
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" '
                    r'content="([^"]+)">', html).group(1)
    assert "default-src 'none'" in csp
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest())
    assert "script-src 'sha256-%s'" % digest.decode("ascii") in csp
    # Exactly one inline script, and no inline event handlers the policy
    # would silently block.
    assert html.count("<script>") == 1
    assert not re.search(r"\son[a-z]+=", html)
