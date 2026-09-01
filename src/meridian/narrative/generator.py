"""
Ties prompt.py, llm_client.py and firewall.py together. A firewall violation
isn't treated as "drop the sentence and move on quietly". That would let a
fabricated number slip through unnoticed on a bad day. Instead: retry once
with the offending numbers named, and if it still fails, the run reports
that narrative generation failed rather than emitting anything unverified.
"""

from __future__ import annotations

from dataclasses import dataclass

from meridian.compute.figures import FigureSet
from meridian.narrative.firewall import FirewallReport, check
from meridian.narrative.llm_client import LLMClient
from meridian.narrative.prompt import build_prompt

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class NarrativeResult:
    status: str  # OK | SKIPPED_NO_API_KEY | FIREWALL_FAILED | GENERATION_FAILED
    text: str | None
    model_name: str | None
    firewall_report: FirewallReport | None
    attempts: int


def generate_narrative(client: LLMClient | None, figure_set: FigureSet) -> NarrativeResult:
    if client is None:
        return NarrativeResult("SKIPPED_NO_API_KEY", None, None, None, attempts=0)

    base_prompt = build_prompt(figure_set)
    prompt = base_prompt
    last_report: FirewallReport | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = client.generate(prompt)
        except Exception:
            return NarrativeResult("GENERATION_FAILED", None, client.model_name, None, attempts=attempt)

        last_report = check(text, figure_set)
        if last_report.passed:
            return NarrativeResult("OK", text, client.model_name, last_report, attempts=attempt)

        prompt = (
            base_prompt
            + "\n\nYour previous answer used number(s) that don't appear in the list above: "
            + ", ".join(last_report.violations)
            + ". Rewrite the paragraph using only numbers copied verbatim from the list."
        )

    return NarrativeResult("FIREWALL_FAILED", None, client.model_name, last_report, attempts=MAX_ATTEMPTS)
