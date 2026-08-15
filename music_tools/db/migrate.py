"""Numbered `.sql` migrations, gated by `PRAGMA user_version`.

Each file is `NNN_name.sql`, applied in numeric order inside its own
transaction with the version bumped in the same transaction, so a half-applied
migration cannot exist. A database newer than this code is refused rather than
touched.
"""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NUMBERED = re.compile(r"^(\d+)_")


class MigrationError(RuntimeError):
    """The database cannot be migrated by this version of the code."""


def available_migrations() -> list[tuple[int, Path]]:
    """Every migration file, as (version, path), in order."""
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _NUMBERED.match(path.name)
        if match is None:
            raise MigrationError(f"migration file is not numbered: {path.name}")
        found.append((int(match.group(1)), path))
    return found


def latest_version() -> int:
    """The version an up-to-date database is stamped with."""
    migrations = available_migrations()
    return migrations[-1][0] if migrations else 0


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Bring `conn` up to the newest migration; return the version it is at."""
    version = current_version(conn)
    newest = latest_version()
    if version > newest:
        raise MigrationError(
            f"database is at version {version}, but this code knows {newest}"
        )
    for number, path in available_migrations():
        if number <= version:
            continue
        # executescript() commits any pending transaction, so the BEGIN/COMMIT
        # has to live inside the script itself rather than around it.
        conn.executescript(
            f"BEGIN;\n{path.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;"
        )
        version = number
    return version
