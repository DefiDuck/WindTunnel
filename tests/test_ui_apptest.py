"""Integration-ish tests using Streamlit's AppTest to render each page.

AppTest spins up the script in-process and lets us inspect what was rendered
without launching a real server. Catches AttributeError / TypeError that show
up only when a page actually renders.

If streamlit isn't installed (or AppTest isn't available), the whole module
is skipped.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    pytest.skip("AppTest not available", allow_module_level=True)

from witness.ui import APP_PATH


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10)


def _page_nav(at: AppTest):
    """Locate the page-nav radio (which has 'Inspect' as an option), tolerant
    of any number of other radios in the sidebar (mode toggle, etc.)."""
    for r in at.sidebar.radio:
        opts = list(getattr(r, "options", []) or [])
        if "Inspect" in opts:
            return r
    raise AssertionError(
        "page-nav radio not found — options seen: "
        + ", ".join(repr(list(getattr(r, "options", []))) for r in at.sidebar.radio)
    )


def _page_text(at: AppTest) -> str:
    """Concatenated text content emitted by the running page (markdown,
    captions, info, error, warning). Used so we can assert on page titles
    that are rendered via raw HTML topbars, not st.header()."""
    parts: list[str] = []
    for collection in (at.markdown, at.caption, at.info, at.warning, at.error):
        for el in collection:
            v = getattr(el, "value", None)
            if v:
                parts.append(str(v))
    for h in at.header:
        if h.value:
            parts.append(str(h.value))
    return "\n".join(parts)


def test_app_renders_load_page_without_errors() -> None:
    at = _new_app()
    at.run()
    # Default page is 'Load traces'
    assert not at.exception, f"unexpected exception: {at.exception}"
    assert "Load traces" in _page_text(at)


def test_app_switches_to_inspect_page_with_no_traces() -> None:
    at = _new_app()
    at.run()
    # Find the sidebar radio and select 'Inspect'
    radio = _page_nav(at)
    radio.set_value("Inspect").run()
    assert not at.exception
    assert "Inspect" in _page_text(at)


def test_app_switches_to_diff_page_with_no_traces() -> None:
    at = _new_app()
    at.run()
    radio = _page_nav(at)
    radio.set_value("Diff").run()
    assert not at.exception


def test_app_switches_to_perturb_page_with_no_traces() -> None:
    at = _new_app()
    at.run()
    radio = _page_nav(at)
    radio.set_value("Perturb & Replay").run()
    assert not at.exception


def test_app_switches_to_fingerprint_page_with_no_traces() -> None:
    at = _new_app()
    at.run()
    radio = _page_nav(at)
    radio.set_value("Fingerprint").run()
    assert not at.exception


def test_load_page_with_a_trace_in_session(tmp_path: Path) -> None:
    """Load a real trace file via the path-input loader and verify it shows up.

    The path input is hidden in 'simple' (default) UI mode; flip the session
    state to 'advanced' before the path loader is rendered."""
    from witness.core.schema import DecisionType, Trace
    from witness.core.store import save_trace

    t = Trace(agent_name="ax", final_output="ok", model="m")
    t.add_decision(type=DecisionType.MODEL_CALL, input={}, output={"text": "ok"})
    p = tmp_path / "fixture.json"
    save_trace(t, p)

    at = _new_app()
    at.session_state["ui_mode"] = "advanced"
    at.run()
    # The path-input lives only in advanced mode — find by key.
    path_input = next(
        ti for ti in at.text_input if getattr(ti, "key", None) == "path_input"
    )
    path_input.set_value(str(p)).run()
    button = next(b for b in at.button if getattr(b, "key", None) == "load_by_path")
    button.click().run()
    assert not at.exception
    # 1 trace should now be loaded — sidebar reports it.
    sidebar_text = " ".join(md.value for md in at.sidebar.markdown)
    assert "1 trace(s) loaded" in sidebar_text or "1 trace" in sidebar_text
