"""Flow ribbon — Witness's signature trace visualization.

A horizontal ribbon of connected nodes, one per decision, color-coded by
type, width proportional to duration_ms. Pure SVG, server-rendered, click
via plain anchor href — no JS, no fragility.

Two public renderers:

- render_flow_ribbon(label, decisions, *, selected, diff)
    Single ribbon for the Sequence tab on a trace detail.

- render_diff_ribbons(label_a, label_b, pairs, *, selected_a, selected_b)
    Two stacked ribbons with connection lines + diff annotations for the
    Diffs page hero view.
"""
from __future__ import annotations

import math
from html import escape
from typing import Literal

from witness.core.schema import Decision, DecisionType
from witness.diff.behavioral import DecisionChange

# Type → color mapping. Used in both renderers; defining here keeps the
# diff and detail views in lockstep on color.
TYPE_COLOR: dict[str, str] = {
    DecisionType.MODEL_CALL.value:   "var(--accent)",     # amber
    DecisionType.TOOL_CALL.value:    "#58A6FF",            # blue
    DecisionType.TOOL_RESULT.value:  "#3FB950",            # green
    DecisionType.REASONING.value:    "var(--fg-muted)",    # gray
    DecisionType.FINAL_OUTPUT.value: "#BC8CFF",            # purple
    DecisionType.CUSTOM.value:       "var(--fg-faint)",
}


# Lucide icon paths (24x24 viewBox), rendered at 12x12 inside each node.
# Each path is mounted via <symbol> + <use> so the SVG payload stays tight
# even on long traces.
_ICON_PATHS: dict[str, str] = {
    DecisionType.MODEL_CALL.value: (
        # cpu — distinctive square-with-pins silhouette at 12px
        "M9 2v2 M15 2v2 M9 20v2 M15 20v2 M2 9h2 M2 15h2 M20 9h2 M20 15h2 "
        "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z "
        "M9 9h6v6H9z"
    ),
    DecisionType.TOOL_CALL.value: (
        # wrench
        "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94"
        "l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
    ),
    DecisionType.TOOL_RESULT.value: (
        # check (broad strokes — reads at 12px)
        "M20 6 9 17l-5-5"
    ),
    DecisionType.REASONING.value: (
        # git-branch
        "M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z "
        "M15 6a9 9 0 0 0-9 9"
    ),
    DecisionType.FINAL_OUTPUT.value: (
        # flag
        "M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z M4 22V15"
    ),
    DecisionType.CUSTOM.value: (
        # circle
        "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"
    ),
}


# ---------------------------------------------------------------------------
# Layout constants — single source of truth so tests can assert on them
# ---------------------------------------------------------------------------

LEFT_PAD = 12
RIGHT_PAD = 12
NODE_HEIGHT = 28
NODE_GAP = 8
TOP_PAD = 14            # leaves headroom above the node for hover lift
RIBBON_HEIGHT = 96
DURATION_LABEL_OFFSET = 14   # below node baseline


def width_for_duration(duration_ms: int | None) -> float:
    """Compute node width: clamp(48, log(ms)*16, 200), or 80 if duration unknown.

    The log scale surfaces slow decisions visually without letting a 12-second
    LLM call hijack the entire viewport.
    """
    if duration_ms is None:
        return 80.0
    ms = max(1, int(duration_ms))
    return max(48.0, min(200.0, math.log(ms) * 16))


# ---------------------------------------------------------------------------
# Single ribbon
# ---------------------------------------------------------------------------


def render_flow_ribbon(
    label: str,
    decisions: list[Decision],
    *,
    selected: int = 0,
    diff: dict[int, Literal["added", "removed", "changed"]] | None = None,
) -> str:
    """Render the trace's decision sequence as a horizontal flow ribbon.

    Returns an SVG string ready to be injected via st.markdown(unsafe_allow_html=True).
    Pure function — no Streamlit calls. Empty decisions → empty string;
    callers should render the canonical empty state instead.
    """
    if not decisions:
        return ""

    diff = diff or {}
    all_none = all(d.duration_ms is None for d in decisions)

    # Compute x positions
    x = float(LEFT_PAD)
    positions: list[tuple[float, float]] = []
    for d in decisions:
        w = 80.0 if all_none else width_for_duration(d.duration_ms)
        positions.append((x, w))
        x += w + NODE_GAP
    total_width = max(int(x + RIGHT_PAD), 320)

    parts: list[str] = []
    parts.append(_svg_open(total_width, RIBBON_HEIGHT, classes="flow-ribbon"))
    parts.append(_defs())
    parts.extend(_render_edges(positions, len(decisions), y=TOP_PAD + NODE_HEIGHT / 2))
    for i, d in enumerate(decisions):
        parts.append(
            _render_node(
                d,
                i,
                positions[i],
                label=label,
                selected=(i == selected),
                diff_kind=diff.get(i),
                hide_duration=all_none,
            )
        )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Stacked diff ribbons (baseline + perturbed)
# ---------------------------------------------------------------------------


def render_diff_ribbons(
    label_a: str,
    label_b: str,
    pairs: list[DecisionChange],
    *,
    selected_a: int = -1,
    selected_b: int = -1,
) -> str:
    """Render baseline and perturbed flow ribbons stacked, with connection
    lines for matched pairs and ghost stubs for added/removed.

    ``pairs`` is the alignment list from ``TraceDiff.alignment.pairs``. We
    walk it in order so the two ribbons stay visually aligned: matched
    pairs occupy the same horizontal slot in both ribbons; added/removed
    leave a gap on the corresponding side.
    """
    if not pairs:
        return ""

    # Collect per-side decisions and their alignment-slot index, plus
    # diff-kind annotations keyed by side+index.
    a_decisions: list[Decision | None] = []
    b_decisions: list[Decision | None] = []
    a_kinds: dict[int, str] = {}
    b_kinds: dict[int, str] = {}

    for slot, ch in enumerate(pairs):
        a_decisions.append(ch.baseline)
        b_decisions.append(ch.perturbed)
        if ch.kind == "removed" and ch.baseline is not None:
            a_kinds[slot] = "removed"
        elif ch.kind == "added" and ch.perturbed is not None:
            b_kinds[slot] = "added"
        elif ch.kind in ("input_changed", "output_changed", "both_changed", "type_changed"):
            if ch.baseline is not None:
                a_kinds[slot] = "changed"
            if ch.perturbed is not None:
                b_kinds[slot] = "changed"
        # 'same' → no annotation

    # Compute per-slot widths: max of the two sides at that slot so the
    # ribbons stay column-aligned. If a side has no decision, use the
    # other side's width.
    slot_widths: list[float] = []
    use_uniform = all(
        (d is None) or d.duration_ms is None
        for d in (*a_decisions, *b_decisions)
    )
    for a_d, b_d in zip(a_decisions, b_decisions, strict=True):
        wa = 80.0 if use_uniform else (
            width_for_duration(a_d.duration_ms) if a_d else 0.0
        )
        wb = 80.0 if use_uniform else (
            width_for_duration(b_d.duration_ms) if b_d else 0.0
        )
        slot_widths.append(max(wa, wb, 56.0))  # min 56 so ghosts have room

    # Compute slot x positions (shared across both ribbons)
    x = float(LEFT_PAD)
    slot_positions: list[float] = []
    for w in slot_widths:
        slot_positions.append(x)
        x += w + NODE_GAP
    total_width = max(int(x + RIGHT_PAD), 320)

    # Layout: 2 ribbons + connection band between them
    a_y = 0
    band_h = 30
    b_y = RIBBON_HEIGHT + band_h
    height = b_y + RIBBON_HEIGHT

    parts: list[str] = []
    parts.append(_svg_open(total_width, height, classes="flow-diff-ribbons"))
    parts.append(_defs())

    # Side labels (left margin)
    parts.append(
        f'<text x="{LEFT_PAD}" y="10" font-family="ui-monospace, monospace" '
        f'font-size="9" font-weight="600" fill="var(--fg-faint)" '
        f'letter-spacing="0.06em">BASELINE</text>'
    )
    parts.append(
        f'<text x="{LEFT_PAD}" y="{b_y + 10}" font-family="ui-monospace, monospace" '
        f'font-size="9" font-weight="600" fill="var(--fg-faint)" '
        f'letter-spacing="0.06em">PERTURBED</text>'
    )

    # Connection lines + ghost stubs
    parts.append('<g class="flow-conns">')
    for slot, ch in enumerate(pairs):
        ax = slot_positions[slot] + slot_widths[slot] / 2
        ay = a_y + TOP_PAD + NODE_HEIGHT  # bottom of baseline node
        by = b_y + TOP_PAD                # top of perturbed node
        if ch.baseline is not None and ch.perturbed is not None:
            # Matched (same or changed) → faint vertical line
            stroke = (
                "var(--warn)"
                if ch.kind != "same"
                else "var(--border)"
            )
            opacity = "0.6" if ch.kind != "same" else "0.4"
            parts.append(
                f'<line x1="{ax}" y1="{ay}" x2="{ax}" y2="{by}" '
                f'stroke="{stroke}" stroke-width="1" opacity="{opacity}" '
                f'stroke-dasharray="{"4 3" if ch.kind != "same" else ""}"/>'
            )
        elif ch.baseline is not None and ch.perturbed is None:
            # Removed: dashed stub from baseline going down to a ghost dot
            ghost_y = b_y + TOP_PAD + NODE_HEIGHT / 2
            parts.append(
                f'<line x1="{ax}" y1="{ay}" x2="{ax}" y2="{ghost_y}" '
                f'stroke="var(--err)" stroke-width="1" opacity="0.4" '
                f'stroke-dasharray="3 3"/>'
            )
            parts.append(
                f'<circle cx="{ax}" cy="{ghost_y}" r="2.5" '
                f'fill="none" stroke="var(--err)" stroke-width="1" '
                f'opacity="0.6"/>'
            )
        elif ch.baseline is None and ch.perturbed is not None:
            # Added: dashed stub up from perturbed to a ghost dot in the baseline lane
            ghost_y = a_y + TOP_PAD + NODE_HEIGHT / 2
            parts.append(
                f'<line x1="{ax}" y1="{ghost_y}" x2="{ax}" y2="{by}" '
                f'stroke="var(--ok)" stroke-width="1" opacity="0.4" '
                f'stroke-dasharray="3 3"/>'
            )
            parts.append(
                f'<circle cx="{ax}" cy="{ghost_y}" r="2.5" '
                f'fill="none" stroke="var(--ok)" stroke-width="1" '
                f'opacity="0.6"/>'
            )
    parts.append('</g>')

    # Per-side edges (arrow chains) — only between adjacent existing nodes.
    parts.append('<g class="flow-edges">')
    parts.extend(
        _render_aligned_edges(
            a_decisions, slot_positions, slot_widths,
            y=a_y + TOP_PAD + NODE_HEIGHT / 2,
        )
    )
    parts.extend(
        _render_aligned_edges(
            b_decisions, slot_positions, slot_widths,
            y=b_y + TOP_PAD + NODE_HEIGHT / 2,
        )
    )
    parts.append('</g>')

    # Baseline ribbon nodes
    for slot, d in enumerate(a_decisions):
        if d is None:
            continue
        x_pos = slot_positions[slot]
        w = 80.0 if use_uniform else width_for_duration(d.duration_ms)
        parts.append(
            _render_node(
                d,
                slot,
                (x_pos, w),
                label=label_a,
                selected=(slot == selected_a),
                diff_kind=a_kinds.get(slot),
                hide_duration=use_uniform,
                y_offset=a_y,
                href_tab="diffs",
            )
        )

    # Perturbed ribbon nodes
    for slot, d in enumerate(b_decisions):
        if d is None:
            continue
        x_pos = slot_positions[slot]
        w = 80.0 if use_uniform else width_for_duration(d.duration_ms)
        parts.append(
            _render_node(
                d,
                slot,
                (x_pos, w),
                label=label_b,
                selected=(slot == selected_b),
                diff_kind=b_kinds.get(slot),
                hide_duration=use_uniform,
                y_offset=b_y,
                href_tab="diffs",
            )
        )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Internal SVG helpers
# ---------------------------------------------------------------------------


def _svg_open(width: int, height: int, *, classes: str) -> str:
    return (
        f'<svg class="{classes}" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink">'
    )


def _defs() -> str:
    parts: list[str] = ['<defs>']
    for type_value, path in _ICON_PATHS.items():
        parts.append(
            f'<symbol id="icon-{type_value}" viewBox="0 0 24 24">'
            f'<path d="{path}" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'</symbol>'
        )
    parts.append(
        '<marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto">'
        '<path d="M 0 1 L 8 5 L 0 9" fill="none" stroke="var(--border)" '
        'stroke-width="1" stroke-linecap="round"/>'
        '</marker>'
    )
    parts.append('</defs>')
    return "".join(parts)


def _render_edges(
    positions: list[tuple[float, float]], n: int, *, y: float
) -> list[str]:
    parts: list[str] = []
    for i in range(n - 1):
        x_end = positions[i][0] + positions[i][1]
        x_next = positions[i + 1][0]
        parts.append(
            f'<line x1="{x_end}" y1="{y}" x2="{x_next}" y2="{y}" '
            f'stroke="var(--border)" stroke-width="1" '
            f'marker-end="url(#flow-arrow)"/>'
        )
    return parts


def _render_aligned_edges(
    decisions: list[Decision | None],
    slot_positions: list[float],
    slot_widths: list[float],
    *,
    y: float,
) -> list[str]:
    """Edges between consecutive existing decisions on the same row, skipping
    over slots where the decision is None (missing on this side)."""
    parts: list[str] = []
    prev_idx: int | None = None
    for i, d in enumerate(decisions):
        if d is None:
            continue
        if prev_idx is not None:
            x_end = slot_positions[prev_idx] + slot_widths[prev_idx]
            x_next = slot_positions[i]
            parts.append(
                f'<line x1="{x_end}" y1="{y}" x2="{x_next}" y2="{y}" '
                f'stroke="var(--border)" stroke-width="1" '
                f'marker-end="url(#flow-arrow)"/>'
            )
        prev_idx = i
    return parts


def _render_node(
    d: Decision,
    i: int,
    pos: tuple[float, float],
    *,
    label: str,
    selected: bool,
    diff_kind: str | None,
    hide_duration: bool,
    y_offset: float = 0.0,
    href_tab: str = "sequence",
) -> str:
    x_n, w_n = pos
    color = TYPE_COLOR.get(d.type.value, "var(--fg-muted)")

    outline_color = color
    outline_width = "1"
    opacity = "1"
    glyph = ""
    if diff_kind == "removed":
        outline_color = "var(--err)"
        outline_width = "2"
        opacity = "0.5"
    elif diff_kind == "added":
        outline_color = "var(--ok)"
        outline_width = "2"
        glyph = (
            f'<text x="{x_n + w_n - 6}" y="{y_offset + TOP_PAD + 11}" '
            f'font-family="ui-monospace, monospace" font-size="13" '
            f'font-weight="700" fill="var(--ok)" text-anchor="end">+</text>'
        )
    elif diff_kind == "changed":
        outline_color = "var(--warn)"
        outline_width = "2"
        glyph = (
            f'<text x="{x_n + w_n - 6}" y="{y_offset + TOP_PAD + 11}" '
            f'font-family="ui-monospace, monospace" font-size="13" '
            f'font-weight="700" fill="var(--warn)" text-anchor="end">~</text>'
        )

    # Glow halo for active node — sits behind the rect
    halo = ""
    if selected:
        halo = (
            f'<rect x="{x_n - 3}" y="{y_offset + TOP_PAD - 5}" '
            f'width="{w_n + 6}" height="{NODE_HEIGHT + 6}" rx="9" '
            f'fill="{color}" opacity="0.15"/>'
        )
        outline_width = "2"

    node_y = y_offset + TOP_PAD - (2 if selected else 0)

    # Compress label to fit
    label_text = _compress_type_label(d.type.value, w_n - 28)
    text_x = x_n + 26
    text_y = node_y + NODE_HEIGHT / 2 + 4

    href = f"?trace={escape(label)}&tab={href_tab}&sel={i}"
    duration_text = ""
    if not hide_duration:
        dur = _format_duration(d.duration_ms)
        duration_text = (
            f'<text x="{x_n + w_n / 2}" '
            f'y="{y_offset + TOP_PAD + NODE_HEIGHT + DURATION_LABEL_OFFSET}" '
            f'font-family="ui-monospace, monospace" font-size="10" '
            f'fill="var(--fg-faint)" text-anchor="middle">{escape(dur)}</text>'
        )

    return (
        f'<a href="{href}" xlink:href="{href}" id="node-{i}" '
        f'class="flow-node-link">'
        f'<g class="flow-node{" flow-node-active" if selected else ""}" '
        f'opacity="{opacity}">'
        f'{halo}'
        f'<rect x="{x_n}" y="{node_y}" width="{w_n}" height="{NODE_HEIGHT}" '
        f'rx="6" fill="var(--bg-raised)" '
        f'stroke="{outline_color}" stroke-width="{outline_width}"/>'
        f'<use xlink:href="#icon-{d.type.value}" '
        f'x="{x_n + 8}" y="{node_y + (NODE_HEIGHT - 12) / 2}" '
        f'width="12" height="12" color="{color}"/>'
        f'<text x="{text_x}" y="{text_y}" '
        f'font-family="ui-monospace, JetBrains Mono, monospace" '
        f'font-size="10.5" font-weight="600" fill="var(--fg)" '
        f'letter-spacing="0.04em">{escape(label_text)}</text>'
        f'{glyph}'
        f'</g></a>'
        f'{duration_text}'
    )


def _compress_type_label(type_value: str, available_px: float) -> str:
    """Truncate a type label to fit. ~7px per char at 10.5px mono."""
    label = type_value.upper()
    max_chars = max(4, int(available_px / 7))
    if len(label) <= max_chars:
        return label
    return label[:max_chars]


def _format_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


__all__ = [
    "NODE_HEIGHT",
    "RIBBON_HEIGHT",
    "TYPE_COLOR",
    "render_diff_ribbons",
    "render_flow_ribbon",
    "width_for_duration",
]
