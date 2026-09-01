# Reporting flow and audit events

## AS-IS: how this report gets made today

An analyst opens `sample_fund_guidelines.pdf`, reads the limits section, and copies the numbers into a
spreadsheet by hand. They open the holdings snapshot, sum up market values per asset class, and type the
allocation percentages next to the limits. They do the same for the aggregate non-IG check, the two
concentration checks, liquidity, duration, and DV01: thirteen numbers, thirteen small manual steps, each one
a place to mistype a cell reference or copy last month's formula into this month's row.

The report goes out. Nobody but the analyst knows exactly which cell pulled from which page of the PDF, and
that knowledge lives in one person's head and one spreadsheet's formula bar. When an examiner later asks
"where did this 47.0% liquidity figure come from", the honest answer is "let me open the file and trace it
back", which is exactly the situation Section 5.1 of the guidelines document says isn't good enough
("every data point... must be traceable to its originating system or document").

## TO-BE: what this system does instead

```
 1. INGEST            sample_fund_guidelines.pdf + sample_holdings.csv
    (automatic)        parsed into dated, cited facts (see docs/03_rfc.md, "ingestion")

 2. BUILD GRAPH        facts assembled into one knowledge graph
    (automatic)        every node/edge carries source_doc, page, chunk_id, confidence

          |
          v
 3. REVIEW GATE  <---  a human checks anything the parser wasn't confident about
    (human, conditional)

          |
          v
 4. COMPUTE            13 figures, each traversed from the graph, each carrying a
    (automatic)         graph_path and a citation. No figure is invented, rounded,
                         or adjusted by a person at this step. That's the point.

          |
          v
 5. NARRATIVE          a short commentary paragraph, generated from the already
    (automatic,         computed figures only, then checked against them
    LLM-assisted)

          |
          v
 6. RECONCILE          computed output checked against the answer key or stated
    (automatic)         deltas, traceability re-verified, narrative re-checked

          |
          v
 7. EXPORT             report_<firm>.xlsx written, hashed, logged
    (automatic)
```

Steps 1, 2, 4, 5, 6 and 7 run without a person in the loop, which is what makes the system reproducible
(constraint 1). Step 3 is the one place a human is asked to look, and only conditionally.

### The review gate (step 3)

Entity and relationship extraction from a PDF is genuinely error-prone. This system hits a real example of
that itself: one row of the risk metrics table (`Interest Rate Sensitivity`) doesn't extract cleanly because
two columns overlap in the PDF's text layout (see `src/meridian/ingestion/pdf_ingest.py`, the
`interest_rate_sensitivity` case). Rather than guess at what that row says, the system flags it.

The auto-pass criterion is mechanical, not a judgment call made per document:

- A fact auto-passes if it came from a **deterministic parse** (a table row or a CSV row matched its
  expected shape exactly) **and** its confidence is at least 0.90.
- A fact extracted from **free-form prose** (the single-issuer cap, the GRE cap, the liquidity floors,
  anything pulled out of a sentence rather than a table cell) always goes to review, regardless of
  confidence. A regex can match confidently on the wrong sentence; a malformed table cell usually just
  fails to parse at all. Those are different risk profiles and get different treatment.
- Anything that failed to parse outright (confidence 0.0, like the interest-rate-sensitivity row above)
  always goes to review.

On the sample documents, this comes out to 25 of 31 extracted facts auto-passing and 6 needing a human look
(5 prose facts plus the 1 failed table row). Run `python scripts/run_report.py --firm firm_a` and check
`output/graph_review_<run_id>.md` to see the actual list.

In a production deployment, this gate would block by default (`--strict-review`) until someone runs
`--approve-graph`. For this submission's single documented start command to produce a complete run without a
second interactive step, the default is to proceed with a warning and log `graph_reviewed` with
`actor="system (default)"`. The distinction between what needed a human and what didn't is still fully
computed and logged either way; it's just not blocking by default. See `docs/03_rfc.md` for why.

## Audit event catalogue

Retention periods are taken directly from the guidelines document itself (Section 5.1: "a minimum of 7
years for transaction data and 10 years for investor-facing reports"). Every event is a row in the
`audit_events` SQLite table (`src/meridian/audit/db.py`), which the database itself refuses to UPDATE or
DELETE after insert, chained by a SHA-256 hash so a raw file edit that bypassed the database entirely would
still show up as a broken chain when replayed (`scripts/verify_audit_chain.py`).

| Event                 | Trigger                                      | Data captured                                                                 | Retention |
|------------------------|-----------------------------------------------|--------------------------------------------------------------------------------|-----------|
| `graph_construction`   | Ingestion finishes assembling the graph       | node/edge counts by type, source documents ingested                            | 7 years   |
| `graph_reviewed`       | The review gate resolves (auto or manual)     | decision, actor, which chunks needed review, how many auto-passed              | 7 years   |
| `config_change`        | A run starts, config is loaded                | firm_id, a hash of the config content, the full config payload                 | 7 years   |
| `figure_computation`   | Each of the 13 figures is computed            | figure id, value, status, graph_path, the chunk_id it cites                    | 7 years   |
| `narrative_generated`  | The LLM call returns (or is skipped)          | model name, a hash of the prompt, the narrative text, firewall status          | 10 years  |
| `firewall_check`       | The narrative is checked against the figures  | pass/fail, list of any numbers found that weren't in the figures               | 10 years  |
| `reconciliation`       | `scripts/reconcile.py` runs                   | pass/fail per figure, expected vs. actual, overall result                      | 10 years  |
| `export`               | `report_<firm>.xlsx` is written               | output path, a SHA-256 hash of the written file                                | 10 years  |

## The LLM / deterministic boundary

Stated plainly, because it's the part an examiner would push on hardest: **the language model never sees a
source document, and it never sees the graph.** It sees exactly one thing: a list of already-computed,
already-rounded figures (value, limit, status), and its only job is to write 2 to 4 sentences of commentary
about them. `src/meridian/compute/engine.py` and everything it calls has no import path to
`src/meridian/narrative/` at all (checked by `tests/test_module_boundaries.py`, not just asserted in prose),
and the figures are written to `output/figures_<firm>.json` before the narrative step ever runs. See
`docs/03_rfc.md` for how this is verified at runtime, not just prevented structurally.
