"""The migration runner and the pragmas every connection is opened with.

Step 1 of docs/plans/02-domain.md.
"""

import sqlite3

import pytest

from music_tools.db.connection import open_db, transaction
from music_tools.db.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    latest_version,
    migrate,
)

TABLES = {
    "module",
    "exercise",
    "practice_day",
    "practice_entry",
    "media_group",
    "media_source",
}
INDEXES = {
    "exercise_due",
    "exercise_name",
    "entry_day",
    "media_source_group",
    "media_source_exercise",
    "media_group_exercise",
}


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


def test_the_module_table_does_not_track_an_instrument(db):
    # The plan's schema sketch had one, against a second instrument turning up
    # some day. One player, one instrument, and nothing would have read it.
    columns = {row[1] for row in db.execute("PRAGMA table_info(module)")}

    assert "instrument" not in columns
    assert {"name", "slug", "log_group", "position"} <= columns


def test_a_score_attached_before_the_rename_is_carried_over(memory_db):
    # The kind was `musescore` until a PDF turned out to be just as good a
    # score; 003 renames what is already attached rather than stranding it.
    memory_db.executescript(
        "BEGIN;"
        + (MIGRATIONS_DIR / "001_initial.sql").read_text()
        + (MIGRATIONS_DIR / "002_media.sql").read_text()
        + "PRAGMA user_version = 2;COMMIT;"
    )
    with transaction(memory_db):
        memory_db.execute(
            "INSERT INTO module (name, slug, log_group, position)"
            " VALUES ('SONGS', 'songs', 'REPERTOIRE', 0)"
        )
        memory_db.execute(
            "INSERT INTO exercise (module_id, name, practiced_count)"
            " VALUES (1, 'le freak', 0)"
        )
        memory_db.execute(
            "INSERT INTO media_source (exercise_id, kind, path, position, added_at)"
            " VALUES (1, 'musescore', '/tunes/le-freak.mscz', 0, '2026-08-20T21:00')"
        )

    migrate(memory_db)

    kinds = [row[0] for row in memory_db.execute("SELECT kind FROM media_source")]
    assert kinds == ["score"]


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


def test_media_goes_when_the_exercise_it_hangs_off_goes(db):
    # ON DELETE CASCADE, which needs the foreign_keys pragma open_db sets:
    # media is part of an exercise rather than a record of its own.
    db.execute(
        "INSERT INTO module (name, slug, log_group, position) VALUES (?,?,?,?)",
        ("SONGS", "songs", "REPERTOIRE", 1),
    )
    db.execute("INSERT INTO exercise (module_id, name) VALUES (1, 'le freak')")
    db.execute(
        "INSERT INTO media_group (exercise_id, position, added_at)"
        " VALUES (1, 0, '2026-08-17T21:05:00')"
    )
    db.execute(
        "INSERT INTO media_source"
        " (exercise_id, group_id, kind, path, position, added_at)"
        " VALUES (1, 1, 'file', '/tunes/loop.wav', 0, '2026-08-17T21:05:00')"
    )

    db.execute("DELETE FROM exercise WHERE id = 1")

    assert db.execute("SELECT count(*) FROM media_source").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM media_group").fetchone()[0] == 0


def test_a_transaction_rolls_back_on_an_exception(db):
    with pytest.raises(RuntimeError):
        with transaction(db):
            db.execute(
                "INSERT INTO module (name, slug, log_group, position) VALUES (?,?,?,?)",
                ("SLAP", "slap", "TECHNIQUE", 1),
            )
            raise RuntimeError("boom")

    assert db.execute("SELECT count(*) FROM module").fetchone()[0] == 0
