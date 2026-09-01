# RFC: Meridian compliance report system

## What this is for

The spec for this system sets five hard constraints and treats them as the whole point, which they are. This
memo explains the architecture that comes out of taking those constraints literally, and defends the
handful of judgment calls I had to make where the spec states a requirement but not a mechanism. I'm
writing this after the system was built and tested against both answer keys, not as a plan I hoped would
work. Every claim below is something I ran and checked, and I say where in the code to look.

## Constraint 3: the LLM cannot be the source of any reported number

This is the constraint I designed around first, because it's the one a clever-looking shortcut could quietly
violate. Two separate mechanisms back it, and they check different things.

**Structural: the LLM has no way to reach a number even if it wanted to.** `src/meridian/compute/engine.py`
and everything under `compute/` produces a frozen `FigureSet`, rounded, formatted, immutable, and writes it
to `output/figures_<firm>.json` before `cli.py` ever calls into `narrative/`. The narrative layer's
`prompt.py` builds its prompt from that already-serialized `FigureSet` and nothing else: not the graph, not
the CSV, not a `Decimal`. There's no code path from `narrative/` back into `compute/`, and I didn't just
decide not to write one. `tests/test_module_boundaries.py` parses the AST of every file under `compute/` and
`graph/` and fails if any of them imports `meridian.narrative` or `google.generativeai`. That test is the
actual guarantee; this paragraph is just describing what it checks.

**Runtime: a firewall that would catch it if the structural guarantee ever broke anyway.**
`compute/engine.py`'s figures expose a "numeric surface", every digit that appears in any figure's formatted
value, limit, or utilization. `narrative/firewall.py` tokenizes whatever the LLM wrote and flags any number
in it that isn't in that surface. If the model fabricates a number (I tested this with a stub client that
always answers "Estimated VaR is 3.2% this quarter", see
`tests/test_firewall.py::test_narrative_with_a_fabricated_number_is_caught`), the generator retries once
with the offending number named, and if it still fails, the run reports `FIREWALL_FAILED` and emits no
narrative at all, rather than quietly dropping the bad sentence. `scripts/reconcile.py`'s step 3 re-runs
this check against whatever narrative the actual report run produced, so it's verified on every run, not
just in a test.

The two mechanisms matter together. The structural one is what makes constraint 3 true by construction, and
the firewall is what makes it possible to *prove* to an auditor that it held, on this specific run, without
them having to read the source code.

## Constraint 2: a figure traces through the graph to its source

Every one of the 13 figures is computed by calling into `graph/queries.py`, functions like
`positions_belonging_to`, `asset_classes_contributing_to`, and `issuers_subject_to`, never by reading
`sample_holdings.csv` or the PDF text directly from a compute module. That's deliberate: if a compute
function could bypass the graph and read the source file itself, the graph would be decoration: it would
look compliant with constraint 2 without actually being load-bearing, which is worse than not having a
graph at all, since it hides the gap instead of making it obvious.

Concretely, `Figure.graph_path` is a string built from the same node ids the graph actually uses (every node
id is already `Type:slug`, so wrapping it in parens is the entire rendering step, see `graph/paths.py`), and
`Figure.citation` comes from `queries.citation_for()`, which walks a real `SOURCED_FROM` edge to a
`SourceChunk` node and reads its `raw_text` back. `scripts/reconcile.py`'s step 2 independently re-checks
this for every figure in a real run: it looks up the cited `chunk_id` in the graph's own chunk registry and
confirms the text matches, rather than trusting the citation object at face value. I also wrote the negative
case deliberately
(`tests/test_traceability.py::test_a_citation_pointing_at_a_nonexistent_chunk_is_caught`): a citation with a
bogus `chunk_id` gets flagged, which is what proves the check can fail, not just pass.

Every node and every edge carries its own provenance (`source_doc`, `page`, `chunk_id`, `ingestion_time`,
`extraction_confidence`) as attributes, not only the fact nodes, but the relationships between them too
(`BELONGS_TO`, `CONTRIBUTES_TO`, `CHILD_OF`, and so on all carry it, copied from whichever chunk asserted
that relationship). That's a deliberately more literal reading of "every node and every edge carries
provenance" than the minimum needed to make citations work. A `SOURCED_FROM` edge to a chunk node alone
would satisfy the citation mechanism, but it wouldn't satisfy that requirement as written.

A figure that can't be traced is returned as an error, not silently emitted. None of the 13 figures in this
dataset actually hit that path (every asset class, risk metric, and limit parsed cleanly enough to get a
`SOURCED_FROM` edge), but the code path exists and is exercised by
`tests/test_traceability.py::test_an_error_figure_is_treated_as_correctly_untraceable_not_a_failure`.
`error_figure()` in `compute/figures.py` is the one place a `Figure` is allowed to have `status="ERROR"`,
`citation=None`, and no `graph_path`, and the dataclass's own `__post_init__` rejects any other combination.

## Constraint 5: a firm's method is config, not code

`configs/firm_a.yaml` and `configs/firm_b.yaml` are the entire difference between the two firms. Three
fields, matching the three conventions `firm_B_brief.md` states:

- `concentration.gre_grouping`: `issuer` or `parent_issuer`, whether the GRE concentration check groups
  Redhill Power and Redhill Transport separately or together under Redhill Holdings.
- `non_ig_aggregate.include_fallen_angels`: whether a downgraded holding still labeled "Investment Grade
  Corporate Bonds" (Marina Bay Resorts, rated BB) counts toward the non-IG aggregate anyway.
- `formatting.utilization_style`: `percent_1dp` or `truncated_bps`.

The graph itself is built once and is identical for both firms. `graph/builder.py` never reads a
`FirmConfig`. The Marina Bay Resorts fallen-angel edge
(`Position:COR-05 -[:CONTRIBUTES_TO {basis: fallen_angel_override}]-> Aggregate:non_ig_exposure`) is added
unconditionally, because "this position's current rating is below investment grade" is an objective fact
about the position, not a house convention. What varies is whether `compute/aggregate.py` walks edges of
that `basis` at all, which is one `if config.non_ig_aggregate.include_fallen_angels:` in
`compute/aggregate.py`, never a check on which firm is running. Same story for GRE grouping in
`compute/concentration.py` (`if grouping == GreGrouping.PARENT_ISSUER:`) and utilization formatting in
`compute/rounding.py::format_utilization`.

`tests/test_config_switch.py` computes both firms off the *same* graph object in the same test and asserts
that exactly the two figures named in `firm_B_brief.md` change (`Aggregate non-IG exposure`,
`Largest GRE issuer`), and nothing else. Running `python scripts/run_report.py --firm firm_a` and then
`python scripts/run_report.py --firm firm_b`, with no code edited in between, produces `report_firm_a.xlsx`
and `report_firm_b.xlsx` with exactly that difference.

## Constraint 4: reconciling to the answer key

`scripts/reconcile.py` reads `sample_docs/firm_A_answer_key.xlsx` directly and compares every row against
the freshly computed `FigureSet`, by `(section, metric)` rather than row position, so a reordered template
still lines up correctly. The tolerance is `status_epsilon_pct = 0` in both firm configs: exact Decimal
comparison, no fuzzing. I checked by hand before writing a line of compute code whether the sample data ever
needs slack. It doesn't: every value in the answer key is either clearly inside its limit, clearly outside
it, or landing exactly on it (the single-corporate-issuer row at exactly 8.0% against an 8% cap), so I
didn't build in tolerance that nothing exercises. The field exists in `FirmConfig.tolerance` for a firm
whose data does need it; it's just zero for both firms here, and documented as zero rather than left
implicit.

Firm B has no answer-key spreadsheet, only the three deltas stated in `firm_B_brief.md`'s own table.
`scripts/reconcile.py` checks those three explicitly and additionally asserts the other ten figures come out
byte-identical to the Firm A run, which is really a second, independent check of constraint 5 as much as
constraint 4. If Firm B's config accidentally changed something it wasn't supposed to change, this is what
would catch it.

All 13 figures reconcile exactly against `firm_A_answer_key.xlsx` (`tests/test_reconciliation.py`,
`python scripts/reconcile.py --firm firm_a`), and Firm B's three deltas plus ten unchanged rows both check
out (`python scripts/reconcile.py --firm firm_b`).

## Determinism

Every figure is computed in `Decimal`, never `float`. Rounding happens exactly once, in
`compute/rounding.py`, at the point a value is turned into a display string; nowhere else touches precision.
Every summation over a set of positions or asset classes sorts by node id first
(`sorted(q.positions_belonging_to(...))` and similar throughout `compute/`), so both the arithmetic and the
`graph_path` strings come out in the same order every time, not whatever order a dict or set iteration
happened to produce. `output/figures_<firm>.json` carries no timestamp or run id, only the audit log does,
so two runs' output files are directly diffable with no post-processing.
`tests/test_determinism.py` checks this two ways: running the same graph object twice, and rebuilding the
graph from the source files from scratch and computing again, both landing on byte-identical JSON.

## Judgment calls I made, and why

How to arrive at each of these was deliberately left open. Here's the record of what I decided and what
data (or lack of it) drove each one.

**Two dual-bound display rules extrapolated beyond what the sample data actually exercises.** The answer key
has exactly one case of an allocation row breaching a limit (Cash & Cash Equivalents, below its 5% floor),
and it displays as `Limit: min 5%`, `Utilization: n/a`. The range collapses to whichever single bound was
actually breached. I extended that symmetrically to a ceiling breach (untested by this dataset, since
nothing in the sample portfolio breaches an allocation ceiling) and applied the same min/max evaluation to
Portfolio Modified Duration, which is also a range limit. Portfolio Modified Duration keeps a different rule
for utilization specifically: it always shows `n/a`, breach or not, because "58% utilized" is a sentence
that means something for a percentage cap and doesn't mean anything for a multi-year duration window. That's
a semantic call, not something I inferred from the one duration row in the answer key (which happens to be
`OK` and also shows `n/a`, so the data was consistent with either interpretation).

**`AT_LIMIT` status uses a configurable epsilon, currently zero for both firms.** The one case that actually
exercises it (single corporate issuer at exactly 8.0% against an 8% cap) needs no tolerance at all.
`Decimal("8.0") == Decimal("8.0")` is exact. `FirmConfig.tolerance.status_epsilon_pct` exists so a firm
whose data genuinely needs a fuzzy boundary has somewhere to put it without an engine change, but I didn't
invent a nonzero default that nothing here would justify.

**PDF table extraction uses `page.extract_text()` plus targeted regexes, not `pdfplumber`'s
`extract_tables()`.** I tried the built-in table detector first. On this specific PDF it mangles cells:
`"Singapore Government Securities (SGS"` and `") 20%"` split into two cells, `"Monitoring Frequency"` and
`"Breach Action"` glued into one column. `extract_text()`, by contrast, comes out clean because the PDF's
underlying layout is a simple top-to-bottom text flow. For a small, fixed, known set of tables, six
row-shaped regexes are more maintainable and more correct than fighting a general table-detection heuristic
that doesn't fit this document. This wouldn't be the right call for an arbitrary PDF with a genuinely
irregular table layout; it's the right call for this one.

**Zero LLM calls anywhere in ingestion.** Every extracted fact's confidence comes from a hand-authored
heuristic (0.98 for a clean table row, 0.90 for a regex prose match, 1.0 for a CSV row, 0.0 for a parse that
outright failed) rather than a model's self-reported confidence. This was a deliberate trade against the
alternative (LLM-assisted extraction with model-reported confidence): it makes constraint 3's firewall
trivially airtight, since the model never sees a source document at all, and it keeps constraint 1's
reproducibility simple, since regex output doesn't vary run to run the way a model's output can. The cost is
that this ingestion approach is more brittle against a differently-formatted guidelines document than an
LLM-assisted extractor would be. That's acceptable here because the scope is the sample materials provided,
not an arbitrary future document.

**Every figure traverses the graph, including the two that are really just portfolio-wide sums (duration and
DV01).** I added a `CONTRIBUTES_TO {basis: portfolio_weighted}` edge from every `Position` to
`RiskMetric:modified_duration` and `RiskMetric:portfolio_dv01` specifically so these two figures have a real
edge to traverse rather than reaching into the graph's node list directly. This costs 26 extra edges for
figures that could otherwise be computed by iterating `Position` nodes directly. I judged that worth it: a
figure the graph doesn't actually touch defeats the point of building the graph at all, for the same reason
argued under constraint 2 above.

**Redhill Holdings is a synthesized node, not a row from any source file.** It never appears in the CSV or
the PDF. It's inferred from the `parent_issuer` column shared by Redhill Power and Redhill Transport's rows.
Its provenance points at both children's chunks rather than one canonical source, and it's flagged
`derived_from_children=True` so an auditor doesn't mistake it for a directly-sourced entity. I judged this
better than either inventing a fake source document for it or leaving GRE parent-issuer grouping unmodeled,
since Firm B's whole second convention depends on this node existing.

**No Docker, no Neo4j.** The knowledge graph is `networkx`, in-memory, rebuilt on every run; the audit log is
SQLite. Both are pure-Python dependencies with no external service to start. I made this call before writing
any compute code, weighing it against how much "starts reliably with zero setup friction" mattered relative
to everything else, and against the scope: this needed to prove the constraints hold, not be
production-grade infrastructure. A real Neo4j deployment would be a reasonable production evolution of this
system; it isn't a reasonable risk to take on an 84-node graph that has to start with a single
`pip install && python` command every time.

**A missing `GOOGLE_API_KEY` doesn't fail the run.** `narrative/llm_client.py::build_client_from_env`
returns `None` if the key isn't set, and `generate_narrative` treats that as `status="SKIPPED_NO_API_KEY"`.
The numeric report, the graph, and the audit log are all unaffected. Most of what actually matters here
(constraints 1, 2, 4, 5, the graph itself) has nothing to do with whether a narrative paragraph got written,
so I didn't want a missing free-tier API key to block the rest of the system from being usable.

## What I'd add for production that I didn't build here

No authentication or access control on the audit log or the report output: anyone who can run the script can
read and write `output/`. No secrets management beyond a `.env` file; a real deployment would use a proper
secrets store for `GOOGLE_API_KEY`. No handling for a guidelines document that changes structure between
versions (the ingestion layer is tuned to this specific PDF's layout, per the trade-off described above). No
retry or backoff around the Gemini API call beyond the two-attempt firewall retry loop; a production system
would want real handling for rate limits and transient failures. The review gate defaults to auto-approve
rather than blocking, for the reason explained in `docs/01_flow_and_audit_events.md`. A production
deployment should default the other way.

## Optional extras

Two small tools on top of the core system, both read-only over the existing engine, neither one computes
anything new.

**Reconciliation / replay viewer** (`scripts/replay.py`, `src/meridian/replay/viewer.py`). Given a figure id,
prints its value and status, its full `graph_path`, its source passage, which `FirmConfig` field actually
decided it (a small table in `viewer.py` maps the two config-dependent figures to their field, and every
figure shows `formatting.utilization_style` since that one applies universally), and its delta against the
answer key or against Firm A. It calls `compute_figure_set` on the same graph `run_report.py` uses, so it
can't introduce a number the real pipeline didn't already produce.

**Configuration mini-DSL with live preview** (`scripts/config_preview.py`, `src/meridian/config/dsl.py`). A
one-line grammar (`gre=issuer|parent_issuer fallen_angels=on|off util=percent|bps epsilon=<n>`) that parses
into a real `FirmConfig`, and a REPL that recomputes all 13 figures on every line typed, with nothing written
to disk. It's not a replacement for `configs/*.yaml`, that's still the only thing a real run reads; this
exists so someone exploring "what would happen if Firm C grouped GREs by parent but kept percent
formatting" doesn't have to hand-edit a YAML file and rerun the whole CLI for every guess.

Skipped a third option that was on the table: global/local retrieval for the narrative layer. It's also the
one most likely to create real tension with constraint 3: feeding the narrative layer more graph content
than a plain figure list, even as "context" rather than numbers, is exactly the kind of change that
deserves more scrutiny than an optional extra should get. Better to leave it out than build a version of it
I wouldn't trust.
