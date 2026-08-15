"""Opening the practice database, and the one transaction helper.

`sqlite3` from the standard library, no ORM. Two pragmas matter: foreign keys
are off by default in SQLite, which would silently void every `REFERENCES` in
the schema, and WAL keeps a reader (the web app, later) out of the writer's
way.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: Overridable with `MUSIC_TOOLS_DB`; see docs/plans/00-practice-app.md.
DEFAULT_DB_PATH = Path.home() / ".local/share/music-tools/practice.db"


def default_db_path() -> Path:
    """Where the database lives unless `MUSIC_TOOLS_DB` says otherwise."""
    override = os.environ.get("MUSIC_TOOLS_DB")
    return Path(override) if override else DEFAULT_DB_PATH


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a practice database with the pragmas set."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one transaction, rolling back if it raises."""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    conn.commit()
