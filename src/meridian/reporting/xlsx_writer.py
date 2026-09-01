"""
Fills report_template.xlsx's exact row shape. Rows are matched by
(section, metric) text rather than row position. The template happens to
list rows in the same order compute/engine.py produces them today, but
matching on the label pair means a reordered template still lines up
correctly, and a mismatch (a template row nothing computed, or a computed
figure with no template row) fails loudly instead of silently writing to
the wrong line.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from meridian.compute.figures import Figure, FigureSet
from meridian.compute.rounding import display_status

_HEADER_ROW = 1
_COLUMNS = ("section", "metric", "value", "limit", "utilization", "status", "source")


def _source_cell(fig: Figure) -> str:
    if fig.status == "ERROR":
        return f"ERROR: {fig.error_reason}"
    return f"{fig.graph_path} -> {fig.citation.source_doc} p.{fig.citation.page}"


def write_report(template_path: str | Path, output_path: str | Path, figure_set: FigureSet) -> None:
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    by_key = {(f.section, f.metric): f for f in figure_set.figures}
    matched: set[tuple[str, str]] = set()

    for row in ws.iter_rows(min_row=_HEADER_ROW + 1):
        section, metric = row[0].value, row[1].value
        if section is None and metric is None:
            continue
        key = (section, metric)
        fig = by_key.get(key)
        if fig is None:
            raise ValueError(
                f"report_template.xlsx row (section={section!r}, metric={metric!r}) has no matching "
                "computed figure. Either the template changed or engine.py is missing a figure"
            )
        matched.add(key)

        value_display = fig.value_display if fig.status != "ERROR" else "ERROR"
        row[2].value = value_display
        row[3].value = fig.limit_display
        row[4].value = fig.utilization_display
        row[5].value = display_status(fig.status)
        row[6].value = _source_cell(fig)

    missing = set(by_key) - matched
    if missing:
        raise ValueError(f"computed figures with no matching template row: {sorted(missing)}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
