from __future__ import annotations

from enum import Enum


class NodeType(str, Enum):
    ASSET_CLASS = "AssetClass"
    RISK_METRIC = "RiskMetric"
    BREACH_ACTION = "BreachAction"
    OWNER = "Owner"
    ISSUER = "Issuer"
    POSITION = "Position"
    AGGREGATE = "Aggregate"          # a cap/floor computed across several asset classes (non-IG, liquidity)
    CONCENTRATION_LIMIT = "ConcentrationLimit"  # a cap applied per issuer (single-issuer, GRE)
    SOURCE_CHUNK = "SourceChunk"


class EdgeType(str, Enum):
    BELONGS_TO = "BELONGS_TO"        # Position -> AssetClass
    ISSUED_BY = "ISSUED_BY"          # Position -> Issuer
    CHILD_OF = "CHILD_OF"            # Issuer -> parent Issuer
    CONTRIBUTES_TO = "CONTRIBUTES_TO"  # AssetClass|Position -> Aggregate
    SUBJECT_TO = "SUBJECT_TO"        # Issuer -> ConcentrationLimit
    HAS_BREACH_ACTION = "HAS_BREACH_ACTION"  # RiskMetric -> BreachAction
    NOTIFIES = "NOTIFIES"            # BreachAction -> Owner
    SOURCED_FROM = "SOURCED_FROM"    # any fact node -> SourceChunk


PROVENANCE_FIELDS = ("source_doc", "page", "chunk_id", "ingestion_time", "extraction_confidence")
