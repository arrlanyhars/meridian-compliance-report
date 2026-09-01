#!/usr/bin/env python3
"""
A small configuration mini-DSL with a live preview. Type a firm's
method as one line (grammar in src/meridian/config/dsl.py) and see all 13
computed figures update immediately. Nothing is written to disk, and this
calls the exact same compute/engine.py every real run uses, so what shows
up here is exactly what run_report.py would produce for that configuration.

Usage:
  python scripts/config_preview.py
  > gre=parent_issuer fallen_angels=on util=bps
  (figures reprint immediately)
  > :a          (load Firm A's method)
  > :b          (load Firm B's method)
  > :h          (help)
  > :q          (quit)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meridian.cli import CONFIGS_DIR, ingest_and_build_graph  # noqa: E402
from meridian.compute.engine import compute_figure_set  # noqa: E402
from meridian.config.dsl import DslError, parse, to_dsl  # noqa: E402
from meridian.config.schema import FirmConfig  # noqa: E402

_HELP = """
grammar:  gre=issuer|parent_issuer  fallen_angels=on|off  util=percent|bps  epsilon=<number>
          any subset of keys; missing ones keep their current value.

commands: :a   load Firm A's method
          :b   load Firm B's method
          :h   show this help
          :q   quit

anything else is parsed as a config line and every figure is recomputed live.
""".strip()

_STATUS_MARKER = {"OK": "  ", "AT_LIMIT": "! ", "BREACH": "!!", "ERROR": "??"}


def _print_figures(figure_set) -> None:
    print()
    for fig in figure_set.figures:
        marker = _STATUS_MARKER.get(fig.status, "  ")
        print(f"  {marker} {fig.metric:38} {str(fig.value_display):>18}  {fig.status:>9}  util={fig.utilization_display}")


def main() -> int:
    print("Meridian config live preview. Type :h for help, :q to quit.")

    ingestion_time = datetime.now(timezone.utc).isoformat()
    mg = ingest_and_build_graph(ingestion_time)

    firm_a_line = to_dsl(FirmConfig.load(CONFIGS_DIR / "firm_a.yaml"))
    firm_b_line = to_dsl(FirmConfig.load(CONFIGS_DIR / "firm_b.yaml"))
    line = firm_a_line
    _print_figures(compute_figure_set(mg, parse(line)))

    while True:
        try:
            raw = input(f"\n[{line}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not raw:
            continue
        if raw == ":q":
            return 0
        if raw == ":h":
            print(_HELP)
            continue
        if raw == ":a":
            raw = firm_a_line
        elif raw == ":b":
            raw = firm_b_line

        try:
            config = parse(raw)
        except DslError as exc:
            print(f"  parse error: {exc}")
            continue

        line = raw
        _print_figures(compute_figure_set(mg, config))


if __name__ == "__main__":
    raise SystemExit(main())
