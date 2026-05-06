"""Pure-Python export helpers for the Witness UI.

These functions don't import streamlit — they take Trace / TraceDiff /
Fingerprint objects and return strings or dicts ready to download. That keeps
them unit-testable without spinning up a UI.
"""
from __future__ import annotations

import json
from typing import Any

from witness.core.schema import Trace
from witness.diff.behavioral import DecisionChange, TraceDiff
from witness.diff.fingerprint import Fingerprint


def diff_to_markdown(d: TraceDiff, *, title: str = "Witness diff") -> str:
    """Render a behavioral diff as a brief, paste-ready markdown report.

    The shape is optimized for PR descriptions and chat messages — short
    summary, tables for tool calls and decisions, fenced code block for the
    final output diff. Not the place for a 1000-line transcript.
    """
    base = d.baseline
    pert = d.perturbed

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")

    # One-line perturbation header
    if pert.perturbation:
        params = " ".join(f"`{k}={v}`" for k, v in pert.perturbation.params.items())
        lines.append(f"**perturbation:** `{pert.perturbation.type}` {params}")
        lines.append("")

    # Summary block
    decisions_delta = len(pert.decisions) - len(base.decisions)
    delta_str = (
        f"+{decisions_delta}" if decisions_delta > 0 else str(decisions_delta)
    )
    final_changed = "yes" if d.final_output_changed else "no"
    wall_delta = (
        f"{d.wall_time_delta_ms:+d} ms" if d.wall_time_delta_ms is not None else "n/a"
    )

    lines.append("| metric | baseline | perturbed | delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| decisions | {len(base.decisions)} | {len(pert.decisions)} | {delta_str} |"
    )
    lines.append(
        f"| wall time | {_fmt_ms(base.wall_time_ms)} | {_fmt_ms(pert.wall_time_ms)} | {wall_delta} |"
    )
    lines.append(f"| final output changed | — | — | **{final_changed}** |")
    lines.append("")

    # Tool counts
    if d.tool_counts_baseline or d.tool_counts_perturbed:
        lines.append("## tool calls")
        lines.append("")
        lines.append("| tool | baseline | perturbed | delta |")
        lines.append("|---|---|---|---|")
        all_tools = sorted(set(d.tool_counts_baseline) | set(d.tool_counts_perturbed))
        for t in all_tools:
            b = d.tool_counts_baseline.get(t, 0)
            p = d.tool_counts_perturbed.get(t, 0)
            delta = p - b
            delta_cell = (
                f"**{delta:+d}**" if delta != 0 else "0"
            )
            lines.append(f"| `{t}` | {b} | {p} | {delta_cell} |")
        lines.append("")

    # Decision-level changes (only the ones that changed)
    changes = [c for c in d.alignment.pairs if c.kind != "same"]
    if changes:
        lines.append("## decisions changed")
        lines.append("")
        for ch in changes:
            lines.append(f"- {_md_change(ch)}")
        lines.append("")

    # Final output
    lines.append("## final output")
    lines.append("")
    if d.final_output_changed:
        lines.append("**baseline:**")
        lines.append("")
        lines.append(_fenced(_str_value(base.final_output)))
        lines.append("")
        lines.append("**perturbed:**")
        lines.append("")
        lines.append(_fenced(_str_value(pert.final_output)))
    else:
        lines.append("_unchanged_")

    return "\n".join(lines)


def fingerprint_to_markdown(fp: Fingerprint, *, title: str = "Witness fingerprint") -> str:
    """Render a Fingerprint as paste-ready markdown."""
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**baseline:** `{fp.baseline_run_id}` — {len(fp.runs)} run(s)")
    lines.append("")

    overall = fp.overall_stability()
    fout = fp.final_output_stability()
    lines.append("| metric | score |")
    lines.append("|---|---|")
    lines.append(f"| overall stability | {overall:.2f} {_score_marker(overall)} |")
    lines.append(f"| final-output stability | {fout:.2f} {_score_marker(fout)} |")
    lines.append("")

    scores = fp.stability_by_decision_type()
    if scores:
        lines.append("## stability by decision type")
        lines.append("")
        lines.append("| decision type | score |")
        lines.append("|---|---|")
        for dtype, score in sorted(scores.items()):
            lines.append(f"| `{dtype}` | {score:.2f} {_score_marker(score)} |")
        lines.append("")

    if fp.runs:
        lines.append("## per-run summary")
        lines.append("")
        lines.append("| perturbation | params | Δ decisions | final |")
        lines.append("|---|---|---|---|")
        for r in fp.runs:
            params = ", ".join(f"`{k}={v}`" for k, v in r.perturbation_params.items()) or "—"
            delta = len(r.diff.perturbed.decisions) - len(r.diff.baseline.decisions)
            delta_str = f"{delta:+d}" if delta != 0 else "0"
            final = "**CHANGED**" if r.diff.final_output_changed else "same"
            lines.append(f"| `{r.perturbation_type}` | {params} | {delta_str} | {final} |")
        lines.append("")

    return "\n".join(lines)


def trace_to_markdown(t: Trace, *, title: str | None = None) -> str:
    """Render a single trace as a markdown summary card."""
    title = title or f"Witness trace — {t.agent_name}"
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- **run_id:** `{t.run_id}`")
    lines.append(f"- **agent:** `{t.agent_name}`")
    if t.model:
        lines.append(f"- **model:** `{t.model}`")
    if t.tools_available:
        tools = ", ".join(f"`{x}`" for x in t.tools_available)
        lines.append(f"- **tools:** {tools}")
    lines.append(f"- **decisions:** {len(t.decisions)}")
    lines.append(f"- **messages:** {len(t.messages)}")
    if t.wall_time_ms is not None:
        lines.append(f"- **wall time:** {_fmt_ms(t.wall_time_ms)}")
    if t.perturbation:
        lines.append(
            f"- **perturbation:** `{t.perturbation.type}` "
            + " ".join(f"`{k}={v}`" for k, v in t.perturbation.params.items())
        )
        lines.append(f"- **parent run:** `{t.parent_run_id}`")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fingerprint preset save/load (Tier-A: spec format only; UI hooks in app.py)
# ---------------------------------------------------------------------------


def preset_to_json(specs: list[tuple[str, dict[str, Any]]]) -> str:
    """Serialize a fingerprint preset (list of (perturbation_name, params)) to JSON."""
    payload = {
        "witness_preset_version": 1,
        "perturbations": [{"type": t, "params": p} for t, p in specs],
    }
    return json.dumps(payload, indent=2)


def preset_from_json(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Inverse of `preset_to_json`. Validates shape and returns the spec list."""
    data = json.loads(text)
    if not isinstance(data, dict) or "perturbations" not in data:
        raise ValueError("not a valid Witness preset (missing 'perturbations')")
    out: list[tuple[str, dict[str, Any]]] = []
    for item in data["perturbations"]:
        if not isinstance(item, dict) or "type" not in item:
            raise ValueError("each perturbation entry needs 'type'")
        out.append((item["type"], dict(item.get("params") or {})))
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _md_change(ch: DecisionChange) -> str:
    if ch.kind == "removed" and ch.baseline:
        return f"`[{ch.baseline.step_id[:14]}]` **REMOVED** {_decision_md(ch.baseline)}"
    if ch.kind == "added" and ch.perturbed:
        return f"`[{ch.perturbed.step_id[:14]}]` **ADDED** {_decision_md(ch.perturbed)}"
    d_obj = ch.baseline or ch.perturbed
    label = {
        "input_changed": "input changed",
        "output_changed": "output changed",
        "both_changed": "input + output changed",
        "type_changed": "type changed",
    }.get(ch.kind, ch.kind)
    step = d_obj.step_id[:14] if d_obj else "?"
    return f"`[{step}]` _{label}_ {_decision_md(d_obj) if d_obj else ''}"


def _decision_md(d: Any) -> str:
    if d is None:
        return ""
    if d.type.value == "tool_call":
        name = d.input.get("name") or d.input.get("tool") or "?"
        return f"tool_call · `{name}`"
    if d.type.value == "model_call":
        m = d.input.get("model") or ""
        return f"model_call · `{m}`" if m else "model_call"
    return f"`{d.type.value}`"


def _str_value(v: Any, *, max_chars: int = 4000) -> str:
    if v is None:
        return "<none>"
    if isinstance(v, str):
        s = v
    else:
        try:
            s = json.dumps(v, indent=2, default=str)
        except (TypeError, ValueError):
            s = repr(v)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n… <truncated>"
    return s


def _fenced(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```"


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "?"
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.2f} s"


def _score_marker(score: float) -> str:
    if score >= 0.66:
        return "(stable)"
    if score >= 0.33:
        return "(mixed)"
    return "(fragile)"


__all__ = [
    "diff_to_markdown",
    "fingerprint_to_markdown",
    "trace_to_markdown",
    "preset_to_json",
    "preset_from_json",
]
