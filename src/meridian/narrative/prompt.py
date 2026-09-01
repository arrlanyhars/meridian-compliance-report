"""
The only thing narrative/ is allowed to see. build_prompt takes a FigureSet,
already frozen, already rounded, already formatted, and turns it into text.
There's no path from here back into compute/ or the graph; if the LLM
wants a number, it has to be one already sitting in this prompt.
"""

from __future__ import annotations

from meridian.compute.figures import FigureSet

_INSTRUCTIONS = (
    "You are writing a short narrative commentary paragraph for a MAS regulatory compliance report "
    "on a Singapore-domiciled fixed income fund. Below is the full list of already-computed, final "
    "figures for this reporting period.\n\n"
    "Rules: do not invent, estimate, recompute, or re-round any number. Every number you use must be "
    "copied exactly from the list below. Your job is prose commentary only: which figures are "
    "breaches, which are close to their limit, what that means for a compliance reader. Do not restate "
    "every row; focus on what's noteworthy. Write 2-4 plain-English sentences, no markdown, no bullet "
    "points, no headings."
)


def build_prompt(figure_set: FigureSet) -> str:
    lines = [_INSTRUCTIONS, "", f"Firm: {figure_set.firm_name}", ""]
    for fig in figure_set.figures:
        if fig.status == "ERROR":
            lines.append(f"- {fig.metric}: COULD NOT BE COMPUTED ({fig.error_reason})")
            continue
        lines.append(f"- {fig.metric}: value={fig.value_display}, limit={fig.limit_display}, status={fig.status}")
    return "\n".join(lines)
