"""
Figure is the one shape every computed number in the report takes, from the
moment compute/engine.py produces it to the moment reporting/xlsx_writer.py
or narrative/prompt.py reads it. It's frozen on purpose: once engine.py
hands out a FigureSet, nothing downstream, least of all the narrative
layer, can mutate a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from meridian.graph.queries import Citation

VALID_STATUSES = {"OK", "AT_LIMIT", "BREACH", "ERROR"}


@dataclass(frozen=True)
class Figure:
    figure_id: str
    section: str
    metric: str
    status: str
    value_display: str | None
    limit_display: str | None
    utilization_display: str | None
    graph_path: str | None
    citation: Citation | None
    error_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"unknown figure status: {self.status!r}")
        if self.status == "ERROR":
            if self.citation is not None or self.error_reason is None:
                raise ValueError(f"{self.figure_id}: ERROR figures must carry error_reason and no citation")
        elif self.citation is None or self.graph_path is None:
            raise ValueError(f"{self.figure_id}: non-error figures must carry a graph_path and citation")

    def to_dict(self) -> dict:
        d: dict = {
            "figure": self.figure_id,
            "section": self.section,
            "metric": self.metric,
            "value": self.value_display,
            "status": self.status,
            "limit": self.limit_display,
            "utilization": self.utilization_display,
            "graph_path": self.graph_path,
            "citation": (
                {
                    "source_doc": self.citation.source_doc,
                    "page": self.citation.page,
                    "chunk_id": self.citation.chunk_id,
                    "passage_summary": self.citation.passage_summary,
                }
                if self.citation
                else None
            ),
        }
        if self.error_reason:
            d["error_reason"] = self.error_reason
        return d


# Any run of digits (with optional decimal point, comma thousands separators,
# or a leading +/-/±) counts as "a number" for the firewall's purposes. This
# intentionally over-matches rather than under-matches. A false positive in
# the firewall means a narrative sentence gets rejected and retried, which is
# cheap; a false negative means a fabricated number slips through, which is
# the one thing constraint 3 exists to prevent.
_NUMERIC_TOKEN = re.compile(r"[+\-±]?\d[\d,]*(?:\.\d+)?")


def numeric_tokens(text: str) -> set[str]:
    return {m.group(0).lstrip("+-±").replace(",", "") for m in _NUMERIC_TOKEN.finditer(text)}


def error_figure(figure_id: str, section: str, metric: str, reason: str) -> Figure:
    """
    A figure that could not be traced back to a source chunk: returned as an
    explicit error, never silently dropped or defaulted to a guessed value.
    """
    return Figure(
        figure_id=figure_id,
        section=section,
        metric=metric,
        status="ERROR",
        value_display=None,
        limit_display=None,
        utilization_display=None,
        graph_path=None,
        citation=None,
        error_reason=reason,
    )


@dataclass(frozen=True)
class FigureSet:
    firm_id: str
    firm_name: str
    figures: tuple[Figure, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "firm_id": self.firm_id,
            "firm_name": self.firm_name,
            "figures": [f.to_dict() for f in self.figures],
        }

    def by_id(self, figure_id: str) -> Figure:
        for f in self.figures:
            if f.figure_id == figure_id:
                return f
        raise KeyError(figure_id)

    def numeric_surface(self) -> set[str]:
        """
        Every numeric token that legitimately appears anywhere in this
        FigureSet's display fields: the allow-list narrative/firewall.py
        checks generated narrative against. Built once, from the frozen
        figures, so it can't drift from what was actually reported.
        """
        tokens: set[str] = set()
        for fig in self.figures:
            for field_value in (fig.value_display, fig.limit_display, fig.utilization_display):
                if field_value:
                    tokens |= numeric_tokens(field_value)
        return tokens
