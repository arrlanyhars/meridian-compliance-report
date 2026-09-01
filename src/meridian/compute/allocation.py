from __future__ import annotations

from decimal import Decimal

import networkx as nx

from meridian.compute.figures import Figure, error_figure
from meridian.compute.rounding import evaluate_range_status, format_percent_1dp, format_utilization, pct
from meridian.config.schema import UtilizationStyle
from meridian.domain import ALLOCATION_ROW_ORDER, REPORT_METRIC_LABELS, REPORT_SECTIONS
from meridian.graph import queries as q


def compute_allocation_figures(
    g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal, utilization_style: UtilizationStyle
) -> list[Figure]:
    figures: list[Figure] = []

    for slug in ALLOCATION_ROW_ORDER:
        node_id = f"AssetClass:{slug}"
        node = g.nodes[node_id]
        position_ids = sorted(q.positions_belonging_to(g, node_id))
        market_value = sum((g.nodes[p]["market_value_sgd"] for p in position_ids), Decimal(0))
        value_pct = pct(market_value, nav)
        min_limit, max_limit = node["min_pct"], node["max_pct"]
        citation = q.citation_for(g, node_id)

        if citation is None:
            # Can't happen with this dataset (builder.py always attaches a
            # SOURCED_FROM edge), but if a future ingestion path ever
            # produced an AssetClass node without one, the figure must come
            # out as an explicit error, not a number nobody could trace.
            figures.append(
                error_figure(
                    f"allocation_{slug}",
                    REPORT_SECTIONS[slug],
                    REPORT_METRIC_LABELS[slug],
                    f"{node_id} has no SOURCED_FROM edge to a source chunk",
                )
            )
            continue

        status, breached_bound = evaluate_range_status(value_pct, min_limit, max_limit, epsilon)

        if status == "BREACH":
            # A breach of one bound of a min/max range makes the other bound
            # moot for this figure. Utilization against a limit you didn't
            # breach isn't a meaningful number, so it's "n/a" rather than a
            # ratio that would misleadingly suggest partial compliance.
            limit_display = f"min {min_limit}%" if breached_bound == "min" else f"max {max_limit}%"
            utilization_display = "n/a"
        else:
            limit_display = f"{min_limit}–{max_limit}%"
            utilization_display = format_utilization(pct(value_pct, max_limit), utilization_style)

        contributing = " + ".join(f"Position:{p.split(':', 1)[1]}" for p in position_ids)
        graph_path = f"({node_id})<-[:BELONGS_TO]-({contributing})-[:SOURCED_FROM]->(SourceChunk:{citation.chunk_id})"

        figures.append(
            Figure(
                figure_id=f"allocation_{slug}",
                section=REPORT_SECTIONS[slug],
                metric=REPORT_METRIC_LABELS[slug],
                status=status,
                value_display=format_percent_1dp(value_pct),
                limit_display=limit_display,
                utilization_display=utilization_display,
                graph_path=graph_path,
                citation=citation,
            )
        )

    return figures
