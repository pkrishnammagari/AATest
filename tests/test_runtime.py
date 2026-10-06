"""AECB_ENV and AECB_AI_BRIEF: which environment, and what the AI panel does."""

from __future__ import annotations

import ast
import importlib.util

import pytest

from aecb import runtime


def test_unset_environment_takes_the_entry_points_default():
    assert runtime.environment(runtime.PROD) == runtime.PROD
    assert runtime.environment(runtime.DEV) == runtime.DEV


@pytest.mark.parametrize("value, expected", [
    ("dev", "dev"), ("uat", "uat"), ("prod", "prod"),
    ("UAT", "uat"), ("  Prod  ", "prod"),
])
def test_environment_reads_case_and_space_insensitively(monkeypatch, value,
                                                        expected):
    monkeypatch.setenv(runtime.ENV_ENVIRONMENT, value)
    assert runtime.environment(runtime.DEV) == expected


def test_blank_environment_counts_as_unset(monkeypatch):
    # systemd turns `AECB_ENV=` into an empty string.
    monkeypatch.setenv(runtime.ENV_ENVIRONMENT, "   ")
    assert runtime.environment(runtime.PROD) == runtime.PROD


@pytest.mark.parametrize("value", ["staging", "production", "uat1"])
def test_unknown_environment_raises_naming_the_setting(monkeypatch, value):
    monkeypatch.setenv(runtime.ENV_ENVIRONMENT, value)
    with pytest.raises(ValueError, match="AECB_ENV must be one of"):
        runtime.environment(runtime.PROD)


def test_unknown_default_is_a_programming_error():
    with pytest.raises(ValueError):
        runtime.environment("staging")
    with pytest.raises(ValueError):
        runtime.ai_mode("staging")


@pytest.mark.parametrize("env, expected", [
    (runtime.DEV, runtime.AI_LIVE),
    (runtime.UAT, runtime.AI_SOON),
    (runtime.PROD, runtime.AI_SOON),
])
def test_default_ai_mode_per_environment(env, expected):
    assert runtime.ai_mode(env) == expected


@pytest.mark.parametrize("value", ["live", "coming_soon", "off", " OFF "])
def test_ai_mode_setting_overrides_the_default(monkeypatch, value):
    monkeypatch.setenv(runtime.ENV_AI_BRIEF, value)
    assert runtime.ai_mode(runtime.PROD) == value.strip().lower()


@pytest.mark.parametrize("value", ["on", "true", "soon", "yes"])
def test_ai_mode_has_no_aliases(monkeypatch, value):
    monkeypatch.setenv(runtime.ENV_AI_BRIEF, value)
    with pytest.raises(ValueError, match="AECB_AI_BRIEF must be one of"):
        runtime.ai_mode(runtime.UAT)


def test_resolve_reports_clean_settings_without_a_problem(monkeypatch):
    monkeypatch.setenv(runtime.ENV_ENVIRONMENT, "uat")
    assert runtime.resolve(runtime.PROD) == (runtime.UAT, runtime.AI_SOON, "")
    monkeypatch.setenv(runtime.ENV_AI_BRIEF, "live")
    assert runtime.resolve(runtime.PROD) == (runtime.UAT, runtime.AI_LIVE, "")


@pytest.mark.parametrize("env_value, mode_value", [
    ("staging", "live"),     # bad environment, even with live requested
    ("dev", "enabled"),      # good environment, bad mode
])
def test_invalid_settings_fall_back_and_never_go_live(monkeypatch, caplog,
                                                      env_value, mode_value):
    monkeypatch.setenv(runtime.ENV_ENVIRONMENT, env_value)
    monkeypatch.setenv(runtime.ENV_AI_BRIEF, mode_value)
    env, mode, problem = runtime.resolve(runtime.DEV)
    assert (env, mode) == (runtime.PROD, runtime.AI_SOON)
    # User-safe: names the settings, never echoes the bad value.
    assert "AECB_ENV" in problem and "invalid" in problem
    assert env_value not in problem and mode_value not in problem


def test_runtime_imports_nothing_from_aecb():
    """app.py reads it before deciding whether to load the brief."""
    source = importlib.util.find_spec("aecb.runtime").origin
    with open(source, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and not (node.module or "").startswith("aecb")
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("aecb") for a in node.names)
