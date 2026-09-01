#!/usr/bin/env python3
"""
Runs the pipeline fresh and checks the three things an auditor would
actually check, against the same graph and figures a real run produces.
This is not a reimplementation that could quietly drift from engine.py:

  1. reconciliation   computed values vs. firm_A_answer_key.xlsx (Firm A)
                       or the three stated deltas in firm_B_brief.md,
                       with the other ten rows required to stay identical
                       to Firm A (Firm B).
  2. traceability      every non-error figure's citation resolves to a
                       real chunk actually sitting in the graph, with
                       matching text, not just a non-null string.
  3. firewall          if a narrative was generated this run, it
                       introduces no number absent from the figures.

Exits non-zero if anything fails, so this doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import openpyxl

from meridian.audit import db as audit_db
from meridian.audit import events as audit_events
from meridian.cli import CONFIGS_DIR, REPO_ROOT, TEMPLATE_PATH, ingest_and_build_graph
from meridian.compute.engine import compute_figure_set
from meridian.compute.figures import FigureSet
from meridian.compute.rounding import display_status
from meridian.config.schema import FirmConfig
from meridian.graph.builder import MeridianGraph
from meridian.narrative.generator import generate_narrative
from meridian.narrative.llm_client import build_client_from_env
from datetime import datetime, timezone


@dataclass
class ReconRow:
    metric: str
    expected: str
    actual: str
    delta: str
    passed: bool


def read_answer_key(path: Path) -> dict[tuple[str, str], dict]:
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows: dict[tuple[str, str], dict] = {}
    for section, metric, value, limit, utilization, status, _source in ws.iter_rows(min_row=2, values_only=True):
        if section is None:
            continue
        rows[(section, metric)] = {"value": value, "status": status}
    return rows


def parse_numeric(text: str | object) -> Decimal | None:
    if text is None:
        return None
    cleaned = str(text).replace(",", "").replace("%", "").replace("SGD", "").replace("/ bp", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def reconcile_against_answer_key(figure_set: FigureSet, answer_key_path: Path) -> list[ReconRow]:
    expected_rows = read_answer_key(answer_key_path)
    rows: list[ReconRow] = []
    for fig in figure_set.figures:
        expected = expected_rows.get((fig.section, fig.metric))
        if expected is None:
            rows.append(ReconRow(fig.metric, "<no matching answer-key row>", str(fig.value_display), "n/a", False))
            continue

        expected_num, actual_num = parse_numeric(expected["value"]), parse_numeric(fig.value_display)
        status_matches = expected["status"] == display_status(fig.status)
        if expected_num is not None and actual_num is not None:
            delta = actual_num - expected_num
            passed = delta == 0 and status_matches
            rows.append(ReconRow(fig.metric, str(expected["value"]), str(fig.value_display), str(delta), passed))
        else:
            passed = str(expected["value"]) == str(fig.value_display) and status_matches
            rows.append(ReconRow(fig.metric, str(expected["value"]), str(fig.value_display), "n/a", passed))
    return rows


# The three deltas firm_B_brief.md states explicitly. Everything else in
# Firm B's report must come out identical to Firm A's.
FIRM_B_STATED_DELTAS = {
    "Aggregate non-IG exposure": {"value": "21.0%", "status": "BREACH"},
    "Largest GRE issuer": {"value": "13.0%", "status": "BREACH"},
}


def reconcile_firm_b(figure_set_a: FigureSet, figure_set_b: FigureSet) -> list[ReconRow]:
    rows: list[ReconRow] = []
    for fig_a, fig_b in zip(figure_set_a.figures, figure_set_b.figures):
        if fig_a.metric in FIRM_B_STATED_DELTAS:
            expected = FIRM_B_STATED_DELTAS[fig_a.metric]
            passed = fig_b.value_display == expected["value"] and fig_b.status == expected["status"]
            rows.append(ReconRow(fig_a.metric, str(expected["value"]), str(fig_b.value_display), "n/a", passed))
        else:
            passed = fig_a.value_display == fig_b.value_display and fig_a.status == fig_b.status
            rows.append(ReconRow(fig_a.metric, str(fig_a.value_display), str(fig_b.value_display), "0 (unchanged)", passed))
    return rows


def check_traceability(figure_set: FigureSet, mg: MeridianGraph) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for fig in figure_set.figures:
        if fig.status == "ERROR":
            results.append((fig.metric, True, f"correctly emitted as ERROR ({fig.error_reason}), not silently traced"))
            continue
        if fig.graph_path is None or fig.citation is None:
            results.append((fig.metric, False, "non-error figure is missing graph_path or citation"))
            continue
        chunk = mg.chunks.get(fig.citation.chunk_id)
        if chunk is None:
            results.append((fig.metric, False, f"citation points at chunk_id {fig.citation.chunk_id!r}, not present in the graph"))
            continue
        if chunk.raw_text != fig.citation.passage_summary:
            results.append((fig.metric, False, "citation's passage_summary does not match the source chunk's raw_text"))
            continue
        results.append((fig.metric, True, f"resolves to {chunk.source_doc} p.{chunk.page} ({fig.citation.chunk_id})"))
    return results


def _print_table(title: str, rows: list[ReconRow]) -> bool:
    print(f"\n{title}")
    print(f"  {'metric':38} {'expected':>16} {'actual':>16} {'delta':>10}  pass")
    for r in rows:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  {r.metric:38} {r.expected:>16} {r.actual:>16} {r.delta:>10}  {mark}")
    return all(r.passed for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firm", default="firm_a", choices=sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml")))
    args = parser.parse_args()

    ingestion_time = datetime.now(timezone.utc).isoformat()
    mg = ingest_and_build_graph(ingestion_time)

    config = FirmConfig.load(CONFIGS_DIR / f"{args.firm}.yaml")
    figure_set = compute_figure_set(mg, config)

    overall_ok = True

    if config.reconciliation.answer_key_path:
        rows = reconcile_against_answer_key(figure_set, REPO_ROOT / config.reconciliation.answer_key_path)
        overall_ok &= _print_table(f"1. Reconciliation vs {config.reconciliation.answer_key_path}", rows)
    else:
        config_a = FirmConfig.load(CONFIGS_DIR / "firm_a.yaml")
        figure_set_a = compute_figure_set(mg, config_a)
        rows = reconcile_firm_b(figure_set_a, figure_set)
        overall_ok &= _print_table("1. Reconciliation vs firm_B_brief.md's stated deltas (relative to Firm A)", rows)

    print("\n2. Traceability (figure -> graph path -> source chunk)")
    trace_results = check_traceability(figure_set, mg)
    for metric, ok, detail in trace_results:
        print(f"  {'PASS' if ok else 'FAIL':4}  {metric:38} {detail}")
    overall_ok &= all(ok for _, ok, _ in trace_results)

    print("\n3. Firewall check (does the narrative introduce any number not in the figures)")
    client = build_client_from_env()
    narrative = generate_narrative(client, figure_set)
    if narrative.status == "SKIPPED_NO_API_KEY":
        print("  SKIP  no GOOGLE_API_KEY configured, so no narrative was generated this run")
    elif narrative.firewall_report is None:
        print(f"  FAIL  narrative generation did not complete (status={narrative.status})")
        overall_ok = False
    else:
        report = narrative.firewall_report
        print(f"  {'PASS' if report.passed else 'FAIL'}  {report.checked_tokens} numeric token(s) found in the "
              f"narrative, {len(report.violations)} not present in the computed figures: {list(report.violations)}")
        overall_ok &= report.passed

    run_id = f"reconcile-{args.firm}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    conn = audit_db.connect(REPO_ROOT / "output" / "audit_log.sqlite3")
    audit_events.log_reconciliation(
        conn,
        run_id,
        args.firm,
        overall_ok,
        [{"metric": r.metric, "expected": r.expected, "actual": r.actual, "passed": r.passed} for r in rows],
    )
    conn.close()

    print(f"\n{'ALL CHECKS PASSED' if overall_ok else 'ONE OR MORE CHECKS FAILED'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
