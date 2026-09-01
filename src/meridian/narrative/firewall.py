"""
The part of constraint 3 that's verified, not just structurally prevented.
The structural half (compute/ can't import narrative/) stops the LLM from
being *in* the number-producing path. This module is the check that proves
it didn't sneak a number in anyway. Every digit the model wrote has to
already exist in the figures it was handed.
"""

from __future__ import annotations

from dataclasses import dataclass

from meridian.compute.figures import FigureSet, numeric_tokens


@dataclass(frozen=True)
class FirewallReport:
    passed: bool
    violations: tuple[str, ...]
    checked_tokens: int


def check(narrative: str, figure_set: FigureSet) -> FirewallReport:
    found = numeric_tokens(narrative)
    allowed = figure_set.numeric_surface()
    violations = tuple(sorted(found - allowed))
    return FirewallReport(passed=not violations, violations=violations, checked_tokens=len(found))
