"""The server runs Python 3.9. Development may happen on a newer interpreter,
so every shipped module is parsed with the 3.9 grammar here -- syntax such as
`match`, parenthesised context managers or `X | Y` annotations evaluated at
runtime would pass locally and fail in production."""

from __future__ import annotations

import ast
import os

import pytest

from conftest import ROOT

_SHIPPED = ["app_api.py"] + [
    os.path.relpath(os.path.join(folder, name), ROOT)
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "aecb"))
    for name in files if name.endswith(".py")]


@pytest.mark.parametrize("path", sorted(_SHIPPED))
def test_parses_as_python_39(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        ast.parse(fh.read(), filename=path, feature_version=(3, 9))
