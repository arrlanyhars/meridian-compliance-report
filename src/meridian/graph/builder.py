"""
Assembles the one graph both firms compute against. This is deliberately the
only place that turns ingestion output into graph structure. Nothing here
reads a FirmConfig, and it shouldn't ever need to. The Marina Bay Resorts
"fallen angel" edge below is the clearest example of that discipline: the
edge always exists once a position's rating clears the standard non-IG
threshold, full stop. Whether that edge actually counts toward a firm's
non-IG aggregate is decided later, in compute/aggregate.py, by reading
config.non_ig_aggregate.include_fallen_angels. If this file started asking
"which firm is this for", constraint 5 would already be broken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import networkx as nx

from meridian.domain import NON_IG_ASSET_CLASS_SLUGS, NON_IG_RATING_THRESHOLD, is_at_or_below_rating
from meridian.ingestion.chunking import SourceChunk
from meridian.ingestion.csv_ingest import PositionRecord
from meridian.ingestion.pdf_ingest import GuidelinesExtraction
from meridian.graph.schema import EdgeType, NodeType

NON_IG_AGGREGATE_ID = "Aggregate:non_ig_exposure"
LIQUID_ASSETS_AGGREGATE_ID = "Aggregate:liquid_assets"
SINGLE_ISSUER_LIMIT_ID = "ConcentrationLimit:single_issuer"
GRE_LIMIT_ID = "ConcentrationLimit:gre"

_LIQUID_ASSET_CLASS_SLUGS = ("sgs", "mas_bills", "cash")


@dataclass
class MeridianGraph:
    graph: nx.MultiDiGraph
    chunks: dict[str, SourceChunk] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def counts_by_node_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            nt = data["node_type"]
            counts[nt] = counts.get(nt, 0) + 1
        return counts

    def all_chunks(self) -> list[SourceChunk]:
        return list(self.chunks.values())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _prov(chunk: SourceChunk) -> dict:
    return {
        "source_doc": chunk.source_doc,
        "page": chunk.page,
        "chunk_id": chunk.chunk_id,
        "ingestion_time": chunk.ingestion_time,
        "extraction_confidence": chunk.extraction_confidence,
    }


class _Builder:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()
        self.chunks: dict[str, SourceChunk] = {}

    def register_chunk(self, chunk: SourceChunk) -> str:
        self.chunks[chunk.chunk_id] = chunk
        node_id = f"SourceChunk:{chunk.chunk_id}"
        if node_id not in self.g:
            self.g.add_node(
                node_id,
                node_type=NodeType.SOURCE_CHUNK.value,
                chunk_id=chunk.chunk_id,
                source_doc=chunk.source_doc,
                page=chunk.page,
                raw_text=chunk.raw_text,
                extraction_method=chunk.extraction_method,
                extraction_confidence=chunk.extraction_confidence,
                ingestion_time=chunk.ingestion_time,
            )
        return node_id

    def sourced_from(self, node_id: str, chunk: SourceChunk, fields: str) -> None:
        chunk_node_id = self.register_chunk(chunk)
        if not self.g.has_edge(node_id, chunk_node_id, key=chunk.chunk_id):
            self.g.add_edge(
                node_id,
                chunk_node_id,
                key=chunk.chunk_id,
                edge_type=EdgeType.SOURCED_FROM.value,
                fields=fields,
                **_prov(chunk),
            )

    def add_node(self, node_id: str, node_type: NodeType, chunk: SourceChunk, **attrs) -> None:
        self.g.add_node(node_id, node_type=node_type.value, **attrs, **_prov(chunk))

    def add_edge(self, u: str, v: str, edge_type: EdgeType, chunk: SourceChunk, key: str | None = None, **attrs) -> None:
        self.g.add_edge(u, v, key=key or edge_type.value, edge_type=edge_type.value, **attrs, **_prov(chunk))


PORTFOLIO_RISK_METRIC_IDS = ("RiskMetric:modified_duration", "RiskMetric:portfolio_dv01")


def build_graph(guidelines: GuidelinesExtraction, positions: list[PositionRecord]) -> MeridianGraph:
    b = _Builder()

    _add_asset_classes(b, guidelines)
    _add_risk_metrics(b, guidelines)
    _add_concentration_limits(b, guidelines)
    _add_aggregates(b, guidelines)
    issuer_ids, parent_ids = _add_issuers(b, positions, guidelines)
    _add_positions(b, positions, issuer_ids)
    _add_portfolio_risk_contributions(b, positions)

    return MeridianGraph(graph=b.g, chunks=b.chunks)


def _add_portfolio_risk_contributions(b: _Builder, positions: list[PositionRecord]) -> None:
    """
    Every position genuinely feeds into the portfolio-level duration and
    DV01 figures. That's just what those metrics mean, not a firm-specific
    choice, so this edge exists unconditionally for the whole book, the
    same way an AssetClass's CONTRIBUTES_TO edges do.
    """
    for pos in positions:
        pos_id = f"Position:{pos.instrument_id}"
        for metric_id in PORTFOLIO_RISK_METRIC_IDS:
            if metric_id not in b.g:
                continue  # the metric failed to parse (interest_rate_sensitivity-style); nothing to attach to
            b.add_edge(pos_id, metric_id, EdgeType.CONTRIBUTES_TO, pos.chunk, basis="portfolio_weighted")


def _add_asset_classes(b: _Builder, guidelines: GuidelinesExtraction) -> None:
    for ac in guidelines.asset_classes:
        node_id = f"AssetClass:{ac.slug}"
        b.add_node(
            node_id,
            NodeType.ASSET_CLASS,
            ac.chunk,
            slug=ac.slug,
            name=ac.name,
            min_pct=ac.min_pct,
            max_pct=ac.max_pct,
            notes=ac.notes,
        )
        b.sourced_from(node_id, ac.chunk, fields="min_pct,max_pct,notes")


def _add_risk_metrics(b: _Builder, guidelines: GuidelinesExtraction) -> None:
    for rm in guidelines.risk_metrics:
        node_id = f"RiskMetric:{rm.metric_id}"
        b.add_node(
            node_id,
            NodeType.RISK_METRIC,
            rm.chunk,
            metric_id=rm.metric_id,
            name=rm.name,
            limit_display=rm.limit_display,
            limit_kind=rm.limit_kind,
            limit_min=rm.limit_min,
            limit_max=rm.limit_max,
            parse_ok=rm.parse_ok,
            review_note=rm.review_note,
        )
        b.sourced_from(node_id, rm.chunk, fields="limit_display,limit_min,limit_max")

        if not rm.parse_ok:
            # The row exists as a node; it just can't back a breach action
            # or owner it never successfully parsed. See review_gate.py:
            # this chunk's confidence is 0.0, so it's routed to a human
            # rather than silently missing from the graph.
            continue

        action_id = f"BreachAction:{rm.metric_id}"
        b.add_node(
            action_id,
            NodeType.BREACH_ACTION,
            rm.chunk,
            action_text=rm.breach_action_text,
            monitoring_frequency=rm.monitoring_frequency,
        )
        b.add_edge(node_id, action_id, EdgeType.HAS_BREACH_ACTION, rm.chunk)
        b.sourced_from(action_id, rm.chunk, fields="action_text,monitoring_frequency")

        owner_id = f"Owner:{_slug(rm.owner_role)}"
        if owner_id not in b.g:
            b.add_node(owner_id, NodeType.OWNER, rm.chunk, role_name=rm.owner_role)
        b.sourced_from(owner_id, rm.chunk, fields="role_name")
        b.add_edge(action_id, owner_id, EdgeType.NOTIFIES, rm.chunk, key=f"{action_id}->{owner_id}")


def _add_concentration_limits(b: _Builder, guidelines: GuidelinesExtraction) -> None:
    b.add_node(
        SINGLE_ISSUER_LIMIT_ID,
        NodeType.CONCENTRATION_LIMIT,
        guidelines.single_issuer_cap.chunk,
        cap_pct=guidelines.single_issuer_cap.value_pct,
        scope="corporate issuer",
    )
    b.sourced_from(SINGLE_ISSUER_LIMIT_ID, guidelines.single_issuer_cap.chunk, fields="cap_pct")

    b.add_node(
        GRE_LIMIT_ID,
        NodeType.CONCENTRATION_LIMIT,
        guidelines.gre_cap.chunk,
        cap_pct=guidelines.gre_cap.value_pct,
        scope="GRE issuer",
    )
    b.sourced_from(GRE_LIMIT_ID, guidelines.gre_cap.chunk, fields="cap_pct")


def _add_aggregates(b: _Builder, guidelines: GuidelinesExtraction) -> None:
    b.add_node(
        NON_IG_AGGREGATE_ID,
        NodeType.AGGREGATE,
        guidelines.non_ig_aggregate_cap.chunk,
        cap_pct=guidelines.non_ig_aggregate_cap.value_pct,
        definition="High Yield + Structured Credit asset classes, plus any fallen-angel holding elsewhere",
    )
    b.sourced_from(NON_IG_AGGREGATE_ID, guidelines.non_ig_aggregate_cap.chunk, fields="cap_pct")
    for slug in sorted(NON_IG_ASSET_CLASS_SLUGS):
        b.add_edge(
            f"AssetClass:{slug}",
            NON_IG_AGGREGATE_ID,
            EdgeType.CONTRIBUTES_TO,
            guidelines.non_ig_aggregate_cap.chunk,
            key=f"AssetClass:{slug}->{NON_IG_AGGREGATE_ID}",
            basis="asset_class",
        )

    b.add_node(
        LIQUID_ASSETS_AGGREGATE_ID,
        NodeType.AGGREGATE,
        guidelines.liquidity_floor_normal.chunk,
        floor_pct_normal=guidelines.liquidity_floor_normal.value_pct,
        floor_pct_stress=guidelines.liquidity_floor_stress.value_pct,
        definition="SGS + MAS Bills + Cash & Cash Equivalents",
    )
    b.sourced_from(LIQUID_ASSETS_AGGREGATE_ID, guidelines.liquidity_floor_normal.chunk, fields="floor_pct_normal")
    b.sourced_from(LIQUID_ASSETS_AGGREGATE_ID, guidelines.liquidity_floor_stress.chunk, fields="floor_pct_stress")
    for slug in _LIQUID_ASSET_CLASS_SLUGS:
        b.add_edge(
            f"AssetClass:{slug}",
            LIQUID_ASSETS_AGGREGATE_ID,
            EdgeType.CONTRIBUTES_TO,
            guidelines.liquidity_floor_normal.chunk,
            key=f"AssetClass:{slug}->{LIQUID_ASSETS_AGGREGATE_ID}",
            basis="asset_class",
        )


def _add_issuers(
    b: _Builder, positions: list[PositionRecord], guidelines: GuidelinesExtraction
) -> tuple[dict[str, str], dict[str, str]]:
    issuer_ids: dict[str, str] = {}
    parent_ids: dict[str, str] = {}

    for pos in positions:
        if pos.issuer_name not in issuer_ids:
            issuer_id = f"Issuer:{_slug(pos.issuer_name)}"
            issuer_ids[pos.issuer_name] = issuer_id
            b.add_node(issuer_id, NodeType.ISSUER, pos.chunk, issuer_name=pos.issuer_name, issuer_type=pos.issuer_type)
            b.sourced_from(issuer_id, pos.chunk, fields="issuer_name,issuer_type")

            if pos.issuer_type == "corporate":
                b.add_edge(issuer_id, SINGLE_ISSUER_LIMIT_ID, EdgeType.SUBJECT_TO, guidelines.single_issuer_cap.chunk)
            elif pos.issuer_type == "GRE":
                b.add_edge(issuer_id, GRE_LIMIT_ID, EdgeType.SUBJECT_TO, guidelines.gre_cap.chunk)

        if pos.parent_issuer and pos.parent_issuer not in parent_ids:
            parent_id = f"Issuer:{_slug(pos.parent_issuer)}"
            parent_ids[pos.parent_issuer] = parent_id
            b.add_node(
                parent_id,
                NodeType.ISSUER,
                pos.chunk,
                issuer_name=pos.parent_issuer,
                issuer_type="GRE",
                # Not a distinct CSV row of its own; inferred from the
                # parent_issuer column shared by its children. Flagged so an
                # auditor doesn't mistake it for a directly-sourced entity.
                derived_from_children=True,
            )
            b.sourced_from(parent_id, pos.chunk, fields="parent_issuer")
            b.add_edge(parent_id, GRE_LIMIT_ID, EdgeType.SUBJECT_TO, guidelines.gre_cap.chunk)

        if pos.parent_issuer:
            child_id = issuer_ids[pos.issuer_name]
            parent_id = parent_ids[pos.parent_issuer]
            b.add_edge(child_id, parent_id, EdgeType.CHILD_OF, pos.chunk, key=f"{child_id}->CHILD_OF->{parent_id}")

    return issuer_ids, parent_ids


def _add_positions(b: _Builder, positions: list[PositionRecord], issuer_ids: dict[str, str]) -> None:
    for pos in positions:
        pos_id = f"Position:{pos.instrument_id}"
        b.add_node(
            pos_id,
            NodeType.POSITION,
            pos.chunk,
            instrument_id=pos.instrument_id,
            instrument_name=pos.instrument_name,
            market_value_sgd=pos.market_value_sgd,
            modified_duration=pos.modified_duration,
            credit_rating=pos.credit_rating,
            downgraded_from=pos.downgraded_from,
        )
        b.sourced_from(pos_id, pos.chunk, fields="market_value_sgd,modified_duration,credit_rating")

        b.add_edge(pos_id, f"AssetClass:{pos.asset_class_slug}", EdgeType.BELONGS_TO, pos.chunk)
        b.add_edge(pos_id, issuer_ids[pos.issuer_name], EdgeType.ISSUED_BY, pos.chunk)

        already_in_non_ig_class = pos.asset_class_slug in NON_IG_ASSET_CLASS_SLUGS
        has_rating = bool(pos.credit_rating)
        if (
            not already_in_non_ig_class
            and has_rating
            and is_at_or_below_rating(pos.credit_rating, NON_IG_RATING_THRESHOLD)
        ):
            b.add_edge(
                pos_id,
                NON_IG_AGGREGATE_ID,
                EdgeType.CONTRIBUTES_TO,
                pos.chunk,
                basis="fallen_angel_override",
                rating=pos.credit_rating,
            )
