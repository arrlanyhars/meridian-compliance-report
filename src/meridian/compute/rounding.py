"""
Every number in the report passes through here exactly once, at the point
it's turned into a display string. Everywhere upstream of this module keeps
full-precision Decimal; nothing gets rounded twice, and nothing gets rounded
implicitly by going through float. That's what makes a rerun byte-identical:
there's no floating point non-determinism and no accidental double rounding
to drift between runs.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from meridian.config.schema import UtilizationStyle

_ONE_DP = Decimal("0.1")


def pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Full-precision percentage. Never rounded here; rounding happens at format time only."""
    if denominator == 0:
        raise ZeroDivisionError("cannot express a percentage of a zero denominator (NAV)")
    return (numerator / denominator) * Decimal(100)


def round_1dp(value: Decimal) -> Decimal:
    return value.quantize(_ONE_DP, rounding=ROUND_HALF_UP)


def format_percent_1dp(value: Decimal) -> str:
    return f"{round_1dp(value)}%"


def format_truncated_bps(value: Decimal) -> str:
    """
    Firm B's house style: basis points, truncated (not rounded) to a whole
    number. 58.333% -> 5833 bps, not 5833.3 or 5834; see firm_B_brief.md.
    """
    bps = (value * 100).to_integral_value(rounding=ROUND_DOWN)
    return f"{int(bps)} bps"


def format_utilization(value: Decimal | None, style: UtilizationStyle) -> str:
    if value is None:
        return "n/a"
    if style == UtilizationStyle.TRUNCATED_BPS:
        return format_truncated_bps(value)
    return format_percent_1dp(value)


def format_sgd(value: Decimal) -> str:
    return f"SGD {value:,.0f}"


def display_status(status: str) -> str:
    """
    Figure.status stays a clean identifier (AT_LIMIT) everywhere internally:
    the JSON output, the firewall's numeric surface, graph_path strings.
    firm_A_answer_key.xlsx spells it "AT LIMIT" with a space, though, so the
    xlsx report and reconcile.py's comparison go through this at the point
    they actually write or compare against that spreadsheet's convention.
    """
    return status.replace("_", " ")


def evaluate_status(value: Decimal, limit: Decimal, kind: str, epsilon: Decimal) -> str:
    """
    kind="max": limit is a ceiling, breached when value exceeds it.
    kind="min": limit is a floor, breached when value falls short of it.

    Sitting exactly on the limit (within epsilon) is its own status,
    AT_LIMIT, rather than folding into OK. It's compliant today but has
    no headroom left, and the answer key treats that as worth flagging
    (see the single-issuer-concentration row, exactly at its 8% cap).
    """
    headroom_used = (value - limit) if kind == "max" else (limit - value)
    if headroom_used > epsilon:
        return "BREACH"
    if headroom_used >= 0:
        return "AT_LIMIT"
    return "OK"


def evaluate_range_status(value: Decimal, min_limit: Decimal, max_limit: Decimal, epsilon: Decimal) -> tuple[str, str | None]:
    """
    For a metric with both a floor and a ceiling (allocation rows, portfolio
    duration). Checks the ceiling first, then the floor, and returns which
    bound is responsible so the caller can decide how to display the limit.
    """
    max_status = evaluate_status(value, max_limit, "max", epsilon)
    if max_status != "OK":
        return max_status, "max"
    min_status = evaluate_status(value, min_limit, "min", epsilon)
    if min_status != "OK":
        return min_status, "min"
    return "OK", None
