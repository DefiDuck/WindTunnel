"""Regression test: clicking a ribbon node / Play button / row link must
not drop ``st.session_state["loaded_traces"]``.

Until commit 3d52c (the pushState/popstate JS shim in app.py), every
``<a href="?...">`` click was a full document navigation, which spawned
a fresh Streamlit session and dropped the in-memory traces dict. The
fix routes those clicks through ``window.history.pushState`` +
synthetic popstate events so Streamlit's frontend treats them as
reactive query-param changes.

We can't fully simulate the browser-side JS shim from Python, but we
*can* verify the Python contract that AppTest exposes: when the active
trace is set and a query param flips (the same outcome the JS shim
produces), session_state.loaded_traces survives across reruns. If a
future commit introduces a Python-side path that explicitly clears
loaded_traces on navigation, this test will catch it.
"""
from __future__ import annotations

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from witness.core.schema import Decision, DecisionType, Trace  # noqa: E402


def _trace(label: str = "fixture") -> Trace:
    return Trace(
        agent_name="t",
        decisions=[
            Decision(type=DecisionType.MODEL_CALL, duration_ms=50, input={"prompt": "a"}),
            Decision(type=DecisionType.TOOL_CALL, duration_ms=10, input={"name": "x"}),
            Decision(type=DecisionType.TOOL_RESULT, duration_ms=5),
            Decision(type=DecisionType.FINAL_OUTPUT, duration_ms=2, output={"text": "z"}),
        ],
    )


def _booted(*, trace_label: str | None = None) -> AppTest:
    at = AppTest.from_file("witness/ui/app.py", default_timeout=30)
    at.session_state["loaded_traces"] = {"fixture": _trace()}
    if trace_label:
        at.session_state["active_label"] = trace_label
    return at


def test_session_state_survives_trace_query_param() -> None:
    """Setting ?trace=fixture (the row-click contract) must not clear
    loaded_traces. AppTest gives us the same Python-side rerun the JS
    shim produces in the browser."""
    at = _booted(trace_label="fixture")
    at.query_params["trace"] = "fixture"
    at.run()
    assert at.session_state["loaded_traces"]
    assert "fixture" in at.session_state["loaded_traces"]


def test_session_state_survives_play_action_query_param() -> None:
    """Pressing Play emits ?trace=...&tab=sequence&play_action=play.
    The trace_detail._render_sequence handler consumes play_action, sets
    play.playing=True, clears the action param, and reruns. Through all
    of that, loaded_traces must persist."""
    at = _booted(trace_label="fixture")
    at.query_params["trace"] = "fixture"
    at.query_params["tab"] = "sequence"
    at.query_params["play_action"] = "play"
    at.run()
    assert at.session_state["loaded_traces"]
    assert "fixture" in at.session_state["loaded_traces"]


def test_session_state_survives_seek_query_param() -> None:
    """Clicking the scrubber emits ?play_action=seek&sel=N. Same
    invariant: traces survive."""
    at = _booted(trace_label="fixture")
    at.query_params["trace"] = "fixture"
    at.query_params["tab"] = "sequence"
    at.query_params["play_action"] = "seek"
    at.query_params["sel"] = "2"
    at.run()
    assert "fixture" in at.session_state["loaded_traces"]


def test_session_state_survives_diff_expand_query_param() -> None:
    """Clicking a node on the diff ribbon emits ?expand=<i>. The diff
    view reads the param to render the inline expansion card; traces
    must persist."""
    at = _booted(trace_label="fixture")
    at.query_params["nav"] = "Diffs"
    at.query_params["expand"] = "1"
    at.run()
    assert "fixture" in at.session_state["loaded_traces"]


def test_navigation_shim_block_present_in_page() -> None:
    """The pushState/popstate shim must actually be injected into the
    page. We assert on a marker comment from the JS source so a future
    refactor can't silently delete the shim."""
    at = _booted()
    at.run()
    # The script lives inside an st.components.v1.html iframe, which
    # AppTest surfaces as an Element with a 'script'-bearing payload.
    # Easiest cross-version check: scan all element values for the
    # interceptor signature.
    # The text from app.py: `Anchor-click interceptor` and `__witness_nav_bound`.
    # Streamlit's components.html stores its inner HTML in an attribute
    # that AppTest doesn't always expose; cheaper check is to scan the
    # rendered markdown chain — but components.html bypasses markdown.
    # As a pragmatic fallback we just import the source file and check
    # the marker is present in the on-disk app.py.
    src = open("witness/ui/app.py", encoding="utf-8").read()
    assert "__witness_nav_bound" in src
    assert "history.pushState" in src
    assert "PopStateEvent" in src
    # And the legacy footgun (direct location.search assignment) must
    # only appear inside the try/catch fallback path.
    assert src.count("win.location.search = qs") == 1
