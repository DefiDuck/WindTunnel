"""Tests for ``witness.ui.components.flow``.

The flow ribbon is pure SVG rendering — no Streamlit, no DOM. We can therefore
unit-test it by inspecting the returned string. The asserts below cover the
properties the brief calls out as load-bearing:

- node count matches the input length
- node width grows monotonically with duration_ms
- the active (selected) node carries ``flow-node-active``
- diff annotations (``+``, ``~``, ghost stubs) are emitted on the right slots
"""
from __future__ import annotations

import math
import re
from itertools import pairwise

from witness.core.schema import Decision, DecisionType
from witness.diff.behavioral import DecisionChange
from witness.ui.components.flow import (
    NODE_HEIGHT,
    RIBBON_HEIGHT,
    TYPE_COLOR,
    render_diff_ribbons,
    render_flow_ribbon,
    width_for_duration,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(
    type_: DecisionType = DecisionType.MODEL_CALL,
    *,
    duration_ms: int | None = None,
    name: str | None = None,
) -> Decision:
    """Build a Decision with deterministic id (the random step_id is fine,
    we never inspect it)."""
    inp: dict[str, object] = {}
    if name is not None:
        inp["name"] = name
    return Decision(type=type_, input=inp, duration_ms=duration_ms)


def _count_nodes(svg: str) -> int:
    # Each node is wrapped in <a class="flow-node-link">. Counting opening
    # anchor tags is the cleanest proxy.
    return svg.count('class="flow-node-link"')


def _node_widths(svg: str) -> list[float]:
    """Pull node rect widths in document order.

    Anchor on the unique node-rect signature ``rx="6" fill="var(--bg-raised)"``
    so we skip both the halo rect (rx="9") and the cosmetic stroke-width
    attributes that would otherwise match a naive ``width=`` regex.
    """
    return [
        float(m)
        for m in re.findall(
            r'<rect [^>]*?width="([\d.]+)"[^>]*?rx="6" fill="var\(--bg-raised\)"',
            svg,
        )
    ]


# ---------------------------------------------------------------------------
# width_for_duration — the math
# ---------------------------------------------------------------------------


def test_width_for_none_returns_uniform_default() -> None:
    assert width_for_duration(None) == 80.0


def test_width_clamps_low() -> None:
    # log(1)*16 = 0, must clamp up to 48
    assert width_for_duration(1) == 48.0
    assert width_for_duration(0) == 48.0  # 0 -> max(1, 0)=1 -> log(1)=0 -> 48
    assert width_for_duration(-50) == 48.0  # negative -> clamped to 1ms first


def test_width_clamps_high() -> None:
    # log(1e9)*16 ≈ 332 → clamped to 200
    assert width_for_duration(10_000_000) == 200.0
    assert width_for_duration(1_000_000_000) == 200.0


def test_width_grows_with_duration_in_band() -> None:
    # Inside the un-clamped band, the curve is strictly increasing.
    samples = [50, 200, 800, 3_000, 12_000]
    widths = [width_for_duration(ms) for ms in samples]
    assert widths == sorted(widths)
    # And no two adjacent samples collapse to the same value (log scale is
    # smooth enough that 4x duration nudges width).
    for prev, nxt in pairwise(widths):
        assert nxt > prev


def test_width_matches_log_formula_in_band() -> None:
    ms = 1234
    expected = max(48.0, min(200.0, math.log(ms) * 16))
    assert width_for_duration(ms) == expected


# ---------------------------------------------------------------------------
# render_flow_ribbon
# ---------------------------------------------------------------------------


def test_empty_decisions_returns_empty_string() -> None:
    assert render_flow_ribbon("baseline", []) == ""


def test_node_count_matches_input() -> None:
    decisions = [
        _decision(DecisionType.MODEL_CALL, duration_ms=50),
        _decision(DecisionType.TOOL_CALL, duration_ms=120, name="search"),
        _decision(DecisionType.TOOL_RESULT, duration_ms=20),
        _decision(DecisionType.FINAL_OUTPUT, duration_ms=10),
    ]
    svg = render_flow_ribbon("base", decisions)
    assert _count_nodes(svg) == len(decisions)


def test_node_widths_monotonic_in_duration() -> None:
    """Decisions sorted by duration → rect widths sorted ascending.

    This guards the contract that visual width *is* duration. If someone
    swaps the formula for uniform widths, this test breaks.
    """
    durations = [25, 100, 400, 1_500, 6_000]
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=d) for d in durations]
    svg = render_flow_ribbon("base", decisions)
    widths = _node_widths(svg)
    assert len(widths) == len(durations)
    assert widths == sorted(widths)


def test_uniform_width_when_all_durations_missing() -> None:
    """All-None durations → uniform 80px nodes (no misleading variation)."""
    decisions = [_decision(DecisionType.MODEL_CALL) for _ in range(3)]
    svg = render_flow_ribbon("base", decisions)
    widths = _node_widths(svg)
    assert widths == [80.0, 80.0, 80.0]


def test_active_node_has_active_class() -> None:
    decisions = [
        _decision(DecisionType.MODEL_CALL, duration_ms=50),
        _decision(DecisionType.TOOL_CALL, duration_ms=80),
        _decision(DecisionType.TOOL_RESULT, duration_ms=30),
    ]
    svg = render_flow_ribbon("base", decisions, selected=1)
    # exactly one active node
    assert svg.count("flow-node-active") == 1
    # and it's tied to id="node-1"
    # the order in render_node is: <a ...id="node-i" ...><g class="flow-node flow-node-active">
    pattern = re.compile(
        r'id="node-1"[^>]*>\s*<g class="flow-node flow-node-active"', re.S
    )
    assert pattern.search(svg) is not None


def test_node_anchor_carries_trace_label_and_index() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("alpha", decisions, selected=0)
    # The label is HTML-escaped but the query separator '&' is structural.
    assert 'href="?trace=alpha&tab=sequence&sel=0"' in svg


def test_node_uses_type_color_via_icon_use() -> None:
    decisions = [_decision(DecisionType.TOOL_CALL, duration_ms=200, name="search")]
    svg = render_flow_ribbon("base", decisions)
    expected = TYPE_COLOR[DecisionType.TOOL_CALL.value]
    # The icon <use color="..."> picks up the type color
    assert f'color="{expected}"' in svg
    # And the icon symbol is referenced
    assert 'xlink:href="#icon-tool_call"' in svg


def test_diff_kind_added_emits_plus_glyph() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("base", decisions, diff={0: "added"})
    # outline color flips to ok and a "+" glyph shows up at the right edge
    assert 'fill="var(--ok)"' in svg
    assert ">+</text>" in svg


def test_diff_kind_removed_dims_node() -> None:
    decisions = [_decision(DecisionType.TOOL_CALL, duration_ms=50, name="rm")]
    svg = render_flow_ribbon("base", decisions, diff={0: "removed"})
    assert 'opacity="0.5"' in svg
    assert 'stroke="var(--err)"' in svg


def test_diff_kind_changed_emits_tilde_glyph() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("base", decisions, diff={0: "changed"})
    assert 'fill="var(--warn)"' in svg
    assert ">~</text>" in svg


def test_svg_height_uses_documented_constants() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("base", decisions)
    assert f'height="{RIBBON_HEIGHT}"' in svg
    # Node rect uses NODE_HEIGHT
    assert f'height="{NODE_HEIGHT}"' in svg


# ---------------------------------------------------------------------------
# render_diff_ribbons
# ---------------------------------------------------------------------------


def _pair(kind: str, a: Decision | None, b: Decision | None) -> DecisionChange:
    return DecisionChange(kind=kind, baseline=a, perturbed=b)


def test_diff_ribbons_empty_pairs_returns_empty_string() -> None:
    assert render_diff_ribbons("a", "b", []) == ""


def test_diff_ribbons_renders_both_sides() -> None:
    a = _decision(DecisionType.MODEL_CALL, duration_ms=120)
    b = _decision(DecisionType.MODEL_CALL, duration_ms=120)
    pairs = [_pair("same", a, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    # exactly two rendered nodes (baseline + perturbed)
    assert _count_nodes(svg) == 2
    # both side labels present
    assert "BASELINE" in svg
    assert "PERTURBED" in svg


def test_diff_ribbons_added_emits_ghost_stub() -> None:
    """An added decision (no baseline counterpart) shows a green dashed stub
    pointing up to a ghost circle in the baseline lane."""
    b = _decision(DecisionType.TOOL_CALL, duration_ms=80, name="new_tool")
    pairs = [_pair("added", None, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    # Only the perturbed node renders; baseline side is empty in this slot
    assert _count_nodes(svg) == 1
    # Ghost circle in ok color
    assert 'stroke="var(--ok)"' in svg
    # Dashed connection
    assert 'stroke-dasharray="3 3"' in svg
    # Perturbed node carries the added-glyph treatment
    assert ">+</text>" in svg


def test_diff_ribbons_removed_emits_ghost_stub() -> None:
    a = _decision(DecisionType.TOOL_CALL, duration_ms=80, name="old_tool")
    pairs = [_pair("removed", a, None)]
    svg = render_diff_ribbons("base", "pert", pairs)
    assert _count_nodes(svg) == 1
    assert 'stroke="var(--err)"' in svg
    assert 'stroke-dasharray="3 3"' in svg


def test_diff_ribbons_changed_emits_warn_connection() -> None:
    a = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    b = _decision(DecisionType.MODEL_CALL, duration_ms=140)
    pairs = [_pair("input_changed", a, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    assert _count_nodes(svg) == 2
    # Faint dashed warn line connects the two
    assert 'stroke="var(--warn)"' in svg
    assert 'stroke-dasharray="4 3"' in svg
    # Both nodes carry the changed glyph
    assert svg.count(">~</text>") == 2


def test_diff_ribbons_same_uses_quiet_connection() -> None:
    a = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    b = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    pairs = [_pair("same", a, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    # 'same' uses border color, not warn
    assert 'stroke="var(--border)"' in svg
    # No diff glyphs
    assert ">~</text>" not in svg
    assert ">+</text>" not in svg


def test_diff_ribbons_mixed_alignment_node_count() -> None:
    """A realistic alignment: same, changed, removed, added.

    Total rendered nodes should be: 2 (same) + 2 (changed) + 1 (removed-baseline)
    + 1 (added-perturbed) = 6.
    """
    a1 = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    a2 = _decision(DecisionType.TOOL_CALL, duration_ms=50, name="x")
    a3 = _decision(DecisionType.TOOL_RESULT, duration_ms=10)
    b1 = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    b2 = _decision(DecisionType.TOOL_CALL, duration_ms=80, name="x")
    b3 = _decision(DecisionType.FINAL_OUTPUT, duration_ms=5)
    pairs = [
        _pair("same", a1, b1),
        _pair("input_changed", a2, b2),
        _pair("removed", a3, None),
        _pair("added", None, b3),
    ]
    svg = render_diff_ribbons("base", "pert", pairs)
    assert _count_nodes(svg) == 6
