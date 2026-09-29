"""Configuration fails loudly: a broken policy file must stop the render,
never degrade it into a plausible-looking report."""

from __future__ import annotations

import json
import os
import shutil

import pytest

from aecb import context
from aecb.render.page import render_page
from conftest import ROOT, SYNTHETIC


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A writable copy of config/ that ReportContext reads instead."""
    target = tmp_path / "config"
    shutil.copytree(os.path.join(ROOT, "config"), str(target))
    monkeypatch.setattr(context, "CONFIG_DIR", str(target))
    return target


def _edit(config_dir, name, change):
    path = config_dir / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_committed_configuration_loads():
    context.from_file(SYNTHETIC)


def test_a_missing_config_file_raises(config_dir):
    (config_dir / "status_codes.json").unlink()
    with pytest.raises(FileNotFoundError):
        context.from_file(SYNTHETIC)


def test_a_status_code_without_rank_raises(config_dir):
    _edit(config_dir, "status_codes.json",
          lambda d: d["codes"]["W"].pop("rank"))
    with pytest.raises(ValueError, match="codes.W needs a whole-number rank"):
        context.from_file(SYNTHETIC)


@pytest.mark.parametrize("scale", [{"min": 900, "max": 300},
                                   {"min": "300", "max": 900}, None])
def test_an_unusable_score_scale_raises(config_dir, scale):
    _edit(config_dir, "bands.json", lambda d: d.update(scale=scale))
    with pytest.raises(ValueError, match="scale"):
        context.from_file(SYNTHETIC)


@pytest.mark.parametrize("severity", [{"severe_max": 100, "normal_min": 60},
                                      {"severe_max": "60", "normal_min": 100},
                                      None])
def test_severity_cut_offs_are_validated(config_dir, severity):
    _edit(config_dir, "status_codes.json", lambda d: d.update(severity=severity))
    with pytest.raises(ValueError, match="severity"):
        context.from_file(SYNTHETIC)


def test_severity_bands_follow_the_configured_cut_offs(config_dir):
    ctx = context.from_file(SYNTHETIC)
    assert [ctx.severity(r) for r in (None, 10, 60, 61, 99, 100)] == \
        ["unknown", "severe", "severe", "adverse", "adverse", "normal"]
    _edit(config_dir, "status_codes.json",
          lambda d: d.update(severity={"severe_max": 40, "normal_min": 90}))
    ctx = context.from_file(SYNTHETIC)
    assert [ctx.severity(r) for r in (40, 45, 90)] == ["severe", "adverse", "normal"]


def test_score_bands_out_of_order_raise(config_dir):
    _edit(config_dir, "bands.json",
          lambda d: d["fh_bands"].reverse())
    with pytest.raises(ValueError, match="ascending"):
        context.from_file(SYNTHETIC)


def test_an_unknown_band_tone_fails_loudly_not_green(config_dir):
    _edit(config_dir, "bands.json",
          lambda d: d["fh_bands"][0].update(tone="purple"))
    with pytest.raises(ValueError, match="tone 'purple'"):
        render_page(context.from_file(SYNTHETIC))


@pytest.mark.parametrize("key", ["validity_days", "closed_window_months",
                                 "applications_90d_red"])
def test_policy_numbers_are_required(config_dir, key):
    _edit(config_dir, "bands.json", lambda d: d.pop(key))
    with pytest.raises(ValueError, match=key):
        context.from_file(SYNTHETIC)


def test_the_optional_macro_context_may_be_absent(config_dir):
    (config_dir / "macro_context.json").unlink()
    assert context.load_optional_config("macro_context.json") is None
