"""Hand-written SQL in, pydantic models out.

No ORM: the whole schema is four tables and the hot query is
`ORDER BY next_due`. Nothing here opens a transaction — callers that need
several writes to be atomic wrap them in `connection.transaction`.
"""

import json
import re
import sqlite3
from datetime import date, datetime
from typing import Any

from music_tools.domain.models import Exercise, Module, PracticeDay, PracticeEntry

EXERCISE_COLUMNS = (
    "module_id",
    "name",
    "style",
    "speed",
    "target_bpm",
    "practiced_count",
    "last_practiced",
    "next_due",
    "notes",
    "recorded",
    "last_recorded",
    "extra",
    "archived_at",
)

ENTRY_COLUMNS = (
    "day_id",
    "exercise_id",
    "started_at",
    "ended_at",
    "speed",
    "bpm",
    "description",
    "log_group",
    "notes",
)


def _row_id(cursor: sqlite3.Cursor) -> int:
    """SQLite always sets `lastrowid` on an INSERT; the type says maybe."""
    if cursor.lastrowid is None:  # pragma: no cover - not reachable via INSERT
        raise RuntimeError("insert produced no row id")
    return cursor.lastrowid


def _require(model: Any, what: str) -> Any:
    """A row just written, or just updated, is always there to read back."""
    if model is None:  # pragma: no cover - a missing row here is a bug
        raise LookupError(f"{what} vanished between write and read")
    return model


def slugify(name: str) -> str:
    """`BASS SLAP` -> `bass-slap`."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# --- modules ----------------------------------------------------------------


def create_module(
    conn: sqlite3.Connection,
    *,
    name: str,
    log_group: str,
    slug: str | None = None,
    instrument: str = "bass",
    position: int | None = None,
) -> Module:
    if position is None:
        position = conn.execute(
            "SELECT coalesce(max(position), 0) + 1 FROM module"
        ).fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO module (name, slug, log_group, instrument, position)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, slug or slugify(name), log_group, instrument, position),
    )
    return _require(get_module(conn, _row_id(cursor)), "module")


def get_module(conn: sqlite3.Connection, module_id: int) -> Module | None:
    row = conn.execute("SELECT * FROM module WHERE id = ?", (module_id,)).fetchone()
    return Module.model_validate(dict(row)) if row else None


def find_module(conn: sqlite3.Connection, name: str) -> Module | None:
    """By name or slug, case-insensitively — what a CLI argument gives us."""
    row = conn.execute(
        "SELECT * FROM module WHERE lower(name) = ? OR slug = ?",
        (name.lower(), slugify(name)),
    ).fetchone()
    return Module.model_validate(dict(row)) if row else None


def list_modules(conn: sqlite3.Connection) -> list[Module]:
    rows = conn.execute(
        "SELECT * FROM module WHERE archived_at IS NULL ORDER BY position, name"
    ).fetchall()
    return [Module.model_validate(dict(row)) for row in rows]


# --- exercises --------------------------------------------------------------


def create_exercise(
    conn: sqlite3.Connection, *, module_id: int, name: str, **fields
) -> Exercise:
    values = {"module_id": module_id, "name": name, **fields}
    columns = _check_columns(values, EXERCISE_COLUMNS)
    cursor = conn.execute(
        f"INSERT INTO exercise ({', '.join(columns)})"
        f" VALUES ({', '.join('?' for _ in columns)})",
        [_encode(values[column]) for column in columns],
    )
    return _require(get_exercise(conn, _row_id(cursor)), "exercise")


def get_exercise(conn: sqlite3.Connection, exercise_id: int) -> Exercise | None:
    row = conn.execute("SELECT * FROM exercise WHERE id = ?", (exercise_id,)).fetchone()
    return Exercise.model_validate(dict(row)) if row else None


def update_exercise(conn: sqlite3.Connection, exercise_id: int, **fields) -> Exercise:
    columns = _check_columns(fields, EXERCISE_COLUMNS)
    conn.execute(
        f"UPDATE exercise SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
        [_encode(fields[column]) for column in columns] + [exercise_id],
    )
    return _require(get_exercise(conn, exercise_id), "exercise")


def find_exercises(
    conn: sqlite3.Connection, name: str, *, module_id: int | None = None
) -> list[Exercise]:
    """Every live exercise with this name — a name can repeat across modules."""
    sql = (
        "SELECT * FROM exercise WHERE lower(name) = ? AND archived_at IS NULL"
        " AND (? IS NULL OR module_id = ?) ORDER BY module_id"
    )
    rows = conn.execute(sql, (name.strip().lower(), module_id, module_id)).fetchall()
    return [Exercise.model_validate(dict(row)) for row in rows]


def exercises_due(
    conn: sqlite3.Connection,
    *,
    module_id: int | None = None,
    on: date | None = None,
) -> list[Exercise]:
    """`bassReorder`, which turned out to be a query.

    Ordered by due date with undated rows last; archived rows never appear.
    `on` narrows to what is actually due by then, which drops the undated.
    """
    sql = [
        "SELECT * FROM exercise WHERE archived_at IS NULL",
        "AND (? IS NULL OR module_id = ?)",
        "AND (? IS NULL OR (next_due IS NOT NULL AND next_due <= ?))",
        "ORDER BY next_due IS NULL, next_due, name",
    ]
    on_iso = on.isoformat() if on else None
    rows = conn.execute(
        " ".join(sql), (module_id, module_id, on_iso, on_iso)
    ).fetchall()
    return [Exercise.model_validate(dict(row)) for row in rows]


def module_dues(
    conn: sqlite3.Connection, *, module_id: int, excluding: int | None = None
) -> list[date]:
    """The due dates ROTATE and HOLD scan, oldest first.

    `excluding` takes the row being scheduled: HOLD passes it, ROTATE does
    not. The sheet's two scans disagree on exactly this and the port keeps
    both.
    """
    rows = conn.execute(
        "SELECT next_due FROM exercise"
        " WHERE module_id = ? AND next_due IS NOT NULL AND archived_at IS NULL"
        " AND (? IS NULL OR id != ?) ORDER BY next_due",
        (module_id, excluding, excluding),
    ).fetchall()
    return [date.fromisoformat(row[0]) for row in rows]


# --- days and entries -------------------------------------------------------


def create_day(
    conn: sqlite3.Connection, *, day: date, notes: str | None = None
) -> PracticeDay:
    cursor = conn.execute(
        "INSERT INTO practice_day (day, notes) VALUES (?, ?)", (day.isoformat(), notes)
    )
    row = conn.execute(
        "SELECT * FROM practice_day WHERE id = ?", (_row_id(cursor),)
    ).fetchone()
    return PracticeDay.model_validate(dict(row))


def get_day(conn: sqlite3.Connection, day: date) -> PracticeDay | None:
    row = conn.execute(
        "SELECT * FROM practice_day WHERE day = ?", (day.isoformat(),)
    ).fetchone()
    return PracticeDay.model_validate(dict(row)) if row else None


def list_days(conn: sqlite3.Connection) -> list[PracticeDay]:
    rows = conn.execute("SELECT * FROM practice_day ORDER BY day").fetchall()
    return [PracticeDay.model_validate(dict(row)) for row in rows]


def create_entry(
    conn: sqlite3.Connection, *, day_id: int, started_at: datetime, **fields
) -> PracticeEntry:
    values = {"day_id": day_id, "started_at": started_at, **fields}
    columns = _check_columns(values, ENTRY_COLUMNS)
    cursor = conn.execute(
        f"INSERT INTO practice_entry ({', '.join(columns)})"
        f" VALUES ({', '.join('?' for _ in columns)})",
        [_encode(values[column]) for column in columns],
    )
    return _require(get_entry(conn, _row_id(cursor)), "entry")


def get_entry(conn: sqlite3.Connection, entry_id: int) -> PracticeEntry | None:
    row = conn.execute(
        "SELECT * FROM practice_entry WHERE id = ?", (entry_id,)
    ).fetchone()
    return PracticeEntry.model_validate(dict(row)) if row else None


def update_entry(conn: sqlite3.Connection, entry_id: int, **fields) -> PracticeEntry:
    columns = _check_columns(fields, ENTRY_COLUMNS)
    conn.execute(
        f"UPDATE practice_entry SET {', '.join(f'{c} = ?' for c in columns)}"
        " WHERE id = ?",
        [_encode(fields[column]) for column in columns] + [entry_id],
    )
    return _require(get_entry(conn, entry_id), "entry")


def close_entry(
    conn: sqlite3.Connection, entry_id: int, *, ended_at: datetime, **fields
) -> PracticeEntry:
    """Stamp an entry's end, and snapshot what was practised into it."""
    return update_entry(conn, entry_id, ended_at=ended_at, **fields)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM practice_entry WHERE id = ?", (entry_id,))


def running_entry(
    conn: sqlite3.Connection, *, day_id: int | None = None
) -> PracticeEntry | None:
    """The entry with no end — the running clock the sheet kept by hand."""
    row = conn.execute(
        "SELECT * FROM practice_entry WHERE ended_at IS NULL"
        " AND (? IS NULL OR day_id = ?) ORDER BY started_at DESC LIMIT 1",
        (day_id, day_id),
    ).fetchone()
    return PracticeEntry.model_validate(dict(row)) if row else None


def running_entries_before(
    conn: sqlite3.Connection, *, day_id: int
) -> list[PracticeEntry]:
    """Entries still running on some earlier day: time nobody attributed."""
    rows = conn.execute(
        "SELECT * FROM practice_entry WHERE ended_at IS NULL AND day_id != ?",
        (day_id,),
    ).fetchall()
    return [PracticeEntry.model_validate(dict(row)) for row in rows]


def entries_for_day(conn: sqlite3.Connection, day_id: int) -> list[PracticeEntry]:
    rows = conn.execute(
        "SELECT * FROM practice_entry WHERE day_id = ? ORDER BY started_at, id",
        (day_id,),
    ).fetchall()
    return [PracticeEntry.model_validate(dict(row)) for row in rows]


def entry_at(
    conn: sqlite3.Connection, *, day_id: int, started_at: datetime
) -> PracticeEntry | None:
    """The importer's natural key: one entry per day per start time."""
    row = conn.execute(
        "SELECT * FROM practice_entry WHERE day_id = ? AND started_at = ?",
        (day_id, started_at.isoformat()),
    ).fetchone()
    return PracticeEntry.model_validate(dict(row)) if row else None


# --- encoding ---------------------------------------------------------------


def _check_columns(values: dict[str, Any], allowed: tuple[str, ...]) -> list[str]:
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"unknown column(s): {', '.join(sorted(unknown))}")
    return [column for column in allowed if column in values]


def _encode(value: Any) -> Any:
    """Dates as ISO text, `extra` as JSON; SQLite has no type for either."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value
