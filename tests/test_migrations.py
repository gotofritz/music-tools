"""The migration runner and the pragmas every connection is opened with.

Step 1 of docs/plans/02-domain.md.
"""

import sqlite3

import pytest

from music_tools.db.connection import open_db, transaction
from music_tools.db.migrate import MigrationError, latest_version, migrate

TABLES = {"module", "exercise", "practice_day", "practice_entry"}
INDEXES = {"exercise_due", "exercise_name", "entry_day"}


def names(conn, kind):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
    ).fetchall()
    return {row[0] for row in rows}


def user_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_migrate_creates_the_schema_and_stamps_the_version(memory_db):
    migrate(memory_db)

    assert user_version(memory_db) == latest_version()
    assert TABLES <= names(memory_db, "table")
    assert INDEXES <= names(memory_db, "index")


def test_migrate_is_idempotent(memory_db):
    migrate(memory_db)
    before = user_version(memory_db)

    migrate(memory_db)

    assert user_version(memory_db) == before


def test_a_newer_database_is_refused_rather_than_migrated(memory_db):
    memory_db.execute(f"PRAGMA user_version = {latest_version() + 1}")

    with pytest.raises(MigrationError):
        migrate(memory_db)

    assert TABLES.isdisjoint(names(memory_db, "table"))


def test_open_db_turns_foreign_keys_on_and_uses_wal(tmp_path):
    conn = open_db(tmp_path / "practice.db")

    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_deleting_a_module_with_exercises_fails_on_the_foreign_key(db):
    db.execute(
        "INSERT INTO module (name, slug, log_group, position) VALUES (?,?,?,?)",
        ("SLAP", "slap", "TECHNIQUE", 1),
    )
    db.execute("INSERT INTO exercise (module_id, name) VALUES (1, 'Stomp!')")

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM module WHERE id = 1")


def test_a_transaction_rolls_back_on_an_exception(db):
    with pytest.raises(RuntimeError):
        with transaction(db):
            db.execute(
                "INSERT INTO module (name, slug, log_group, position) VALUES (?,?,?,?)",
                ("SLAP", "slap", "TECHNIQUE", 1),
            )
            raise RuntimeError("boom")

    assert db.execute("SELECT count(*) FROM module").fetchone()[0] == 0
