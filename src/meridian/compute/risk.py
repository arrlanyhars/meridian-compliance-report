from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import networkx as nx

from meridian.compute.figures import Figure, error_figure
from meridian.compute.rounding import evaluate_range_status, evaluate_status, format_utilization, pct
from meridian.config.schema import UtilizationStyle
from meridian.domain import REPORT_METRIC_LABELS, REPORT_SECTIONS
from meridian.graph import queries as q
from meridian.graph.builder import PORTFOLIO_RISK_METRIC_IDS
from meridian.graph.paths import converging

_DURATION_FIGURE_ID = "portfolio_modified_duration"
_DV01_FIGURE_ID = "portfolio_dv01"
_DURATION_METRIC_ID, _DV01_METRIC_ID = PORTFOLIO_RISK_METRIC_IDS

_TWO_DP = Decimal("0.01")


def _weighted_duration_sum(g: nx.MultiDiGraph, position_ids: list[str]) -> Decimal:
    return sum(
        (g.nodes[p]["market_value_sgd"] * g.nodes[p]["modified_duration"] for p in position_ids),
        Decimal(0),
    )


def compute_duration_figure(g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal) -> Figure:
    section, metric = REPORT_SECTIONS[_DURATION_FIGURE_ID], REPORT_METRIC_LABELS[_DURATION_FIGURE_ID]
    citation = q.citation_for(g, _DURATION_METRIC_ID)
    if citation is None:
        return error_figure(_DURATION_FIGURE_ID, section, metric, f"{_DURATION_METRIC_ID} has no SOURCED_FROM edge")

    node = g.nodes[_DURATION_METRIC_ID]
    position_ids = sorted(q.positions_contributing_to(g, _DURATION_METRIC_ID, basis="portfolio_weighted"))
    duration_years = _weighted_duration_sum(g, position_ids) / nav

    # A duration figure landing outside [min, max] is still reported as a
    # range with "n/a" utilization, never a single-sided limit the way a
    # breached allocation row is. "58% utilized" makes sense for a
    # percentage cap; it does not make sense for a time window, so this
    # doesn't reuse allocation.py's breach-display convention.
    status, _ = evaluate_range_status(duration_years, node["limit_min"], node["limit_max"], epsilon)
    graph_path = converging(_DURATION_METRIC_ID, "CONTRIBUTES_TO", [(p, {}) for p in position_ids])

    return Figure(
        figure_id=_DURATION_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=f"{duration_years.quantize(_TWO_DP, rounding=ROUND_HALF_UP)} yrs",
        limit_display=f"{node['limit_min']}–{node['limit_max']} yrs",
        utilization_display="n/a",
        graph_path=graph_path,
        citation=citation,
    )


def compute_dv01_figure(
    g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal, utilization_style: UtilizationStyle
) -> Figure:
    section, metric = REPORT_SECTIONS[_DV01_FIGURE_ID], REPORT_METRIC_LABELS[_DV01_FIGURE_ID]
    citation = q.citation_for(g, _DV01_METRIC_ID)
    if citation is None:
        return error_figure(_DV01_FIGURE_ID, section, metric, f"{_DV01_METRIC_ID} has no SOURCED_FROM edge")

    node = g.nodes[_DV01_METRIC_ID]
    position_ids = sorted(q.positions_contributing_to(g, _DV01_METRIC_ID, basis="portfolio_weighted"))
    # DV01 is the portfolio's value change for a 1bp (0.0001) rate move.
    dv01 = _weighted_duration_sum(g, position_ids) * Decimal("0.0001")
    limit_max = node["limit_max"]

    status = evaluate_status(dv01, limit_max, "max", epsilon)
    utilization_display = format_utilization(pct(dv01, limit_max), utilization_style)
    graph_path = converging(_DV01_METRIC_ID, "CONTRIBUTES_TO", [(p, {}) for p in position_ids])

    return Figure(
        figure_id=_DV01_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=f"SGD {dv01.quantize(_TWO_DP, rounding=ROUND_HALF_UP):,.0f} / bp",
        limit_display=f"max {limit_max:,.0f}",
        utilization_display=utilization_display,
        graph_path=graph_path,
        citation=citation,
    )
