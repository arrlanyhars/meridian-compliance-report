"""The config mini-DSL used by scripts/config_preview.py."""

from decimal import Decimal

import pytest

from meridian.config.dsl import DslError, parse, to_dsl
from meridian.config.schema import GreGrouping, UtilizationStyle


def test_parses_every_known_key():
    config = parse("gre=parent_issuer fallen_angels=on util=bps epsilon=0.5")
    assert config.concentration.gre_grouping == GreGrouping.PARENT_ISSUER
    assert config.non_ig_aggregate.include_fallen_angels is True
    assert config.formatting.utilization_style == UtilizationStyle.TRUNCATED_BPS
    assert config.tolerance.status_epsilon_pct == Decimal("0.5")


def test_missing_keys_fall_back_to_defaults():
    config = parse("")
    assert config.concentration.gre_grouping == GreGrouping.ISSUER
    assert config.non_ig_aggregate.include_fallen_angels is False
    assert config.formatting.utilization_style == UtilizationStyle.PERCENT_1DP
    assert config.tolerance.status_epsilon_pct == Decimal("0")


def test_key_order_does_not_matter():
    a = parse("util=bps gre=parent_issuer")
    b = parse("gre=parent_issuer util=bps")
    assert a.formatting.utilization_style == b.formatting.utilization_style
    assert a.concentration.gre_grouping == b.concentration.gre_grouping


@pytest.mark.parametrize(
    "line",
    [
        "notakeyvalue",
        "unknown_key=foo",
        "gre=sideways",
        "fallen_angels=maybe",
        "util=fahrenheit",
        "epsilon=not_a_number",
    ],
)
def test_invalid_input_raises_dsl_error_instead_of_crashing(line):
    with pytest.raises(DslError):
        parse(line)


def test_round_trips_firm_a_and_firm_b(firm_a_config, firm_b_config):
    for original in (firm_a_config, firm_b_config):
        reparsed = parse(to_dsl(original))
        assert reparsed.concentration.gre_grouping == original.concentration.gre_grouping
        assert reparsed.non_ig_aggregate.include_fallen_angels == original.non_ig_aggregate.include_fallen_angels
        assert reparsed.formatting.utilization_style == original.formatting.utilization_style
        assert reparsed.tolerance.status_epsilon_pct == original.tolerance.status_epsilon_pct
