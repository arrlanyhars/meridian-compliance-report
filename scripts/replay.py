#!/usr/bin/env python3
"""
Reconciliation / replay viewer. Given a figure, shows its graph path, its
source passage, its delta vs the answer key (or vs Firm A, for Firm B),
and which configuration rule actually produced it.

This recomputes the same FigureSet from the same graph run_report.py uses
(deterministically, see tests/test_determinism.py); it never invents a
number of its own. Entirely read-only.

Usage:
  python scripts/replay.py --firm firm_a                    # list all figures
  python scripts/replay.py --firm firm_a --figure aggregate_non_ig_exposure
  python scripts/replay.py --firm firm_b --figure largest_gre_issuer
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_SCRIPTS))

from meridian.cli import CONFIGS_DIR, REPO_ROOT, ingest_and_build_graph  # noqa: E402
from meridian.compute.engine import compute_figure_set  # noqa: E402
from meridian.config.schema import FirmConfig  # noqa: E402
from meridian.replay.viewer import explain_figure, render_explanation  # noqa: E402
from reconcile import read_answer_key  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--firm", default="firm_a", choices=sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml")))
    parser.add_argument("--figure", help="figure id to replay. Omit to list every figure id for this firm.")
    args = parser.parse_args()

    ingestion_time = datetime.now(timezone.utc).isoformat()
    mg = ingest_and_build_graph(ingestion_time)
    config = FirmConfig.load(CONFIGS_DIR / f"{args.firm}.yaml")
    figure_set = compute_figure_set(mg, config)

    if args.figure is None:
        print(f"figures for --firm {args.firm}:\n")
        for fig in figure_set.figures:
            print(f"  {fig.figure_id:38} {str(fig.value_display):>18}  {fig.status}")
        print("\nrerun with --figure <id> for the full replay of one of them")
        return 0

    try:
        figure = figure_set.by_id(args.figure)
    except KeyError:
        print(f"no figure named {args.figure!r} for --firm {args.firm}. Run without --figure to list them.")
        return 1

    answer_key_value = None
    if config.reconciliation.answer_key_path:
        rows = read_answer_key(REPO_ROOT / config.reconciliation.answer_key_path)
        row = rows.get((figure.section, figure.metric))
        if row:
            answer_key_value = row["value"]

    firm_a_figure = None
    if args.firm != "firm_a":
        firm_a_config = FirmConfig.load(CONFIGS_DIR / "firm_a.yaml")
        firm_a_figure_set = compute_figure_set(mg, firm_a_config)
        firm_a_figure = firm_a_figure_set.by_id(args.figure)

    explanation = explain_figure(figure, config, answer_key_value, firm_a_figure)
    print(render_explanation(explanation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
