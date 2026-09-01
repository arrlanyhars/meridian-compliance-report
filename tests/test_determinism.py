"""Constraint 1: the same inputs must produce byte-identical figures."""

import json

from meridian.compute.engine import compute_figure_set


def test_rerun_produces_identical_figure_json(meridian_graph, firm_a_config):
    first = json.dumps(compute_figure_set(meridian_graph, firm_a_config).to_dict(), sort_keys=True)
    second = json.dumps(compute_figure_set(meridian_graph, firm_a_config).to_dict(), sort_keys=True)
    assert first == second


def test_rebuilding_the_graph_from_scratch_still_matches(meridian_graph, firm_a_config):
    """
    Not just "the same graph object computed twice". Rebuilding the graph
    from the source files again (a fresh ingestion pass) has to land on the
    same figures too, since that's what a real rerun of the pipeline does.
    """
    from datetime import datetime, timezone
    from pathlib import Path

    from meridian.graph.builder import build_graph
    from meridian.ingestion.csv_ingest import load_holdings
    from meridian.ingestion.pdf_ingest import parse_guidelines

    sample_docs = Path(__file__).resolve().parent.parent / "sample_docs"
    now = datetime.now(timezone.utc).isoformat()
    guidelines = parse_guidelines(sample_docs / "sample_fund_guidelines.pdf", now)
    positions = load_holdings(sample_docs / "sample_holdings.csv", now)
    rebuilt_graph = build_graph(guidelines, positions)

    original = json.dumps(compute_figure_set(meridian_graph, firm_a_config).to_dict(), sort_keys=True)
    rebuilt = json.dumps(compute_figure_set(rebuilt_graph, firm_a_config).to_dict(), sort_keys=True)
    assert original == rebuilt
