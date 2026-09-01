"""
Small traversal helpers shared by the compute/ modules. Nothing here computes
a report figure; it only answers graph questions ("which positions belong
to this asset class", "what does this node cite"). Keeping the traversal
separate from the arithmetic makes it possible to unit-test "does the graph
actually connect what it should" independently of "is the arithmetic right".
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from meridian.graph.schema import EdgeType


@dataclass(frozen=True)
class Citation:
    source_doc: str
    page: int | None
    chunk_id: str
    passage_summary: str


def _edges_by_type(g: nx.MultiDiGraph, node_id: str, edge_type: EdgeType, direction: str) -> list[tuple[str, str, dict]]:
    edges = g.out_edges(node_id, data=True) if direction == "out" else g.in_edges(node_id, data=True)
    return [(u, v, d) for u, v, d in edges if d.get("edge_type") == edge_type.value]


def positions_belonging_to(g: nx.MultiDiGraph, asset_class_id: str) -> list[str]:
    """Position node ids with a BELONGS_TO edge into this AssetClass."""
    return [u for u, _, _ in _edges_by_type(g, asset_class_id, EdgeType.BELONGS_TO, "in")]


def positions_contributing_to(g: nx.MultiDiGraph, aggregate_id: str, basis: str | None = None) -> list[str]:
    """Position node ids with a direct CONTRIBUTES_TO edge into this Aggregate (not via an AssetClass)."""
    edges = _edges_by_type(g, aggregate_id, EdgeType.CONTRIBUTES_TO, "in")
    return [u for u, _, d in edges if u.startswith("Position:") and (basis is None or d.get("basis") == basis)]


def asset_classes_contributing_to(g: nx.MultiDiGraph, aggregate_id: str, basis: str | None = None) -> list[str]:
    edges = _edges_by_type(g, aggregate_id, EdgeType.CONTRIBUTES_TO, "in")
    return [u for u, _, d in edges if u.startswith("AssetClass:") and (basis is None or d.get("basis") == basis)]


def issuers_subject_to(g: nx.MultiDiGraph, limit_id: str) -> list[str]:
    return [u for u, _, _ in _edges_by_type(g, limit_id, EdgeType.SUBJECT_TO, "in")]


def positions_issued_by(g: nx.MultiDiGraph, issuer_id: str) -> list[str]:
    return [u for u, _, _ in _edges_by_type(g, issuer_id, EdgeType.ISSUED_BY, "in")]


def parent_of(g: nx.MultiDiGraph, issuer_id: str) -> str | None:
    edges = _edges_by_type(g, issuer_id, EdgeType.CHILD_OF, "out")
    return edges[0][1] if edges else None


def breach_action_of(g: nx.MultiDiGraph, risk_metric_id: str) -> str | None:
    edges = _edges_by_type(g, risk_metric_id, EdgeType.HAS_BREACH_ACTION, "out")
    return edges[0][1] if edges else None


def owner_of(g: nx.MultiDiGraph, breach_action_id: str) -> str | None:
    edges = _edges_by_type(g, breach_action_id, EdgeType.NOTIFIES, "out")
    return edges[0][1] if edges else None


def citation_for(g: nx.MultiDiGraph, node_id: str) -> Citation | None:
    """
    Walk node_id's SOURCED_FROM edge(s) out to their SourceChunk node(s).
    A node can have more than one (Aggregate:liquid_assets has two: the
    normal-condition floor and the stress floor come from the same sentence
    but were extracted as separate facts); the first is used as the figure's
    primary citation, but every edge is still on the graph for an auditor to
    walk directly if they want the full picture.

    Returns None if no SOURCED_FROM edge exists, which is the caller's
    signal to treat the figure as untraceable rather than invent a citation.
    """
    edges = _edges_by_type(g, node_id, EdgeType.SOURCED_FROM, "out")
    if not edges:
        return None
    _, chunk_node_id, _ = edges[0]
    chunk = g.nodes[chunk_node_id]
    return Citation(
        source_doc=chunk["source_doc"],
        page=chunk["page"],
        chunk_id=chunk["chunk_id"],
        passage_summary=chunk["raw_text"],
    )
