"""Tests for ``witness.ui.components.flow``.

The flow ribbon is pure SVG rendering — no Streamlit, no DOM. We can therefore
unit-test it by inspecting the returned string. The asserts below cover the
properties the brief calls out as load-bearing:

- node count matches the input length
- node width grows monotonically with duration_ms (above the label-floor)
- the active (selected) node carries ``flow-node-active``
- diff annotations (``+``, ``~``, ghost stubs) are emitted on the right slots
- NO icons inside data primitives — refused per the strip-ornament brief
- type labels are full and never truncated (``FINAL_OUTPUT``, not ``FINAL_O``)
- each node has a top accent path in the type color
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
    """Pull node-body rect widths in document order.

    Anchor on the unique ``class="flow-node-body"`` signature so we skip
    the halo rect, marker glyphs, and any other rect that might appear.
    """
    return [
        float(m)
        for m in re.findall(
            r'<rect class="flow-node-body" [^>]*?width="([\d.]+)"',
            svg,
        )
    ]


def _accent_fills(svg: str) -> list[str]:
    """Return the fill color of every accent path in document order."""
    return re.findall(
        r'<path class="flow-accent" [^>]*?fill="([^"]+)"',
        svg,
    )


# ---------------------------------------------------------------------------
# width_for_duration — the math (unchanged after the strip-ornament refactor;
# this is the log-scaled duration component, with the label-floor applied
# separately in _node_width)
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
    """Above the label-floor, decisions sorted by duration must produce
    non-decreasing rect widths.

    The label-floor for MODEL_CALL is 10*7.2+24 ≈ 96px, so durations below
    ~400ms (where log(ms)*16 < 96) all collapse to 96. Pick durations well
    above that band to assert strict growth.
    """
    durations = [500, 2_000, 5_000, 10_000, 50_000]
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=d) for d in durations]
    svg = render_flow_ribbon("base", decisions)
    widths = _node_widths(svg)
    assert len(widths) == len(durations)
    assert widths == sorted(widths)
    # And strictly increasing within this band — the log curve doesn't
    # plateau at these durations.
    for prev, nxt in pairwise(widths):
        assert nxt > prev, f"widths regressed: {widths}"


def test_node_widths_floor_to_label_for_short_durations() -> None:
    """Short durations must not produce nodes too narrow to fit the label.

    A 25ms TOOL_RESULT node would have log_w ≈ 51.5 — which is shorter
    than the 11-char ``TOOL_RESULT`` label needs (≈103px). The label
    floor is what guarantees no truncation.
    """
    decisions = [_decision(DecisionType.TOOL_RESULT, duration_ms=25)]
    svg = render_flow_ribbon("base", decisions)
    widths = _node_widths(svg)
    assert len(widths) == 1
    # 11 chars * 7.2 + 24 = 103.2
    assert widths[0] >= 103.0


def test_uniform_min_width_when_all_durations_missing() -> None:
    """All-None durations → label-derived widths.

    There's no longer a fixed 80px uniform — width is always at least the
    label width. For 3 MODEL_CALL nodes (10 chars), each is 96px.
    """
    decisions = [_decision(DecisionType.MODEL_CALL) for _ in range(3)]
    svg = render_flow_ribbon("base", decisions)
    widths = _node_widths(svg)
    expected = 10 * 7.2 + 24  # MODEL_CALL = 10 chars
    assert widths == [expected, expected, expected]


def test_active_node_has_active_class() -> None:
    decisions = [
        _decision(DecisionType.MODEL_CALL, duration_ms=50),
        _decision(DecisionType.TOOL_CALL, duration_ms=80),
        _decision(DecisionType.TOOL_RESULT, duration_ms=30),
    ]
    svg = render_flow_ribbon("base", decisions, selected=1)
    # exactly one active node
    assert svg.count("flow-node-active") == 1
    # and it's tied to id="node-1". The order in render_node is:
    #   <a ...id="node-i" ...><g class="flow-node flow-node-active">
    pattern = re.compile(
        r'id="node-1"[^>]*>\s*<g class="flow-node flow-node-active"', re.S
    )
    assert pattern.search(svg) is not None


def test_node_anchor_carries_trace_label_and_index() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("alpha", decisions, selected=0)
    # The label is HTML-escaped but the query separator '&' is structural.
    assert 'href="?trace=alpha&tab=sequence&sel=0"' in svg


# ---------------------------------------------------------------------------
# Strip-ornament invariants — the ribbon must communicate type via color
# (top accent bar) and typography (full type label) only.
# ---------------------------------------------------------------------------


def test_no_icon_references_inside_nodes() -> None:
    """Premium dev tools never put pictographic content inside data
    primitives. Verify there are no ``<use>`` or ``#icon-…`` references
    anywhere in the ribbon SVG."""
    decisions = [
        _decision(DecisionType.MODEL_CALL, duration_ms=50),
        _decision(DecisionType.TOOL_CALL, duration_ms=80, name="search"),
        _decision(DecisionType.TOOL_RESULT, duration_ms=20),
        _decision(DecisionType.REASONING, duration_ms=10),
        _decision(DecisionType.FINAL_OUTPUT, duration_ms=5),
        _decision(DecisionType.CUSTOM, duration_ms=1),
    ]
    svg = render_flow_ribbon("base", decisions)
    assert "<use " not in svg
    assert "xlink:href=\"#icon-" not in svg
    assert "<symbol " not in svg


def test_no_emoji_glyphs_inside_nodes() -> None:
    """The accidental Material-Symbols-as-text bug from earlier rounds —
    where ``arrow_right`` leaked through as literal text — must not recur.
    Generic guard: no common emoji codepoints in the SVG."""
    decisions = [_decision(DecisionType.TOOL_CALL, duration_ms=50, name="x")]
    svg = render_flow_ribbon("base", decisions)
    for emoji in ("📦", "🔧", "✓", "🚩", "⚙", "🧠"):
        assert emoji not in svg


def test_full_type_label_not_truncated() -> None:
    """``FINAL_OUTPUT`` is the longest label (12 chars). The width must
    accommodate it in full — ``FINAL_O`` would be a regression of the
    pre-strip-ornament truncation logic."""
    decisions = [_decision(DecisionType.FINAL_OUTPUT, duration_ms=5)]
    svg = render_flow_ribbon("base", decisions)
    assert ">FINAL_OUTPUT</text>" in svg
    # The truncated form must NOT appear anywhere.
    assert ">FINAL_O</text>" not in svg
    assert ">FINAL_OU</text>" not in svg


def test_each_node_has_one_accent_path_in_type_color() -> None:
    """Every node has exactly one ``flow-accent`` path painted in its
    type's color. This is the only color signal inside the node."""
    decisions = [
        _decision(DecisionType.MODEL_CALL, duration_ms=50),
        _decision(DecisionType.TOOL_CALL, duration_ms=80),
        _decision(DecisionType.TOOL_RESULT, duration_ms=20),
        _decision(DecisionType.FINAL_OUTPUT, duration_ms=5),
    ]
    svg = render_flow_ribbon("base", decisions)
    fills = _accent_fills(svg)
    expected = [TYPE_COLOR[d.type.value] for d in decisions]
    assert fills == expected
    # Sanity: one accent per node, not more, not fewer.
    assert len(fills) == len(decisions)


def test_active_node_border_is_type_color() -> None:
    """When a node is selected, its border flips from var(--border) to
    its type color so the ring + halo + accent all read together."""
    decisions = [_decision(DecisionType.TOOL_CALL, duration_ms=80, name="x")]
    svg = render_flow_ribbon("base", decisions, selected=0)
    expected = TYPE_COLOR[DecisionType.TOOL_CALL.value]
    # Body rect carries stroke=type_color when active.
    pattern = re.compile(
        rf'<rect class="flow-node-body" [^>]*?stroke="{re.escape(expected)}"',
    )
    assert pattern.search(svg) is not None


def test_entrance_animation_delays_are_staggered() -> None:
    """Verify each node's inline ``animation-delay`` follows the 40ms
    stagger so the entrance reads left-to-right.

    Edges have their own animation-delay attributes, so we anchor on the
    ``flow-node`` <g> to pick up node delays specifically.
    """
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50) for _ in range(4)]
    svg = render_flow_ribbon("base", decisions)
    node_delays = [
        int(m)
        for m in re.findall(
            r'<g class="flow-node[^"]*"[^>]*?style="animation-delay: (\d+)ms"',
            svg,
        )
    ]
    assert node_delays == [0, 40, 80, 120]


def test_diff_kind_added_emits_plus_glyph() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("base", decisions, diff={0: "added"})
    # Glyph is an SVG <text> element, not a glyph icon.
    assert 'class="flow-diff-glyph">+</text>' in svg
    # And the border flips to ok.
    assert 'stroke="var(--ok)"' in svg


def test_diff_kind_removed_dims_node() -> None:
    decisions = [_decision(DecisionType.TOOL_CALL, duration_ms=50, name="rm")]
    svg = render_flow_ribbon("base", decisions, diff={0: "removed"})
    assert 'opacity="0.5"' in svg
    assert 'stroke="var(--err)"' in svg


def test_diff_kind_changed_emits_tilde_glyph() -> None:
    decisions = [_decision(DecisionType.MODEL_CALL, duration_ms=50)]
    svg = render_flow_ribbon("base", decisions, diff={0: "changed"})
    assert 'class="flow-diff-glyph">~</text>' in svg
    assert 'stroke="var(--warn)"' in svg


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


def test_diff_ribbons_no_icons_either_side() -> None:
    """The strip-ornament rule applies to the diff overlay too."""
    a = _decision(DecisionType.TOOL_CALL, duration_ms=80, name="search")
    b = _decision(DecisionType.TOOL_CALL, duration_ms=80, name="search")
    pairs = [_pair("same", a, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    assert "<use " not in svg
    assert "xlink:href=\"#icon-" not in svg


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
    assert 'class="flow-diff-glyph">+</text>' in svg


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
    assert svg.count('class="flow-diff-glyph">~</text>') == 2


def test_diff_ribbons_same_uses_quiet_connection() -> None:
    a = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    b = _decision(DecisionType.MODEL_CALL, duration_ms=100)
    pairs = [_pair("same", a, b)]
    svg = render_diff_ribbons("base", "pert", pairs)
    # 'same' uses border color, not warn
    assert 'stroke="var(--border)"' in svg
    # No diff glyphs
    assert 'class="flow-diff-glyph">~</text>' not in svg
    assert 'class="flow-diff-glyph">+</text>' not in svg


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
