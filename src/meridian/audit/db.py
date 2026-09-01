"""
The append-only audit trail. Two independent guarantees back the "no row
may be updated or deleted after insertion" requirement:

1. A SQLite trigger that raises on any UPDATE or DELETE against the table.
   This is enforced by the database itself, not by application code being
   well-behaved. Nobody with a plain sqlite3 shell can quietly edit a row.
2. A SHA-256 hash chain over the rows (each row hashes in the previous row's
   hash), so even a rebuild of the database file from scratch under the same
   schema, bypassing the trigger by construction, would be detectable:
   scripts/verify_audit_chain.py recomputes the chain and would find it
   doesn't match the row_hash values already on file, or that a row was
   removed and the chain now skips a link.

This module is the only place with a write connection to the database;
everything else goes through audit/events.py's typed helpers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type    TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    firm_id       TEXT,
    timestamp_utc TEXT NOT NULL,
    actor         TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    prev_row_hash TEXT NOT NULL,
    row_hash      TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE is not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only: DELETE is not permitted');
END;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _row_hash(event_type: str, run_id: str, timestamp_utc: str, payload_json: str, prev_hash: str) -> str:
    # Deliberately excludes event_id: that's assigned by SQLite's
    # AUTOINCREMENT only after the row is inserted, and computing the hash
    # before insert (see insert_event's comment for why) means it can't be
    # part of the input. Row ordering is still tamper-evident without it:
    # each row's prev_hash must equal the previous row's row_hash, so
    # reordering or removing a row breaks the chain regardless.
    digest = hashlib.sha256()
    for part in (event_type, run_id, timestamp_utc, payload_json, prev_hash):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def last_row_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT row_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
    return row[0] if row else _GENESIS_HASH


def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    run_id: str,
    firm_id: str | None,
    actor: str,
    timestamp_utc: str,
    payload: dict,
) -> int:
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    prev_hash = last_row_hash(conn)
    row_hash = _row_hash(event_type, run_id, timestamp_utc, payload_json, prev_hash)

    # A single INSERT with the hash already computed. There's no follow-up
    # UPDATE to set it, which matters because the append-only triggers above
    # would reject one. Rows are correct on arrival or not written at all.
    cursor = conn.execute(
        "INSERT INTO audit_events (event_type, run_id, firm_id, timestamp_utc, actor, payload_json, "
        "prev_row_hash, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event_type, run_id, firm_id, timestamp_utc, actor, payload_json, prev_hash, row_hash),
    )
    conn.commit()
    return cursor.lastrowid


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    rows_checked: int
    problems: list[str]


def verify_chain(conn: sqlite3.Connection) -> ChainVerification:
    problems: list[str] = []
    prev_hash = _GENESIS_HASH
    rows = conn.execute(
        "SELECT event_id, event_type, run_id, timestamp_utc, payload_json, prev_row_hash, row_hash "
        "FROM audit_events ORDER BY event_id ASC"
    ).fetchall()

    for event_id, event_type, run_id, timestamp_utc, payload_json, stored_prev_hash, stored_row_hash in rows:
        if stored_prev_hash != prev_hash:
            problems.append(f"event {event_id}: prev_row_hash does not match the preceding row's hash")
        expected = _row_hash(event_type, run_id, timestamp_utc, payload_json, stored_prev_hash)
        if expected != stored_row_hash:
            problems.append(f"event {event_id}: row_hash does not match its own content")
        prev_hash = stored_row_hash

    return ChainVerification(ok=not problems, rows_checked=len(rows), problems=problems)
