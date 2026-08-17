"""Hand-written SQL in, pydantic models out.

No ORM: the whole schema is six tables and the hot query is
`ORDER BY next_due`. Nothing here opens a transaction — callers that need
several writes to be atomic wrap them in `connection.transaction`.
"""

import json
import re
import sqlite3
from datetime import date, datetime
from typing import Any

from music_tools.domain.models import (
    Exercise,
    MediaGroup,
    MediaSource,
    Module,
    PracticeDay,
    PracticeEntry,
)

MODULE_COLUMNS = (
    "name",
    "slug",
    "log_group",
    "position",
    "archived_at",
)

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

MEDIA_GROUP_COLUMNS = (
    "exercise_id",
    "label",
    "position",
    "added_at",
)

MEDIA_SOURCE_COLUMNS = (
    "exercise_id",
    "group_id",
    "kind",
    "path",
    "url",
    "body",
    "label",
    "position",
    "gain",
    "pan",
    "muted",
    "added_at",
)

ENTRY_COLUMNS = (
    "day_id",
    "exercise_id",
    "started_at",  # stamped by start; the gaps between entries are gaps
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
    position: int | None = None,
) -> Module:
    if position is None:
        position = conn.execute(
            "SELECT coalesce(max(position), 0) + 1 FROM module"
        ).fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO module (name, slug, log_group, position) VALUES (?, ?, ?, ?)",
        (name, slug or slugify(name), log_group, position),
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


def list_modules(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> list[Module]:
    rows = conn.execute(
        "SELECT * FROM module WHERE (? OR archived_at IS NULL) ORDER BY position, name",
        (include_archived,),
    ).fetchall()
    return [Module.model_validate(dict(row)) for row in rows]


def update_module(conn: sqlite3.Connection, module_id: int, **fields) -> Module:
    columns = _check_columns(fields, MODULE_COLUMNS)
    conn.execute(
        f"UPDATE module SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
        [_encode(fields[column]) for column in columns] + [module_id],
    )
    return _require(get_module(conn, module_id), "module")


def delete_module(conn: sqlite3.Connection, module_id: int) -> None:
    """Hard delete. The foreign key refuses while any row still points here."""
    conn.execute("DELETE FROM module WHERE id = ?", (module_id,))


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


def delete_exercise(conn: sqlite3.Connection, exercise_id: int) -> None:
    """Hard delete. The foreign key refuses while the log still points here."""
    conn.execute("DELETE FROM exercise WHERE id = ?", (exercise_id,))


def count_entries_for_exercise(conn: sqlite3.Connection, exercise_id: int) -> int:
    return conn.execute(
        "SELECT count(*) FROM practice_entry WHERE exercise_id = ?", (exercise_id,)
    ).fetchone()[0]


def find_exercises(
    conn: sqlite3.Connection,
    name: str,
    *,
    module_id: int | None = None,
    include_archived: bool = False,
) -> list[Exercise]:
    """Every live exercise with this name — a name can repeat across modules."""
    sql = (
        "SELECT * FROM exercise WHERE lower(name) = ?"
        " AND (? OR archived_at IS NULL)"
        " AND (? IS NULL OR module_id = ?) ORDER BY module_id"
    )
    rows = conn.execute(
        sql, (name.strip().lower(), include_archived, module_id, module_id)
    ).fetchall()
    return [Exercise.model_validate(dict(row)) for row in rows]


def exercises_due(
    conn: sqlite3.Connection,
    *,
    module_id: int | None = None,
    on: date | None = None,
    include_archived: bool = False,
) -> list[Exercise]:
    """`bassReorder`, which turned out to be a query.

    Ordered by due date with undated rows last. Archived rows never appear,
    and neither do the rows of an archived module: a module is the unit, so
    archiving one takes its whole queue out of circulation. `on` narrows to
    what is actually due by then, which drops the undated.
    """
    sql = [
        "SELECT exercise.* FROM exercise",
        "JOIN module ON module.id = exercise.module_id",
        "WHERE (? OR (exercise.archived_at IS NULL AND module.archived_at IS NULL))",
        "AND (? IS NULL OR module_id = ?)",
        "AND (? IS NULL OR (next_due IS NOT NULL AND next_due <= ?))",
        "ORDER BY next_due IS NULL, next_due, exercise.name",
    ]
    on_iso = on.isoformat() if on else None
    rows = conn.execute(
        " ".join(sql), (include_archived, module_id, module_id, on_iso, on_iso)
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


# --- media ------------------------------------------------------------------


def create_media_group(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    position: int,
    added_at: datetime,
    label: str | None = None,
) -> MediaGroup:
    cursor = conn.execute(
        "INSERT INTO media_group (exercise_id, label, position, added_at)"
        " VALUES (?, ?, ?, ?)",
        (exercise_id, label, position, added_at.isoformat()),
    )
    return _require(get_media_group(conn, _row_id(cursor)), "media group")


def get_media_group(conn: sqlite3.Connection, group_id: int) -> MediaGroup | None:
    row = conn.execute("SELECT * FROM media_group WHERE id = ?", (group_id,)).fetchone()
    return MediaGroup.model_validate(dict(row)) if row else None


def media_groups_for_exercise(
    conn: sqlite3.Connection, *, exercise_id: int
) -> list[MediaGroup]:
    rows = conn.execute(
        "SELECT * FROM media_group WHERE exercise_id = ? ORDER BY position, id",
        (exercise_id,),
    ).fetchall()
    return [MediaGroup.model_validate(dict(row)) for row in rows]


def update_media_group(conn: sqlite3.Connection, group_id: int, **fields) -> MediaGroup:
    columns = _check_columns(fields, MEDIA_GROUP_COLUMNS)
    conn.execute(
        f"UPDATE media_group SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
        [_encode(fields[column]) for column in columns] + [group_id],
    )
    return _require(get_media_group(conn, group_id), "media group")


def delete_media_group(conn: sqlite3.Connection, group_id: int) -> None:
    """The group, and — through the cascade — whatever still plays in it."""
    conn.execute("DELETE FROM media_group WHERE id = ?", (group_id,))


def create_media_source(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    kind: str,
    position: int,
    added_at: datetime,
    **fields,
) -> MediaSource:
    values = {
        "exercise_id": exercise_id,
        "kind": kind,
        "position": position,
        "added_at": added_at,
        **fields,
    }
    columns = _check_columns(values, MEDIA_SOURCE_COLUMNS)
    cursor = conn.execute(
        f"INSERT INTO media_source ({', '.join(columns)})"
        f" VALUES ({', '.join('?' for _ in columns)})",
        [_encode(values[column]) for column in columns],
    )
    return _require(get_media_source(conn, _row_id(cursor)), "media source")


def get_media_source(conn: sqlite3.Connection, source_id: int) -> MediaSource | None:
    row = conn.execute(
        "SELECT * FROM media_source WHERE id = ?", (source_id,)
    ).fetchone()
    return MediaSource.model_validate(dict(row)) if row else None


def media_sources_for_exercise(
    conn: sqlite3.Connection, *, exercise_id: int
) -> list[MediaSource]:
    rows = conn.execute(
        "SELECT * FROM media_source WHERE exercise_id = ? ORDER BY position, id",
        (exercise_id,),
    ).fetchall()
    return [MediaSource.model_validate(dict(row)) for row in rows]


def media_sources_in_group(
    conn: sqlite3.Connection, *, group_id: int
) -> list[MediaSource]:
    """The tracks of one set, in the order they play down the mixer strip."""
    rows = conn.execute(
        "SELECT * FROM media_source WHERE group_id = ? ORDER BY position, id",
        (group_id,),
    ).fetchall()
    return [MediaSource.model_validate(dict(row)) for row in rows]


def update_media_source(
    conn: sqlite3.Connection, source_id: int, **fields
) -> MediaSource:
    columns = _check_columns(fields, MEDIA_SOURCE_COLUMNS)
    conn.execute(
        f"UPDATE media_source SET {', '.join(f'{c} = ?' for c in columns)}"
        " WHERE id = ?",
        [_encode(fields[column]) for column in columns] + [source_id],
    )
    return _require(get_media_source(conn, source_id), "media source")


def delete_media_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM media_source WHERE id = ?", (source_id,))


def next_media_position(conn: sqlite3.Connection, *, exercise_id: int) -> int:
    """Where the next card goes: one past whatever is furthest down already.

    Two tables carry the exercise-level order — a group for the files, the
    source itself for everything else — so the next position is the maximum of
    both. Members of a set are ordered by their own position within the group.
    """
    groups = conn.execute(
        "SELECT coalesce(max(position), -1) FROM media_group WHERE exercise_id = ?",
        (exercise_id,),
    ).fetchone()[0]
    sources = conn.execute(
        "SELECT coalesce(max(position), -1) FROM media_source"
        " WHERE exercise_id = ? AND group_id IS NULL",
        (exercise_id,),
    ).fetchone()[0]
    return max(groups, sources) + 1


def next_track_position(conn: sqlite3.Connection, *, group_id: int) -> int:
    """Where the next track goes in a set."""
    return (
        conn.execute(
            "SELECT coalesce(max(position), -1) FROM media_source WHERE group_id = ?",
            (group_id,),
        ).fetchone()[0]
        + 1
    )


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


def days_before(
    conn: sqlite3.Connection, *, before: date, limit: int
) -> list[PracticeDay]:
    """The days strictly before `before`, most recent first: a page of history."""
    rows = conn.execute(
        "SELECT * FROM practice_day WHERE day < ? ORDER BY day DESC LIMIT ?",
        (before.isoformat(), limit),
    ).fetchall()
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
