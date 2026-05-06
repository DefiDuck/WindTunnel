# Changelog

## Unreleased

### Web UI — functional polish (Tier A)

A second pass on the Streamlit UI focused on interaction quality, not visuals
(visual side is a parallel workstream).

- **Drag-and-drop trace upload** — replaces the path-only input with
  `st.file_uploader(accept_multiple_files=True)`. Path input remains under an
  expander for power users.
- **Live progress + status panels** — replays and fingerprint loops now use
  `st.status` with streamed detail; fingerprint also shows a per-run progress
  bar (`Running 2/4: prompt_injection…`).
- **Toast notifications** — short non-blocking feedback (`st.toast`) on every
  load / remove / perturbation-complete. No more inline success banners.
- **Click-to-expand decision rows** — Inspect page renders decisions as
  expanders by default; toggle to switch to the dataframe view.
- **Search & filter** — text input above decisions, messages, and the diff
  timeline; live case-insensitive filter across all columns.
- **Designed empty states** — "No traces loaded" pages now offer a CTA button
  that switches to the Load page.
- **Confirmation on destructive actions** — Remove a trace requires a second
  click (auto-resets after 4 s).
- **Markdown export** — Diff, Perturb, Fingerprint, and Inspect pages each
  expose a "Download as markdown" button. Output is paste-ready for PR
  descriptions / Slack / docs.
- **Fingerprint preset save/load** — download the current perturbation list as
  JSON, upload it later to repeat the exact fingerprint config on a new
  baseline.
- **`witness.ui.export`** — new pure-Python module: `diff_to_markdown`,
  `fingerprint_to_markdown`, `trace_to_markdown`, `preset_to_json /
  preset_from_json`. No streamlit dependency, importable from anywhere.
- **`witness.ui.components`** — extracted reusable widgets (`empty_state`,
  `confirm_button`, `search_input`, `filter_rows`, `decision_expander`,
  `decision_list`, `markdown_download`, `StatusPanel`).
- **Tests** — 96 → 132. Added `tests/test_ui_export.py`,
  `tests/test_ui_components.py`, and `tests/test_ui_apptest.py` (AppTest-based
  per-page render checks).

### Added (earlier in this Unreleased block)
- **Rich-powered terminal output** for `witness diff`, `witness fingerprint`, and
  `witness inspect`. Boxed panels, tables, color-coded change badges, stability
  bar charts. Auto-enabled when `rich` is installed; pass `--plain` for the
  legacy ANSI renderer. Available via `pip install "witness[rich]"` or
  `pip install "witness[ui]"`.
- **Streamlit web UI** (`witness ui`) — five-page interactive app:
  Load traces, Inspect, Diff, Perturb & Replay, Fingerprint. Run perturbations
  live in the browser, see diffs render with side-by-side panels, see stability
  bar charts. Available via `pip install "witness[ui]"`.
- `examples/ollama_research_agent.py` — end-to-end demo against a local Ollama
  model via the OpenAI adapter (no Ollama-specific code in the library).
- CLI auto-reconfigures stdout/stderr to UTF-8 on Windows so rich box-drawing
  characters render in cmd.exe and PowerShell 5.

## v0.1.0 — initial release

The MVP from `BUILD.md` (capture / perturb / diff), plus everything in the
"stretch" list except the web UI and trace-import integrations.

### Capture
- `@witness.observe()` decorator — sync + async, contextvar-based, bare and parameterized forms
- `witness.record_decision()` for manual instrumentation
- Anthropic SDK adapter — auto-records `messages.create` calls (sync + async)
- OpenAI SDK adapter — auto-records `chat.completions.create` calls (sync + async)
- Stable JSON trace schema (`trace_v1`) with forward-compat `extra="allow"`
  on every model
- Schema published as JSON Schema at `witness/schema/trace_v1.json`

### Perturb
- `Truncate(fraction=...)` — drop trailing N% of context
- `PromptInjection(text=...)` — append a hostile instruction
- `ModelSwap(target=...)` — replace the model identifier
- `ToolRemoval(tool=...)` — remove a tool from `tools_available`
- `witness.replay_context()` — agents can honor model/tool overrides during replay
- `witness.replay()` — programmatic counterfactual replay with auto-save suppression

### Diff
- LCS-based decision alignment with `same` / `input_changed` / `output_changed` / `both_changed` / `added` / `removed` / `type_changed` classification
- Color-coded terminal renderer
- `witness.diff.fingerprint()` — N-perturbation behavioral signature
  with stability scores per decision type and an overall (geometric-mean) score

### CLI
- `witness diff baseline.json perturbed.json` (color or `--json`, `-v` for verbose)
- `witness perturb baseline.json --type ... --param k=v -o ...` (with optional `--no-rerun` snapshot mode)
- `witness inspect <trace>` — pretty summary of a trace
- `witness perturbations` — list registered perturbation types
- `witness fingerprint baseline.json --run truncate:fraction=0.25 --run prompt_injection`
- `witness schema [--regenerate|--path]`

### Tests
- 96 unit tests covering schema, store, capture, perturbations, diff, replay, fingerprint, schema export, CLI, and end-to-end demo flow
- Integration test suite (`tests/integration/`) gated on `RUN_INTEGRATION=1`
  with real Anthropic API call

### Docs
- README with the gap framing, CLI flow, perturbation table, JSON Schema location
- This changelog
- LICENSE (MIT)
