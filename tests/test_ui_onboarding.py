"""Smoke tests for the sample-data generator that powers the Load page's
'Try sample data' onboarding button.
"""
from __future__ import annotations

from witness.ui.onboarding import SAMPLE_DOC, generate_sample_traces


def test_generate_sample_traces_returns_two_traces() -> None:
    baseline, perturbed = generate_sample_traces()
    assert baseline is not None
    assert perturbed is not None
    # Baseline should have several decisions from the mock agent loop
    assert len(baseline.decisions) >= 5
    # Perturbed is derived from baseline
    assert perturbed.parent_run_id == baseline.run_id
    assert perturbed.perturbation is not None
    assert perturbed.perturbation.type == "truncate"


def test_generate_sample_traces_yields_a_diff() -> None:
    """The sample baseline + truncate(0.75) should produce a non-empty
    behavioral diff (the whole point of having a 'Try sample' button is
    that clicking through to Diff shows actual changes)."""
    from witness.diff.behavioral import diff

    baseline, perturbed = generate_sample_traces()
    d = diff(baseline, perturbed)
    # Either the final output changed or at least one decision was removed
    decisions_changed = any(p.kind != "same" for p in d.alignment.pairs)
    assert d.final_output_changed or decisions_changed


def test_sample_doc_is_long_enough() -> None:
    """The sample doc has to be > 200 chars so the mock agent triggers the
    read_document branch (which is what makes the diff interesting)."""
    assert len(SAMPLE_DOC) > 200
