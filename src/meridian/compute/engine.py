"""
Orchestrates every compute/* module into one FigureSet. This module, and
everything it imports from compute/, must never import from narrative/ or
any LLM SDK. tests/test_module_boundaries.py checks that by static analysis,
not just convention: constraint 3 depends on this being structurally true,
not merely something nobody happened to break yet.
"""

from __future__ import annotations

from decimal import Decimal

import networkx as nx

from meridian.compute.aggregate import compute_non_ig_aggregate_figure
from meridian.compute.allocation import compute_allocation_figures
from meridian.compute.concentration import (
    compute_gre_concentration_figure,
    compute_single_issuer_concentration_figure,
)
from meridian.compute.figures import FigureSet
from meridian.compute.liquidity import compute_liquidity_figure
from meridian.compute.risk import compute_duration_figure, compute_dv01_figure
from meridian.config.schema import FirmConfig
from meridian.graph.builder import MeridianGraph
from meridian.graph.schema import NodeType


def total_nav(g: nx.MultiDiGraph) -> Decimal:
    return sum(
        (data["market_value_sgd"] for _, data in g.nodes(data=True) if data["node_type"] == NodeType.POSITION.value),
        Decimal(0),
    )


def compute_figure_set(mg: MeridianGraph, config: FirmConfig) -> FigureSet:
    g = mg.graph
    nav = total_nav(g)
    epsilon = config.tolerance.status_epsilon_pct
    style = config.formatting.utilization_style

    figures = list(compute_allocation_figures(g, nav, epsilon, style))
    figures.append(
        compute_non_ig_aggregate_figure(g, nav, epsilon, style, config.non_ig_aggregate.include_fallen_angels)
    )
    figures.append(compute_single_issuer_concentration_figure(g, nav, epsilon, style))
    figures.append(compute_gre_concentration_figure(g, nav, epsilon, style, config.concentration.gre_grouping))
    figures.append(compute_liquidity_figure(g, nav, epsilon, style))
    figures.append(compute_duration_figure(g, nav, epsilon))
    figures.append(compute_dv01_figure(g, nav, epsilon, style))

    return FigureSet(firm_id=config.firm_id, firm_name=config.firm_name, figures=tuple(figures))
