"""
Small, shared facts about the Meridian fund domain that don't belong to any
single layer (ingestion, graph, compute all need them). Kept separate so none
of those layers end up importing each other just to share a lookup table.
"""

from __future__ import annotations

# The holdings CSV uses shorter asset class labels than the guidelines PDF
# ("Foreign Currency Bonds" vs "Foreign Currency Bonds (hedged)"). Both sides
# get normalized to these slugs so a Position and its AssetClass node agree
# on identity regardless of which document used which spelling.
ASSET_CLASS_SLUGS: dict[str, str] = {
    "Singapore Government Securities": "sgs",
    "Singapore Government Securities (SGS)": "sgs",
    "MAS Bills": "mas_bills",
    "Investment Grade Corporate Bonds": "ig_corp",
    "High Yield Bonds": "high_yield",
    "Foreign Currency Bonds": "fx_bonds",
    "Foreign Currency Bonds (hedged)": "fx_bonds",
    "Structured Credit": "structured_credit",
    "Structured Credit (ABS/MBS)": "structured_credit",
    "Cash & Cash Equivalents": "cash",
}

# Asset classes whose entire holding is treated as non-investment-grade by
# definition (Section 2's own aggregate note), independent of any per-position
# credit rating check.
NON_IG_ASSET_CLASS_SLUGS: frozenset[str] = frozenset({"high_yield", "structured_credit"})

# S&P-style scale, best to worst. Only used for ordinal comparison (is rating
# X at or below rating Y), never displayed or stored as a magic number.
_RATING_SCALE: tuple[str, ...] = (
    "AAA",
    "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC+", "CCC", "CCC-",
    "CC", "C", "D",
)
_RATING_RANK: dict[str, int] = {rating: rank for rank, rating in enumerate(_RATING_SCALE)}

# BB+ is the standard rating-agency cutoff for investment grade (BBB- is the
# lowest IG notch, BB+ the highest non-IG notch). This is a fact about the
# rating scale itself, not a firm's house convention, so it's a constant here
# rather than a config field. What IS a house convention is whether a firm
# pulls sub-IG holdings from other asset classes into the non-IG aggregate at
# all (see FirmConfig.non_ig_aggregate.include_fallen_angels).
NON_IG_RATING_THRESHOLD = "BB+"


def is_at_or_below_rating(rating: str, threshold: str) -> bool:
    """True if `rating` is the same as or worse than `threshold` (higher rank = worse)."""
    try:
        return _RATING_RANK[rating] >= _RATING_RANK[threshold]
    except KeyError as exc:
        raise ValueError(f"unrecognized credit rating: {exc.args[0]!r}") from exc


# The order and exact wording of report_template.xlsx / firm_A_answer_key.xlsx.
# xlsx_writer.py and reconcile.py both key off (section, metric) to line a
# computed Figure up with its row, so this has to match those files verbatim,
# not the guidelines PDF's own wording (which spells some of these slightly
# differently, e.g. "Singapore Government Securities (SGS)").
ALLOCATION_ROW_ORDER: tuple[str, ...] = (
    "sgs", "mas_bills", "ig_corp", "high_yield", "fx_bonds", "structured_credit", "cash",
)

REPORT_METRIC_LABELS: dict[str, str] = {
    "sgs": "Singapore Government Securities",
    "mas_bills": "MAS Bills",
    "ig_corp": "Investment Grade Corporate Bonds",
    "high_yield": "High Yield Bonds",
    "fx_bonds": "Foreign Currency Bonds (hedged)",
    "structured_credit": "Structured Credit (ABS/MBS)",
    "cash": "Cash & Cash Equivalents",
    "aggregate_non_ig_exposure": "Aggregate non-IG exposure",
    "largest_single_corporate_issuer": "Largest single corporate issuer",
    "largest_gre_issuer": "Largest GRE issuer",
    "liquid_assets_ratio": "Liquid assets ratio",
    "portfolio_modified_duration": "Portfolio modified duration",
    "portfolio_dv01": "Portfolio DV01",
}

REPORT_SECTIONS: dict[str, str] = {
    "sgs": "Allocation", "mas_bills": "Allocation", "ig_corp": "Allocation",
    "high_yield": "Allocation", "fx_bonds": "Allocation", "structured_credit": "Allocation",
    "cash": "Allocation",
    "aggregate_non_ig_exposure": "Aggregate",
    "largest_single_corporate_issuer": "Concentration",
    "largest_gre_issuer": "Concentration",
    "liquid_assets_ratio": "Liquidity",
    "portfolio_modified_duration": "Market risk",
    "portfolio_dv01": "Market risk",
}


def asset_class_slug(label: str) -> str:
    try:
        return ASSET_CLASS_SLUGS[label]
    except KeyError as exc:
        raise ValueError(f"unrecognized asset class label: {exc.args[0]!r}") from exc
