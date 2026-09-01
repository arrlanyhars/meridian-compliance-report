"""The append-only guarantee, checked against a real SQLite connection rather than assumed from the schema."""

import sqlite3

import pytest

from meridian.audit import db as audit_db


@pytest.fixture
def conn(tmp_path):
    connection = audit_db.connect(tmp_path / "audit_log.sqlite3")
    audit_db.insert_event(connection, "graph_construction", "run-1", None, "system", "2026-01-01T00:00:00Z", {"nodes": 1})
    audit_db.insert_event(connection, "export", "run-1", "firm_a", "system", "2026-01-01T00:00:01Z", {"path": "x"})
    yield connection
    connection.close()


def test_update_is_rejected(conn):
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_events SET actor = 'tampered' WHERE event_id = 1")


def test_delete_is_rejected(conn):
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_events WHERE event_id = 1")


def test_hash_chain_verifies_on_untouched_data(conn):
    result = audit_db.verify_chain(conn)
    assert result.ok
    assert result.rows_checked == 2


def test_hash_chain_catches_a_row_spliced_in_by_bypassing_the_trigger(tmp_path):
    """
    The trigger stops a live UPDATE through this connection. This proves the
    second, independent layer, the hash chain, catches tampering that
    doesn't go through the trigger at all: a fresh row inserted directly
    with a forged prev_row_hash, the way someone editing the raw file with
    a different tool might do it.
    """
    connection = audit_db.connect(tmp_path / "audit_log.sqlite3")
    audit_db.insert_event(connection, "graph_construction", "run-1", None, "system", "2026-01-01T00:00:00Z", {"nodes": 1})

    connection.execute(
        "INSERT INTO audit_events (event_type, run_id, firm_id, timestamp_utc, actor, payload_json, "
        "prev_row_hash, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("export", "run-1", "firm_a", "2026-01-01T00:00:01Z", "system", "{}", "forged-prev-hash", "forged-row-hash"),
    )
    connection.commit()

    result = audit_db.verify_chain(connection)
    assert not result.ok
    assert result.problems
    connection.close()
