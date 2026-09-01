"""
Given one figure, explain exactly how it was produced. This is read-only
over an already-computed Figure; it doesn't touch the graph or
recompute anything, so it can't introduce a number that didn't already come
out of compute/engine.py. scripts/replay.py is the CLI shell around this.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from meridian.compute.figures import Figure
from meridian.config.schema import FirmConfig

# Which config field actually decides this figure's value, beyond the
# universal formatting.utilization_style that applies to every figure's
# utilization display. Most figures aren't config-dependent at all: this
# table only has entries for the two figures firm_B_brief.md's conventions
# actually touch. See docs/03_rfc.md, "Constraint 5", for why the other
# eleven figures never appear here.
FIGURE_CONFIG_RULES: dict[str, tuple[str, ...]] = {
    "aggregate_non_ig_exposure": ("non_ig_aggregate.include_fallen_angels",),
    "largest_gre_issuer": ("concentration.gre_grouping",),
}


def _config_value(config: FirmConfig, dotted_path: str) -> str:
    obj: object = config
    for part in dotted_path.split("."):
        obj = getattr(obj, part)
    return obj.value if isinstance(obj, Enum) else str(obj)


def _parse_numeric(text: object) -> Decimal | None:
    if text is None:
        return None
    cleaned = str(text).replace(",", "").replace("%", "").replace("SGD", "").replace("/ bp", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class ReplayExplanation:
    figure_id: str
    firm_id: str
    section: str
    metric: str
    value: str | None
    status: str
    limit: str | None
    utilization: str | None
    graph_path: str | None
    source_doc: str | None
    page: int | None
    passage: str | None
    config_rules: tuple[str, ...]
    delta_vs_answer_key: str | None
    delta_vs_firm_a: str | None


def explain_figure(
    figure: Figure,
    config: FirmConfig,
    answer_key_value: object = None,
    firm_a_figure: Figure | None = None,
) -> ReplayExplanation:
    rules = [f"{path} = {_config_value(config, path)}" for path in FIGURE_CONFIG_RULES.get(figure.figure_id, ())]
    rules.append(f"formatting.utilization_style = {config.formatting.utilization_style.value}")

    delta_vs_answer_key = None
    if answer_key_value is not None:
        expected_num, actual_num = _parse_numeric(answer_key_value), _parse_numeric(figure.value_display)
        if expected_num is not None and actual_num is not None:
            delta = actual_num - expected_num
            delta_vs_answer_key = "0 (exact match)" if delta == 0 else str(delta)
        else:
            delta_vs_answer_key = "match" if str(answer_key_value) == figure.value_display else "differs"

    delta_vs_firm_a = None
    if firm_a_figure is not None:
        if figure.value_display == firm_a_figure.value_display and figure.status == firm_a_figure.status:
            delta_vs_firm_a = "unchanged from Firm A"
        else:
            delta_vs_firm_a = (
                f"Firm A had {firm_a_figure.value_display} ({firm_a_figure.status}), "
                f"this firm has {figure.value_display} ({figure.status})"
            )

    return ReplayExplanation(
        figure_id=figure.figure_id,
        firm_id=config.firm_id,
        section=figure.section,
        metric=figure.metric,
        value=figure.value_display,
        status=figure.status,
        limit=figure.limit_display,
        utilization=figure.utilization_display,
        graph_path=figure.graph_path,
        source_doc=figure.citation.source_doc if figure.citation else None,
        page=figure.citation.page if figure.citation else None,
        passage=figure.citation.passage_summary if figure.citation else None,
        config_rules=tuple(rules),
        delta_vs_answer_key=delta_vs_answer_key,
        delta_vs_firm_a=delta_vs_firm_a,
    )


def render_explanation(exp: ReplayExplanation) -> str:
    lines = [
        f"{exp.metric}  [{exp.section}]",
        f"  figure_id:    {exp.figure_id}",
        f"  firm:         {exp.firm_id}",
        f"  value:        {exp.value}    status: {exp.status}",
        f"  limit:        {exp.limit}",
        f"  utilization:  {exp.utilization}",
        "",
        "  graph path (figure -> graph path -> source chunk):",
        f"    {exp.graph_path or '(none, this figure is an ERROR)'}",
        "",
        "  source:",
    ]
    if exp.source_doc:
        lines.append(f"    {exp.source_doc}, page {exp.page}")
        lines.append(f'    "{exp.passage}"')
    else:
        lines.append("    (none, this figure could not be traced)")

    lines.append("")
    lines.append("  configuration rule(s) that produced this value:")
    lines += [f"    - {rule}" for rule in exp.config_rules]

    if exp.delta_vs_answer_key is not None:
        lines += ["", f"  delta vs. answer key: {exp.delta_vs_answer_key}"]
    if exp.delta_vs_firm_a is not None:
        lines += ["", f"  vs. Firm A: {exp.delta_vs_firm_a}"]

    return "\n".join(lines)
