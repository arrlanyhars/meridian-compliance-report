"""
Renders a `graph_path` string in the same Cypher-ish notation the spec's
own example figure uses: (Label:id)-[:TYPE]->(Label:id). Since every node
id in this graph is already "Type:slug", a node only needs wrapping in
parens; nothing here invents display names.
"""

from __future__ import annotations


def node(node_id: str) -> str:
    return f"({node_id})"


def hop(from_id: str, edge_type: str, to_id: str, **edge_attrs: object) -> str:
    label = f"[:{edge_type}{_attrs(edge_attrs)}]"
    return f"({from_id})-{label}->({to_id})"


def converging(target_id: str, edge_type: str, sources: list[tuple[str, dict]]) -> str:
    """
    Several nodes feeding one edge_type into target_id, rendered as one
    continuous chain the way the spec's own example does it:
    (A)-[:TYPE]->(Target)<-[:TYPE]-(B)<-[:TYPE]-(C)

    sources: list of (node_id, edge_attrs) in the order they should appear.
    """
    if not sources:
        return node(target_id)
    first_id, first_attrs = sources[0]
    chain = [f"({first_id})-[:{edge_type}{_attrs(first_attrs)}]->({target_id})"]
    for node_id, attrs in sources[1:]:
        chain.append(f"<-[:{edge_type}{_attrs(attrs)}]-({node_id})")
    return "".join(chain)


def _attrs(attrs: dict) -> str:
    if not attrs:
        return ""
    inner = ", ".join(f"{k}:{v}" for k, v in attrs.items())
    return f" {{{inner}}}"
