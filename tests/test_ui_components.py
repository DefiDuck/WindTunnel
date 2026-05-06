"""Tests for the pure helpers inside witness.ui.components.

Streamlit-dependent helpers (empty_state, confirm_button, decision_expander)
are tested via streamlit's AppTest framework when available, but the basic
pure functions (filter_rows, _decision_summary) work without a UI runtime.
"""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from witness.core.schema import DecisionType, Trace
from witness.ui.components import filter_rows


def test_filter_rows_empty_query_returns_all() -> None:
    rows = [{"a": 1, "b": "foo"}, {"a": 2, "b": "bar"}]
    assert filter_rows(rows, "") == rows


def test_filter_rows_matches_any_value() -> None:
    rows = [
        {"name": "search", "out": "alpha"},
        {"name": "read", "out": "beta"},
        {"name": "search", "out": "gamma"},
    ]
    out = filter_rows(rows, "alpha")
    assert len(out) == 1
    assert out[0]["out"] == "alpha"


def test_filter_rows_case_insensitive() -> None:
    rows = [{"x": "Hello"}, {"x": "world"}]
    assert len(filter_rows(rows, "HELLO")) == 1
    assert len(filter_rows(rows, "WORLD")) == 1


def test_filter_rows_handles_non_string_values() -> None:
    rows = [{"n": 42, "s": "answer"}, {"n": 100, "s": "other"}]
    assert len(filter_rows(rows, "42")) == 1
    assert len(filter_rows(rows, "answer")) == 1


def test_filter_rows_no_match_returns_empty() -> None:
    rows = [{"x": "foo"}, {"x": "bar"}]
    assert filter_rows(rows, "qux") == []


def test_decision_summary_helpers() -> None:
    """The internal _decision_summary is used by decision_list and decision_expander.
    Smoke-test via the components module path."""
    from witness.ui.components import _decision_summary

    t = Trace(agent_name="x")
    d_tool = t.add_decision(
        type=DecisionType.TOOL_CALL, input={"name": "search"}, output={}
    )
    d_model = t.add_decision(
        type=DecisionType.MODEL_CALL, input={"model": "claude"}, output={}
    )
    d_final = t.add_decision(type=DecisionType.FINAL_OUTPUT, input={}, output={})

    assert "tool_call" in _decision_summary(d_tool)
    assert "search" in _decision_summary(d_tool)
    assert "model_call" in _decision_summary(d_model)
    assert "claude" in _decision_summary(d_model)
    assert _decision_summary(d_final) == "final_output"
