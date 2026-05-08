# Sample traces

Two pre-captured trace JSONs you can drag onto the WindTunnel Traces page to
see every section of the UI work without capturing your own.

| File | What it is |
|------|------------|
| `sample-baseline.json` | A mock research agent run — 7 decisions: model_call → tool_call(search) → tool_result → tool_call(read_document) → tool_result → model_call → final_output |
| `sample-perturbed.json` | The same agent re-run with `Truncate(fraction=0.75)` applied. The truncation drops the doc below the read_document threshold, so two decisions are skipped (5 instead of 7). `parent_run_id` links back to the baseline. |

## Try them

```bash
windtunnel ui
```

Then on the Traces page, drag both files onto the upload zone (or use **Add by path** in Settings). The lineage graph should show the perturbed lane branching off from the baseline; the diff page (after picking the two) shows two skipped decisions and a CHANGED final output.

## Regenerate

```bash
python -c "
from witness.core.store import save_trace
from witness.ui.onboarding import generate_sample_traces

baseline, perturbed = generate_sample_traces(fraction=0.75)
save_trace(baseline, 'samples/sample-baseline.json')
save_trace(perturbed, 'samples/sample-perturbed.json')
"
```

The generator is deterministic, so re-running it produces traces that diff to the same shape — only the `run_id`s change.
