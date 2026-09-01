"""Constraint 4: the computed report has to reconcile to Firm A's answer key, every row."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reconcile import reconcile_against_answer_key  # noqa: E402

from meridian.compute.engine import compute_figure_set

ANSWER_KEY = Path(__file__).resolve().parent.parent / "sample_docs" / "firm_A_answer_key.xlsx"


def test_all_thirteen_figures_reconcile_exactly(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    rows = reconcile_against_answer_key(figures, ANSWER_KEY)

    assert len(rows) == 13
    failures = [r for r in rows if not r.passed]
    assert not failures, [(r.metric, r.expected, r.actual) for r in failures]
