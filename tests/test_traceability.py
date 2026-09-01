"""
Constraint 2: figure -> graph path -> source chunk has to be a real,
checkable path, not just a citation object that looks plausible. The
negative case here (a citation pointing at a chunk_id that doesn't exist)
is what proves check_traceability is an actual check and not a rubber stamp.
If it can't fail on bad input, it can't be trusted on good input either.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reconcile import check_traceability  # noqa: E402

from meridian.compute.engine import compute_figure_set
from meridian.compute.figures import Figure
from meridian.graph.queries import Citation


def test_every_real_figure_traces_to_a_chunk_actually_in_the_graph(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    results = check_traceability(figures, meridian_graph)
    failures = [(metric, detail) for metric, ok, detail in results if not ok]
    assert not failures, failures


def test_a_citation_pointing_at_a_nonexistent_chunk_is_caught(meridian_graph, firm_a_config):
    real_figure = compute_figure_set(meridian_graph, firm_a_config).figures[0]
    tampered = Figure(
        figure_id=real_figure.figure_id,
        section=real_figure.section,
        metric=real_figure.metric,
        status=real_figure.status,
        value_display=real_figure.value_display,
        limit_display=real_figure.limit_display,
        utilization_display=real_figure.utilization_display,
        graph_path=real_figure.graph_path,
        citation=Citation(
            source_doc="sample_fund_guidelines.pdf",
            page=1,
            chunk_id="this-chunk-id-does-not-exist-in-the-graph",
            passage_summary="a passage that was never actually extracted",
        ),
    )
    from meridian.compute.figures import FigureSet

    tampered_set = FigureSet(firm_id="firm_a", firm_name="Firm A", figures=(tampered,))
    results = check_traceability(tampered_set, meridian_graph)
    metric, ok, detail = results[0]
    assert not ok
    assert "not present in the graph" in detail


def test_an_error_figure_is_treated_as_correctly_untraceable_not_a_failure():
    from meridian.compute.figures import FigureSet, error_figure

    error_set = FigureSet(
        firm_id="firm_a",
        firm_name="Firm A",
        figures=(error_figure("some_figure", "Allocation", "Some Metric", "no SOURCED_FROM edge"),),
    )

    class _EmptyGraph:
        chunks: dict = {}

    results = check_traceability(error_set, _EmptyGraph())
    metric, ok, detail = results[0]
    assert ok  # an ERROR figure is the correct, honest outcome here, not a defect
