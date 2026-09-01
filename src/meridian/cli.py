"""
Wires every layer into one run: ingest -> build graph -> review gate ->
compute -> narrative -> write report -> audit log. scripts/run_report.py is
just an argparse shell around run_report() below; this is where the actual
pipeline order lives, so it's testable without going through a subprocess.

On the review gate default: in a real production deployment this would
default to --strict-review, blocking on anything a human hasn't signed off
on. For this submission, the default is auto-approve so the one documented
start command (`python scripts/run_report.py`) produces a complete run
without a second interactive step. The gate is still fully real, though;
--strict-review demonstrates it blocking. See docs/03_rfc.md.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from meridian.audit import db as audit_db
from meridian.audit import events as audit_events
from meridian.compute.engine import compute_figure_set
from meridian.compute.figures import FigureSet
from meridian.config.schema import FirmConfig
from meridian.graph.builder import MeridianGraph, build_graph
from meridian.ingestion.csv_ingest import load_holdings
from meridian.ingestion.pdf_ingest import parse_guidelines
from meridian.ingestion.review_gate import GraphReviewReport, build_review_report, render_review_markdown
from meridian.narrative.generator import NarrativeResult, generate_narrative
from meridian.narrative.llm_client import build_client_from_env
from meridian.narrative.prompt import build_prompt
from meridian.reporting.xlsx_writer import write_report

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDELINES_PATH = REPO_ROOT / "sample_docs" / "sample_fund_guidelines.pdf"
HOLDINGS_PATH = REPO_ROOT / "sample_docs" / "sample_holdings.csv"
TEMPLATE_PATH = REPO_ROOT / "sample_docs" / "report_template.xlsx"
CONFIGS_DIR = REPO_ROOT / "configs"


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    firm_id: str
    blocked: bool
    review_report: GraphReviewReport
    figure_set: FigureSet | None = None
    figures_path: Path | None = None
    report_path: Path | None = None
    narrative: NarrativeResult | None = None


def ingest_and_build_graph(ingestion_time: str) -> MeridianGraph:
    guidelines = parse_guidelines(GUIDELINES_PATH, ingestion_time)
    positions = load_holdings(HOLDINGS_PATH, ingestion_time)
    return build_graph(guidelines, positions)


def run_report(
    firm_id: str,
    *,
    strict_review: bool = False,
    approve_graph: bool = False,
    output_dir: Path | None = None,
    audit_db_path: Path | None = None,
) -> RunOutcome:
    output_dir = output_dir or (REPO_ROOT / "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_db_path = audit_db_path or (output_dir / "audit_log.sqlite3")

    run_id = f"{firm_id}-{uuid.uuid4().hex[:8]}"
    ingestion_time = datetime.now(timezone.utc).isoformat()
    conn = audit_db.connect(audit_db_path)

    config = FirmConfig.load(CONFIGS_DIR / f"{firm_id}.yaml")
    audit_events.log_config_change(conn, run_id, config.firm_id, config.content_hash(), config.model_dump(mode="json"))

    mg = ingest_and_build_graph(ingestion_time)
    audit_events.log_graph_construction(conn, run_id, mg)

    review = build_review_report(mg.all_chunks())
    (output_dir / f"graph_review_{run_id}.md").write_text(
        render_review_markdown(review, run_id, firm_id), encoding="utf-8"
    )

    if review.clean:
        audit_events.log_graph_reviewed(conn, run_id, review, "approved", actor="system (nothing flagged)")
    elif approve_graph:
        audit_events.log_graph_reviewed(conn, run_id, review, "approved", actor="human (--approve-graph)")
    elif strict_review:
        audit_events.log_graph_reviewed(conn, run_id, review, "blocked", actor="system (--strict-review)")
        conn.close()
        return RunOutcome(run_id, firm_id, blocked=True, review_report=review)
    else:
        audit_events.log_graph_reviewed(conn, run_id, review, "auto_approved", actor="system (default)")

    figure_set = compute_figure_set(mg, config)
    audit_events.log_figure_computation(conn, run_id, firm_id, figure_set)

    figures_path = output_dir / f"figures_{firm_id}.json"
    figures_path.write_text(json.dumps(figure_set.to_dict(), indent=2), encoding="utf-8")

    client = build_client_from_env()
    narrative = generate_narrative(client, figure_set)
    if narrative.text is not None:
        prompt_hash = hashlib.sha256(build_prompt(figure_set).encode("utf-8")).hexdigest()
        audit_events.log_narrative_generated(
            conn, run_id, firm_id, narrative.model_name or "", prompt_hash, narrative.text, narrative.status
        )
        (output_dir / f"narrative_{firm_id}.txt").write_text(narrative.text, encoding="utf-8")
    if narrative.firewall_report is not None:
        audit_events.log_firewall_check(
            conn, run_id, firm_id, narrative.firewall_report.passed, list(narrative.firewall_report.violations)
        )

    report_path = output_dir / f"report_{firm_id}.xlsx"
    write_report(TEMPLATE_PATH, report_path, figure_set)
    file_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    audit_events.log_export(conn, run_id, firm_id, str(report_path), file_hash)

    conn.close()
    return RunOutcome(
        run_id,
        firm_id,
        blocked=False,
        review_report=review,
        figure_set=figure_set,
        figures_path=figures_path,
        report_path=report_path,
        narrative=narrative,
    )
