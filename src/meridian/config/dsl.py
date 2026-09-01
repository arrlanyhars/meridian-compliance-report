"""
A small, intentionally minimal DSL for expressing a firm's method as one
line, instead of a multi-line YAML file. This is not a replacement for
configs/*.yaml, that's still what the engine actually reads on a real run.
It exists for scripts/config_preview.py's live-preview REPL, where typing a
full YAML block on every edit would be tedious.

Grammar: whitespace-separated key=value tokens, any order, any subset
(missing keys fall back to Firm A's defaults):

  gre=issuer|parent_issuer
  fallen_angels=on|off
  util=percent|bps
  epsilon=<decimal>

Example: "gre=parent_issuer fallen_angels=on util=bps"
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from meridian.config.schema import (
    ConcentrationConfig,
    FirmConfig,
    FormattingConfig,
    GreGrouping,
    NonIgAggregateConfig,
    ReconciliationConfig,
    ToleranceConfig,
    UtilizationStyle,
)

_GRE_VALUES = {"issuer": GreGrouping.ISSUER, "parent_issuer": GreGrouping.PARENT_ISSUER}
_BOOL_VALUES = {"on": True, "true": True, "1": True, "off": False, "false": False, "0": False}
_UTIL_VALUES = {"percent": UtilizationStyle.PERCENT_1DP, "bps": UtilizationStyle.TRUNCATED_BPS}
_KNOWN_KEYS = {"gre", "fallen_angels", "util", "epsilon"}


class DslError(ValueError):
    pass


def parse(line: str, *, firm_id: str = "preview", firm_name: str = "Preview") -> FirmConfig:
    fields: dict[str, str] = {}
    for token in line.strip().split():
        if "=" not in token:
            raise DslError(f"expected key=value, got {token!r}")
        key, _, value = token.partition("=")
        if key not in _KNOWN_KEYS:
            raise DslError(f"unknown key {key!r}, expected one of {sorted(_KNOWN_KEYS)}")
        fields[key] = value

    gre_raw = fields.get("gre", "issuer")
    if gre_raw not in _GRE_VALUES:
        raise DslError(f"gre must be one of {sorted(_GRE_VALUES)}, got {gre_raw!r}")

    fallen_raw = fields.get("fallen_angels", "off")
    if fallen_raw not in _BOOL_VALUES:
        raise DslError(f"fallen_angels must be one of {sorted(_BOOL_VALUES)}, got {fallen_raw!r}")

    util_raw = fields.get("util", "percent")
    if util_raw not in _UTIL_VALUES:
        raise DslError(f"util must be one of {sorted(_UTIL_VALUES)}, got {util_raw!r}")

    epsilon_raw = fields.get("epsilon", "0")
    try:
        epsilon = Decimal(epsilon_raw)
    except InvalidOperation:
        raise DslError(f"epsilon must be a number, got {epsilon_raw!r}") from None

    return FirmConfig(
        firm_id=firm_id,
        firm_name=firm_name,
        concentration=ConcentrationConfig(gre_grouping=_GRE_VALUES[gre_raw]),
        non_ig_aggregate=NonIgAggregateConfig(include_fallen_angels=_BOOL_VALUES[fallen_raw]),
        formatting=FormattingConfig(utilization_style=_UTIL_VALUES[util_raw]),
        tolerance=ToleranceConfig(status_epsilon_pct=epsilon),
        reconciliation=ReconciliationConfig(answer_key_path=None),
    )


def to_dsl(config: FirmConfig) -> str:
    gre = "parent_issuer" if config.concentration.gre_grouping == GreGrouping.PARENT_ISSUER else "issuer"
    fallen = "on" if config.non_ig_aggregate.include_fallen_angels else "off"
    util = "bps" if config.formatting.utilization_style == UtilizationStyle.TRUNCATED_BPS else "percent"
    return f"gre={gre} fallen_angels={fallen} util={util} epsilon={config.tolerance.status_epsilon_pct}"
