from __future__ import annotations

from decimal import Decimal

import networkx as nx

from meridian.compute.figures import Figure, error_figure
from meridian.compute.rounding import evaluate_status, format_percent_1dp, format_utilization, pct
from meridian.config.schema import UtilizationStyle
from meridian.domain import REPORT_METRIC_LABELS, REPORT_SECTIONS
from meridian.graph import queries as q
from meridian.graph.builder import LIQUID_ASSETS_AGGREGATE_ID
from meridian.graph.paths import converging

_FIGURE_ID = "liquid_assets_ratio"


def compute_liquidity_figure(
    g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal, utilization_style: UtilizationStyle
) -> Figure:
    section, metric = REPORT_SECTIONS[_FIGURE_ID], REPORT_METRIC_LABELS[_FIGURE_ID]
    citation = q.citation_for(g, LIQUID_ASSETS_AGGREGATE_ID)
    if citation is None:
        return error_figure(_FIGURE_ID, section, metric, f"{LIQUID_ASSETS_AGGREGATE_ID} has no SOURCED_FROM edge")

    node = g.nodes[LIQUID_ASSETS_AGGREGATE_ID]
    floor = node["floor_pct_normal"]  # the report is against normal-condition liquidity, not the stress floor

    asset_class_ids = sorted(q.asset_classes_contributing_to(g, LIQUID_ASSETS_AGGREGATE_ID, basis="asset_class"))
    total = sum(
        (g.nodes[p]["market_value_sgd"] for ac in asset_class_ids for p in q.positions_belonging_to(g, ac)),
        Decimal(0),
    )

    value_pct = pct(total, nav)
    status = evaluate_status(value_pct, floor, "min", epsilon)
    utilization_display = format_utilization(pct(value_pct, floor), utilization_style)
    graph_path = converging(LIQUID_ASSETS_AGGREGATE_ID, "CONTRIBUTES_TO", [(ac, {}) for ac in asset_class_ids])

    return Figure(
        figure_id=_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=format_percent_1dp(value_pct),
        limit_display=f"min {floor}%",
        utilization_display=utilization_display,
        graph_path=graph_path,
        citation=citation,
    )
