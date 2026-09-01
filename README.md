# Meridian compliance report system

A system that turns a fund's investment guidelines (PDF) and a holdings snapshot (CSV) into a MAS-style
compliance report, where every number can be traced back through a knowledge graph to the exact sentence or
table row it came from, and the language model is never allowed to touch a number. It may only write the
narrative commentary around them.

The five hard constraints it targets, reproducibility, graph-based traceability, an LLM firewall,
reconciliation to an answer key, and config-only reconfiguration to a second firm's conventions, are
covered in detail in `docs/03_rfc.md`.

## Run it

Requires Python 3.10 or newer. Tested on macOS and Ubuntu (22.04 and 24.04), against Python 3.10, 3.11,
3.12, and 3.13. Not tested on Windows; development happened on macOS, so macOS and Ubuntu are what's actually
verified. The code itself has nothing OS-specific in it (just `pathlib` and `sqlite3`), so it should work on
Windows too, but "should" isn't the same claim as "tested" and I want to be upfront about the difference.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_report.py
```

The venv step isn't optional busywork: on a Homebrew Python (Mac) or most current Linux distributions, a
plain `pip install` outside a virtual environment is refused outright (PEP 668,
"externally-managed-environment"). Creating the venv first sidesteps that entirely, and it's the right way
to install project dependencies anyway.

Running it produces Firm A's report at `output/report_firm_a.xlsx`, the raw computed figures at
`output/figures_firm_a.json`, a graph review note at `output/graph_review_<run_id>.md`, and an append-only
audit trail at `output/audit_log.sqlite3`.

To get Firm B's report instead, same engine, no code changed, just a different config:

```
python scripts/run_report.py --firm firm_b
```

### Narrative commentary (optional)

The report is complete without this. Narrative is commentary, not a number. To get it:

```
cp .env.example .env
# edit .env: GOOGLE_API_KEY=<a free key from https://aistudio.google.com/app/apikey>
python scripts/run_report.py
```

Without a key, the run still produces the full report. `narrative` in the console output shows
`SKIPPED_NO_API_KEY`, and that's recorded in the audit log too, not silently skipped.

### Checking the work

```
pip install -r requirements-dev.txt
pytest                                    # 37 tests: determinism, config-switch, firewall,
                                           # traceability, module boundaries, audit log, reconciliation,
                                           # replay viewer, config DSL

python scripts/reconcile.py --firm firm_a # reconciles against firm_A_answer_key.xlsx
python scripts/reconcile.py --firm firm_b # reconciles against firm_B_brief.md's stated deltas
                                           # (both also re-verify traceability and the firewall)

python scripts/verify_audit_chain.py      # independently re-checks the audit log's hash chain
```

### Extras: replay viewer and config live preview

`scripts/replay.py` shows exactly how one figure was produced: its graph path, its source passage, which
config field decided it, and its delta against the answer key or against Firm A.

```
python scripts/replay.py --firm firm_a                                    # lists every figure id
python scripts/replay.py --firm firm_b --figure aggregate_non_ig_exposure # full replay of one
```

`scripts/config_preview.py` is a small REPL around a one-line config DSL (grammar in
`src/meridian/config/dsl.py`). Type a firm's method, see all 13 figures recompute immediately, nothing
written to disk.

```
python scripts/config_preview.py
> gre=parent_issuer fallen_angels=on util=bps
```

### The graph review gate

Every run writes `output/graph_review_<run_id>.md`, listing which extracted facts needed a human look (see
`docs/01_flow_and_audit_events.md` for the auto-pass criterion). By default the run proceeds anyway and logs
that it did. To see the gate actually block:

```
python scripts/run_report.py --strict-review          # stops, tells you to review and re-run
python scripts/run_report.py --approve-graph           # records an explicit human sign-off, proceeds
```

## Layout

```
sample_docs/          the five source files this system was built against, unmodified
configs/               firm_a.yaml / firm_b.yaml, the only thing that differs between the two firms
docs/                  the three design documents
src/meridian/
  ingestion/            PDF + CSV -> cited facts (pdf_ingest.py, csv_ingest.py, review_gate.py)
  graph/                the knowledge graph itself (builder.py, queries.py, paths.py)
  compute/              every report figure; never imports narrative/ (see tests/test_module_boundaries.py)
  narrative/            the LLM layer; only ever sees a finished FigureSet (llm_client.py, firewall.py)
  audit/                the append-only SQLite log
  reporting/            fills report_template.xlsx from a FigureSet
  replay/                explains one figure's graph path, source, and config rule (viewer.py)
scripts/                run_report.py, reconcile.py, verify_audit_chain.py: the actual entrypoints
                        replay.py, config_preview.py: two small extras on top
tests/                  pytest suite backing every claim in docs/03_rfc.md
```

## What I'd want to add for production

Covered honestly at the end of `docs/03_rfc.md`: auth on the audit log, real secrets management, handling a
guidelines document whose layout changes between versions, retry/backoff around the LLM call, and a review
gate that blocks by default instead of warning by default.
