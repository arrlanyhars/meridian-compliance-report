"""
This is the whole answer to constraint 5 ("reconfigure to Firm B without an
engine-code edit"). Everything a firm's house convention can vary is a field
here, nothing more, nothing less. The compute layer reads a FirmConfig and
branches on these fields; it never checks `if firm_id == "firm_b"` anywhere.

If a future firm needs a convention this schema doesn't cover, that's a sign
the schema needs a new field, not a special case bolted onto the engine.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class GreGrouping(str, Enum):
    ISSUER = "issuer"
    PARENT_ISSUER = "parent_issuer"


class UtilizationStyle(str, Enum):
    PERCENT_1DP = "percent_1dp"
    TRUNCATED_BPS = "truncated_bps"


class ConcentrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gre_grouping: GreGrouping


class NonIgAggregateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Whether a holding downgraded below investment grade counts toward the
    # non-IG aggregate even if its asset_class label still says otherwise.
    # The rating cutoff itself (BB+) is a rating-agency constant, not a firm
    # convention. See domain.NON_IG_RATING_THRESHOLD; it isn't a field here.
    # This flag is the only thing that actually varies by firm.
    include_fallen_angels: bool


class FormattingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utilization_style: UtilizationStyle


class ToleranceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # How far a figure may sit from a limit before we call it a breach, as
    # percentage points. 0 means exact comparison, which is what both sample
    # firms need. Every case in the answer key lands exactly on or off the
    # limit, there's no fuzzy case to justify a wider tolerance here.
    status_epsilon_pct: Decimal = Decimal("0")


class ReconciliationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Firm B has no answer key spreadsheet, only the 3 deltas stated in
    # firm_B_brief.md, so this is left null for that config.
    answer_key_path: str | None = None


class FirmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firm_id: str
    firm_name: str
    concentration: ConcentrationConfig
    non_ig_aggregate: NonIgAggregateConfig
    formatting: FormattingConfig
    tolerance: ToleranceConfig = ToleranceConfig()
    reconciliation: ReconciliationConfig = ReconciliationConfig()

    @classmethod
    def load(cls, path: str | Path) -> "FirmConfig":
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return cls.model_validate(raw)

    def content_hash(self) -> str:
        """Stable hash of the config content, used for the config_change audit event."""
        import hashlib

        canonical = self.model_dump_json(exclude_none=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
