"""First-run onboarding helpers — sample data generator and welcome card.

The sample data generator produces a self-contained baseline + truncate-perturbed
pair so a brand-new user can click one button on the Load page and immediately
have something to inspect / diff / fingerprint. No external imports beyond
witness itself, so it works whether or not ``examples/`` is on sys.path.
"""
from __future__ import annotations

import witness
from witness.core.schema import DecisionType, Trace
from witness.perturbations import Truncate


SAMPLE_DOC = """\
Constitutional AI is a method for training AI assistants to be helpful, harmless, and honest.

The approach uses a set of principles, called a constitution, to guide the model's behavior.
Rather than relying solely on human feedback, the model critiques and revises its own outputs.

This technique reduces the burden on human annotators while still producing aligned behavior.
The result is a model that explains its reasoning and refuses harmful requests transparently.
"""


def _summarize(doc: str) -> str:
    paras = [p.strip() for p in doc.split("\n\n") if p.strip()]
    sentences = []
    for p in paras[:3]:
        s = p.split(".")[0].strip()
        if s:
            sentences.append(s + ".")
    if not sentences:
        return "I don't have enough context to summarize."
    return " ".join(sentences)


def _search(query: str, doc: str) -> list[dict[str, str]]:
    q = (query or "").lower().strip().split()
    if not q:
        return []
    head = q[0]
    paras = [p.strip() for p in doc.split("\n\n") if p.strip()]
    return [{"para": p[:120]} for p in paras if head in p.lower()][:2]


@witness.observe(name="sample_research_agent", save=False)
def _sample_agent(doc: str) -> str:
    """Self-contained mock agent — same shape as examples/research_agent.py
    but inlined so the UI can call it without examples/ on sys.path.
    """
    witness.record_decision(
        DecisionType.MODEL_CALL,
        input={"model": "mock-claude", "prompt": "Summarize this document"},
        output={"text": "I'll search the document first."},
        duration_ms=12,
        metadata={"sdk": "mock"},
    )
    witness.record_decision(
        DecisionType.TOOL_CALL,
        input={"name": "search", "args": {"query": "main argument"}},
        output={},
        duration_ms=1,
        metadata={"sdk": "mock"},
    )
    witness.record_decision(
        DecisionType.TOOL_RESULT,
        input={"name": "search"},
        output={"hits": _search("main argument", doc)},
        duration_ms=2,
        metadata={"sdk": "mock"},
    )
    if len(doc) > 200:
        witness.record_decision(
            DecisionType.TOOL_CALL,
            input={
                "name": "read_document",
                "args": {"start": 0, "len": min(500, len(doc))},
            },
            output={},
            duration_ms=1,
            metadata={"sdk": "mock"},
        )
        witness.record_decision(
            DecisionType.TOOL_RESULT,
            input={"name": "read_document"},
            output={"text": doc[: min(500, len(doc))]},
            duration_ms=2,
            metadata={"sdk": "mock"},
        )
    final = _summarize(doc)
    witness.record_decision(
        DecisionType.MODEL_CALL,
        input={"model": "mock-claude", "prompt": "Synthesize"},
        output={"text": final},
        duration_ms=15,
        metadata={"sdk": "mock"},
    )
    witness.record_decision(
        DecisionType.FINAL_OUTPUT,
        input={},
        output={"text": final},
        metadata={"sdk": "mock"},
    )
    return final


def generate_sample_traces(
    *, fraction: float = 0.75, doc: str | None = None
) -> tuple[Trace, Trace]:
    """Capture a baseline run of the sample agent, then a truncate-perturbed
    counterfactual. Returns ``(baseline, perturbed)``.

    Both traces are fully detached from disk — the @observe decorator's save
    is suppressed. The caller is responsible for stashing them in session state.
    """
    _sample_agent(doc=doc or SAMPLE_DOC)
    baseline = _sample_agent.__witness_last_trace__  # type: ignore[attr-defined]
    if baseline is None:
        raise RuntimeError("sample agent failed to capture a trace")
    perturbed = witness.replay(
        baseline,
        Truncate(fraction=fraction),
        agent_fn=_sample_agent,
    )
    return baseline, perturbed


__all__ = ["generate_sample_traces", "SAMPLE_DOC"]
