from __future__ import annotations

from decimal import Decimal

import networkx as nx

from meridian.compute.figures import Figure, error_figure
from meridian.compute.rounding import evaluate_status, format_percent_1dp, format_utilization, pct
from meridian.config.schema import GreGrouping, UtilizationStyle
from meridian.domain import REPORT_METRIC_LABELS, REPORT_SECTIONS
from meridian.graph import queries as q
from meridian.graph.builder import GRE_LIMIT_ID, SINGLE_ISSUER_LIMIT_ID
from meridian.graph.paths import converging

_SINGLE_FIGURE_ID = "largest_single_corporate_issuer"
_GRE_FIGURE_ID = "largest_gre_issuer"


def _issuer_market_value(g: nx.MultiDiGraph, issuer_id: str) -> Decimal:
    return sum((g.nodes[p]["market_value_sgd"] for p in q.positions_issued_by(g, issuer_id)), Decimal(0))


def compute_single_issuer_concentration_figure(
    g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal, utilization_style: UtilizationStyle
) -> Figure:
    section, metric = REPORT_SECTIONS[_SINGLE_FIGURE_ID], REPORT_METRIC_LABELS[_SINGLE_FIGURE_ID]
    citation = q.citation_for(g, SINGLE_ISSUER_LIMIT_ID)
    if citation is None:
        return error_figure(_SINGLE_FIGURE_ID, section, metric, f"{SINGLE_ISSUER_LIMIT_ID} has no SOURCED_FROM edge")

    cap = g.nodes[SINGLE_ISSUER_LIMIT_ID]["cap_pct"]
    corporate_issuer_ids = sorted(q.issuers_subject_to(g, SINGLE_ISSUER_LIMIT_ID))
    best_issuer_id = max(corporate_issuer_ids, key=lambda i: _issuer_market_value(g, i))
    best_value = _issuer_market_value(g, best_issuer_id)

    value_pct = pct(best_value, nav)
    status = evaluate_status(value_pct, cap, "max", epsilon)
    utilization_display = format_utilization(pct(value_pct, cap), utilization_style)

    position_ids = sorted(q.positions_issued_by(g, best_issuer_id))
    contributing = " + ".join(f"Position:{p.split(':', 1)[1]}" for p in position_ids)
    graph_path = f"({contributing})-[:ISSUED_BY]->({best_issuer_id})-[:SUBJECT_TO]->({SINGLE_ISSUER_LIMIT_ID})"

    return Figure(
        figure_id=_SINGLE_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=format_percent_1dp(value_pct),
        limit_display=f"max {cap}%",
        utilization_display=utilization_display,
        graph_path=graph_path,
        citation=citation,
    )


def compute_gre_concentration_figure(
    g: nx.MultiDiGraph, nav: Decimal, epsilon: Decimal, utilization_style: UtilizationStyle, grouping: GreGrouping
) -> Figure:
    section, metric = REPORT_SECTIONS[_GRE_FIGURE_ID], REPORT_METRIC_LABELS[_GRE_FIGURE_ID]
    citation = q.citation_for(g, GRE_LIMIT_ID)
    if citation is None:
        return error_figure(_GRE_FIGURE_ID, section, metric, f"{GRE_LIMIT_ID} has no SOURCED_FROM edge")

    cap = g.nodes[GRE_LIMIT_ID]["cap_pct"]
    # SUBJECT_TO also reaches the synthetic parent placeholder (Redhill
    # Holdings), which never issues a position directly. Only real issuers
    # are grouping candidates; the parent is just a grouping key below.
    gre_issuer_ids = sorted(i for i in q.issuers_subject_to(g, GRE_LIMIT_ID) if q.positions_issued_by(g, i))

    groups: dict[str, list[str]] = {}
    for issuer_id in gre_issuer_ids:
        if grouping == GreGrouping.PARENT_ISSUER:
            key = q.parent_of(g, issuer_id) or issuer_id
        else:
            key = issuer_id
        groups.setdefault(key, []).append(issuer_id)

    best_key, best_members, best_value = None, [], Decimal(-1)
    for key, members in sorted(groups.items()):
        value = sum((_issuer_market_value(g, m) for m in members), Decimal(0))
        if value > best_value:
            best_key, best_members, best_value = key, members, value

    value_pct = pct(best_value, nav)
    status = evaluate_status(value_pct, cap, "max", epsilon)
    utilization_display = format_utilization(pct(value_pct, cap), utilization_style)

    if len(best_members) == 1:
        subject_path = f"({best_members[0]})-[:SUBJECT_TO]->({GRE_LIMIT_ID})"
    else:
        # Multiple issuers grouped under one parent (Firm B's convention):
        # show them converging via CHILD_OF before the parent is checked
        # against the cap.
        subject_path = converging(best_key, "CHILD_OF", [(m, {}) for m in best_members])
        subject_path += f"-[:SUBJECT_TO]->({GRE_LIMIT_ID})"

    return Figure(
        figure_id=_GRE_FIGURE_ID,
        section=section,
        metric=metric,
        status=status,
        value_display=format_percent_1dp(value_pct),
        limit_display=f"max {cap}%",
        utilization_display=utilization_display,
        graph_path=subject_path,
        citation=citation,
    )
