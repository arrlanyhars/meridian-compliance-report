#!/usr/bin/env python3
"""
The single entrypoint: `python scripts/run_report.py` (defaults to Firm A)
or `python scripts/run_report.py --firm firm_b`. Everything else about how
the two firms differ lives in configs/, never in a flag here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meridian.cli import CONFIGS_DIR, run_report  # noqa: E402


def _available_firms() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firm", default="firm_a", choices=_available_firms(), help="which configs/<firm>.yaml to run (default: firm_a)")
    parser.add_argument(
        "--strict-review",
        action="store_true",
        help="block the run if the graph review gate has unresolved items (see docs/03_rfc.md)",
    )
    parser.add_argument(
        "--approve-graph",
        action="store_true",
        help="record an explicit human sign-off on the review gate before proceeding",
    )
    args = parser.parse_args()

    outcome = run_report(args.firm, strict_review=args.strict_review, approve_graph=args.approve_graph)

    if outcome.blocked:
        print(f"BLOCKED: run {outcome.run_id} needs graph review before it can proceed.")
        print(f"  {outcome.review_report.auto_passed}/{outcome.review_report.total_chunks} facts auto-passed; "
              f"{len(outcome.review_report.needs_review)} need a human to look at them.")
        print(f"  See output/graph_review_{outcome.run_id}.md, then rerun with --approve-graph.")
        return 1

    print(f"run {outcome.run_id} ({args.firm}) complete")
    print(f"  report:    {outcome.report_path}")
    print(f"  figures:   {outcome.figures_path}")
    print(f"  narrative: {outcome.narrative.status}"
          + (f" (model: {outcome.narrative.model_name})" if outcome.narrative.model_name else ""))
    if not outcome.review_report.clean:
        signed_off = "confirmed via --approve-graph" if args.approve_graph else "accepted by default (no --strict-review)"
        print(f"  graph review: {len(outcome.review_report.needs_review)} item(s) needed a human look, {signed_off}, "
              f"see output/graph_review_{outcome.run_id}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
