#!/usr/bin/env python3
"""
Independently recomputes the audit log's SHA-256 hash chain and checks it
against what's stored on disk. Think of it as the belt to the append-only
triggers' suspenders. A trigger stops a live UPDATE/DELETE through this
connection; this catches a database file that was tampered with some other
way (edited with a raw sqlite3 client against a copy of the file, a row
spliced in by rebuilding the table, etc).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meridian.audit import db as audit_db


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "output" / "audit_log.sqlite3"
    if not db_path.exists():
        print(f"no audit log at {db_path}, run scripts/run_report.py first")
        return 1

    conn = audit_db.connect(db_path)
    result = audit_db.verify_chain(conn)
    conn.close()

    print(f"checked {result.rows_checked} row(s) in {db_path}")
    if result.ok:
        print("chain intact: every row's hash matches its content and links correctly to the previous row")
        return 0

    print(f"chain broken: {len(result.problems)} problem(s) found:")
    for problem in result.problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
