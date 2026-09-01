"""
Typed helpers over audit/db.py's raw insert_event, one function per event
type in the catalogue documented in docs/01_flow_and_audit_events.md. Kept
thin on purpose: each function's whole job is "shape this event's payload
correctly and give it a stable event_type string", nothing more.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from meridian.audit.db import insert_event
from meridian.compute.figures import FigureSet
from meridian.graph.builder import MeridianGraph
from meridian.ingestion.review_gate import GraphReviewReport


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_graph_construction(conn: sqlite3.Connection, run_id: str, mg: MeridianGraph) -> int:
    return insert_event(
        conn,
        "graph_construction",
        run_id,
        firm_id=None,  # the graph is built once, shared by both firms
        actor="system",
        timestamp_utc=now_iso(),
        payload={
            "node_count": mg.node_count,
            "edge_count": mg.edge_count,
            "counts_by_node_type": mg.counts_by_node_type(),
            "source_documents": sorted({c.source_doc for c in mg.all_chunks()}),
        },
    )


def log_graph_reviewed(conn: sqlite3.Connection, run_id: str, report: GraphReviewReport, decision: str, actor: str) -> int:
    return insert_event(
        conn,
        "graph_reviewed",
        run_id,
        firm_id=None,
        actor=actor,
        timestamp_utc=now_iso(),
        payload={
            "decision": decision,  # "approved" | "auto_approved"
            "total_chunks": report.total_chunks,
            "auto_passed": report.auto_passed,
            "items_needing_review": [item.chunk_id for item in report.needs_review],
        },
    )


def log_config_change(conn: sqlite3.Connection, run_id: str, firm_id: str, config_hash: str, config_payload: dict) -> int:
    return insert_event(
        conn,
        "config_change",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={"config_hash": config_hash, "config": config_payload},
    )


def log_figure_computation(conn: sqlite3.Connection, run_id: str, firm_id: str, figure_set: FigureSet) -> int:
    return insert_event(
        conn,
        "figure_computation",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={
            "figures": [
                {
                    "figure": f.figure_id,
                    "value": f.value_display,
                    "status": f.status,
                    "graph_path": f.graph_path,
                    "chunk_id": f.citation.chunk_id if f.citation else None,
                }
                for f in figure_set.figures
            ]
        },
    )


def log_narrative_generated(
    conn: sqlite3.Connection, run_id: str, firm_id: str, model: str, prompt_hash: str, narrative: str, firewall_status: str
) -> int:
    return insert_event(
        conn,
        "narrative_generated",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={
            "model": model,
            "prompt_hash": prompt_hash,
            "narrative": narrative,
            "firewall_status": firewall_status,
        },
    )


def log_firewall_check(conn: sqlite3.Connection, run_id: str, firm_id: str, passed: bool, violations: list[str]) -> int:
    return insert_event(
        conn,
        "firewall_check",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={"passed": passed, "violations": violations},
    )


def log_reconciliation(
    conn: sqlite3.Connection, run_id: str, firm_id: str, passed: bool, per_figure_results: list[dict]
) -> int:
    return insert_event(
        conn,
        "reconciliation",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={"passed": passed, "results": per_figure_results},
    )


def log_export(conn: sqlite3.Connection, run_id: str, firm_id: str, output_path: str, file_hash: str) -> int:
    return insert_event(
        conn,
        "export",
        run_id,
        firm_id=firm_id,
        actor="system",
        timestamp_utc=now_iso(),
        payload={"output_path": output_path, "file_hash": file_hash},
    )
