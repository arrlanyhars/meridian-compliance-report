from __future__ import annotations

from decimal import Decimal

import networkx as nx

from meridian.compute.figures import Figure, error_figure
from meridian.compute.rounding import evaluate_status, format_percent_1dp, format_utilization, pct
from meridian.config.schema import UtilizationStyle
from meridian.domain import REPORT_METRIC_LABELS, REPORT_SECTIONS
from meridian.graph import queries as q
from meridian.graph.builder import NON_IG_AGGREGATE_ID
from meridian.graph.paths import converging

_FIGURE_ID = "aggregate_non_ig_exposure"


def compute_non_ig_aggregate_figure(
    g: nx.MultiDiGraph,
    nav: Decimal,
    epsilon: Decimal,
    utilization_style: UtilizationStyle,
    include_fallen_angels: bool,
) -> Figure:
    section, metric = REPORT_SECTIONS[_FIGURE_ID], REPORT_METRIC_LABELS[_FIGURE_ID]
    citation = q.citation_for(g, NON_IG_AGGREGATE_ID)
    if citation is None:
        return error_figure(_FIGURE_ID, section, metric, f"{NON_IG_AGGREGATE_ID} has no SOURCED_FROM edge")

    node = g.nodes[NON_IG_AGGREGATE_ID]
    asset_class_ids = sorted(q.asset_classes_contributing_to(g, NON_IG_AGGREGATE_ID, basis="asset_class"))
    total = sum(
        (g.nodes[p]["market_value_sgd"] for ac in asset_class_ids for p in q.positions_belonging_to(g, ac)),
        Decimal(0),
    )
    path_sources: list[tuple[str, dict]] = [(ac, {}) for ac in asset_class_ids]

    if include_fallen_angels:
        fallen_ids = sorted(q.positions_contributing_to(g, NON_IG_AGGREGATE_ID, basis="fallen_angel_override"))
        total += sum((g.nodes[p]["market_value_sgd"] for p in fallen_ids), Decimal(0))
        path_sources += [(p, {"basis": "fallen_angel_override"}) for p in fallen_ids]

    value_pct = pct(total, nav)
    cap = node["cap_pct"]
    status = evaluate_status(value_pct, cap, "max", epsilon)
    utilization_display = format_utilization(pct(value_pct, cap), utilization_style)
    graph_path = converging(NON_IG_AGGREGATE_ID, "CONTRIBUTES_TO", path_sources)

    return Figure(
        figure_id=_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=format_percent_1dp(value_pct),
        limit_display=f"max {cap}%",
        utilization_display=utilization_display,
        graph_path=graph_path,
        citation=citation,
    )
