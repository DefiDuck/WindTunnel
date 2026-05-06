"""Tests for the pure-Python exporters in witness.ui.export.

These don't import streamlit so they always run.
"""
from __future__ import annotations

import json

import pytest

from witness.core.schema import DecisionType, Trace
from witness.diff.behavioral import diff
from witness.diff.fingerprint import fingerprint
from witness.ui.export import (
    diff_to_markdown,
    fingerprint_to_markdown,
    preset_from_json,
    preset_to_json,
    trace_to_markdown,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _trace(name: str = "x", final: str = "ok") -> Trace:
    t = Trace(agent_name=name, model="m", final_output=final, wall_time_ms=42)
    t.add_decision(type=DecisionType.MODEL_CALL, input={"model": "m"}, output={"text": final})
    t.add_decision(type=DecisionType.TOOL_CALL, input={"name": "search"}, output={})
    t.add_decision(type=DecisionType.TOOL_RESULT, input={"name": "search"}, output={"hits": []})
    t.add_decision(type=DecisionType.FINAL_OUTPUT, input={}, output={"text": final})
    return t


# ---------------------------------------------------------------------------
# diff_to_markdown
# ---------------------------------------------------------------------------


def test_diff_to_markdown_basic_shape() -> None:
    a = _trace(final="alpha")
    b = _trace(final="beta")
    md = diff_to_markdown(diff(a, b))
    assert md.startswith("# Witness diff")
    assert "| metric | baseline | perturbed | delta |" in md
    assert "## final output" in md
    # Final-output changed -> baseline + perturbed sections present
    assert "**baseline:**" in md
    assert "**perturbed:**" in md


def test_diff_to_markdown_unchanged_says_unchanged() -> None:
    a = _trace(final="same")
    b = _trace(final="same")
    md = diff_to_markdown(diff(a, b))
    assert "_unchanged_" in md
    # Decision-changes section is omitted entirely if nothing changed
    assert "## decisions changed" not in md


def test_diff_to_markdown_includes_tool_counts() -> None:
    a = _trace()
    a.add_decision(type=DecisionType.TOOL_CALL, input={"name": "search"}, output={})
    b = _trace()  # one less search
    md = diff_to_markdown(diff(a, b))
    assert "## tool calls" in md
    assert "`search`" in md
    # Delta cell for the tool that changed should be bolded
    assert "**-1**" in md or "**+1**" in md


def test_diff_to_markdown_with_perturbation() -> None:
    from witness.core.schema import PerturbationRecord

    a = _trace()
    b = _trace(final="x")
    b.perturbation = PerturbationRecord(type="truncate", params={"fraction": 0.5})
    md = diff_to_markdown(diff(a, b))
    assert "**perturbation:**" in md
    assert "`truncate`" in md
    assert "`fraction=0.5`" in md


def test_diff_to_markdown_custom_title() -> None:
    a = _trace()
    b = _trace()
    md = diff_to_markdown(diff(a, b), title="Custom title")
    assert md.startswith("# Custom title")


def test_diff_to_markdown_decisions_changed_section() -> None:
    a = _trace()
    a.add_decision(type=DecisionType.TOOL_CALL, input={"name": "extra"}, output={})
    b = _trace()
    md = diff_to_markdown(diff(a, b))
    assert "## decisions changed" in md
    assert "REMOVED" in md or "ADDED" in md


# ---------------------------------------------------------------------------
# fingerprint_to_markdown
# ---------------------------------------------------------------------------


def test_fingerprint_to_markdown_shape() -> None:
    base = _trace()
    fp = fingerprint(base, [_trace(final="other"), _trace()])
    md = fingerprint_to_markdown(fp)
    assert md.startswith("# Witness fingerprint")
    assert "**baseline:**" in md
    assert "## stability by decision type" in md
    assert "## per-run summary" in md


def test_fingerprint_to_markdown_no_runs() -> None:
    base = _trace()
    fp = fingerprint(base, [])
    md = fingerprint_to_markdown(fp)
    assert md.startswith("# Witness fingerprint")
    # No runs -> no per-run table, no stability-by-type table
    assert "## per-run summary" not in md


def test_fingerprint_to_markdown_score_marker() -> None:
    base = _trace()
    # Stable: identical traces => stability == 1
    fp = fingerprint(base, [base, base])
    md = fingerprint_to_markdown(fp)
    assert "(stable)" in md


# ---------------------------------------------------------------------------
# trace_to_markdown
# ---------------------------------------------------------------------------


def test_trace_to_markdown_includes_basics() -> None:
    t = _trace(name="zelda")
    md = trace_to_markdown(t)
    assert "zelda" in md
    assert f"**run_id:** `{t.run_id}`" in md
    assert "**decisions:** 4" in md


def test_trace_to_markdown_with_perturbation() -> None:
    from witness.core.schema import PerturbationRecord

    t = _trace()
    t.perturbation = PerturbationRecord(type="truncate", params={"fraction": 0.25})
    t.parent_run_id = "run_parent"
    md = trace_to_markdown(t)
    assert "**perturbation:**" in md
    assert "`truncate`" in md
    assert "**parent run:**" in md


# ---------------------------------------------------------------------------
# Preset save/load round-trip
# ---------------------------------------------------------------------------


def test_preset_round_trip() -> None:
    specs = [
        ("truncate", {"fraction": 0.25}),
        ("truncate", {"fraction": 0.5}),
        ("prompt_injection", {}),
        ("model_swap", {"target": "claude-haiku-4-5"}),
    ]
    text = preset_to_json(specs)
    parsed = json.loads(text)
    assert parsed["witness_preset_version"] == 1
    assert len(parsed["perturbations"]) == 4
    restored = preset_from_json(text)
    assert restored == specs


def test_preset_from_json_validates() -> None:
    with pytest.raises(ValueError):
        preset_from_json('{"foo": "bar"}')  # missing 'perturbations'
    with pytest.raises(ValueError):
        preset_from_json('{"perturbations": [{"params": {}}]}')  # missing 'type'
    with pytest.raises(json.JSONDecodeError):
        preset_from_json("not json")


def test_preset_from_json_handles_empty_params() -> None:
    text = '{"witness_preset_version": 1, "perturbations": [{"type": "truncate"}]}'
    specs = preset_from_json(text)
    assert specs == [("truncate", {})]
