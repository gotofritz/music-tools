"""The catalogue: modules, and the rows in them.

A **module** is the fundamental abstraction — a practice area, one sheet back
when this was a spreadsheet. Modules are independent of each other: a queue
per module, scheduled per module, and `next MODULE` is the normal way to ask
what to play. Everything here is about keeping that catalogue in order, as
opposed to `domain/session.py`, which is about a practice session.

Two rules about removing things, and they are the reason this module exists
rather than the CLI calling the repository directly — refusing to delete
something is a decision, and `db/repository.py` does not make those:

- **Archiving is the normal move.** It is reversible, it keeps the day log
  intelligible, and it takes the module's whole queue out of circulation.
- **Deleting is for mistakes**, and stops at anything the day log points at.
  History is not editable through the catalogue.
"""

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from music_tools.db import repository as repo
from music_tools.db.connection import transaction
from music_tools.domain.models import Exercise, Module


class NotFound(LookupError):
    """No module or exercise with that id."""


class InUse(RuntimeError):
    """The change would collide with something, or throw history away."""


class ModuleSummary(BaseModel):
    """A module and the state of its own queue."""

    module: Module
    exercises: int
    due: int
    next_due: date | None


def module_overview(
    conn: sqlite3.Connection, *, today: date, include_archived: bool = False
) -> list[ModuleSummary]:
    """Every module with the size and state of its queue, in module order."""
    summaries = []
    for module in repo.list_modules(conn, include_archived=include_archived):
        exercises = repo.exercises_due(
            conn, module_id=module.id, include_archived=include_archived
        )
        dues = [row.next_due for row in exercises if row.next_due is not None]
        summaries.append(
            ModuleSummary(
                module=module,
                exercises=len(exercises),
                due=sum(1 for due in dues if due <= today),
                next_due=min(dues) if dues else None,
            )
        )
    return summaries


# --- modules ----------------------------------------------------------------


def rename_module(conn: sqlite3.Connection, module_id: int, name: str) -> Module:
    """Rename a module, moving its slug with it."""
    module = _module(conn, module_id)
    clash = repo.find_module(conn, name)
    if clash is not None and clash.id != module.id:
        raise InUse(f"there is already a module called {clash.name}")
    return repo.update_module(conn, module.id, name=name, slug=repo.slugify(name))


def update_module(conn: sqlite3.Connection, module_id: int, **fields) -> Module:
    """Retag or reorder a module. Use `rename_module` for the name."""
    module = _module(conn, module_id)
    if "name" in fields:
        raise ValueError("use rename_module, which moves the slug too")
    return repo.update_module(conn, module.id, **fields)


def archive_module(
    conn: sqlite3.Connection, module_id: int, *, now: datetime
) -> Module:
    """Take a module, and so its whole queue, out of circulation. Reversible."""
    return repo.update_module(conn, _module(conn, module_id).id, archived_at=now)


def restore_module(conn: sqlite3.Connection, module_id: int) -> Module:
    """Put an archived module, and its queue, back."""
    module = _module(conn, module_id, include_archived=True)
    return repo.update_module(conn, module.id, archived_at=None)


def delete_module(
    conn: sqlite3.Connection, module_id: int, *, force: bool = False
) -> None:
    """Delete a module. Empty ones go quietly; `force` takes the rows with it.

    Nothing goes if the day log points at any of those rows: the log is a
    record, and a record with a dangling exercise is worse than a module that
    outstays its welcome. Archive it instead.
    """
    module = _module(conn, module_id, include_archived=True)
    rows = repo.exercises_due(conn, module_id=module.id, include_archived=True)
    if rows and not force:
        rows_said = f"{len(rows)} row" + ("s" if len(rows) != 1 else "")
        raise InUse(
            f"{module.name} still has {rows_said};"
            " archive it, or pass force to take them with it"
        )
    logged = [row for row in rows if repo.count_entries_for_exercise(conn, row.id)]
    if logged:
        raise InUse(
            f"{module.name} has rows in the day log ({logged[0].name});"
            " archive it rather than deleting the history"
        )
    with transaction(conn):
        for row in rows:
            repo.delete_exercise(conn, row.id)
        repo.delete_module(conn, module.id)


# --- rows -------------------------------------------------------------------


def add_exercise(
    conn: sqlite3.Connection, *, module_id: int, name: str, **fields
) -> Exercise:
    """Add a row to a module, refusing a name the module already uses."""
    module = _module(conn, module_id)
    if repo.find_exercises(conn, name, module_id=module.id):
        raise InUse(f"there is already a row called {name} here")
    return repo.create_exercise(conn, module_id=module.id, name=name, **fields)


def update_exercise(conn: sqlite3.Connection, exercise_id: int, **fields) -> Exercise:
    """Edit a row. The day log is a snapshot and does not follow."""
    exercise = _exercise(conn, exercise_id)
    name = fields.get("name")
    if name and name.lower() != exercise.name.lower():
        clash = repo.find_exercises(conn, name, module_id=exercise.module_id)
        if clash:
            raise InUse(f"there is already a row called {clash[0].name} here")
    return repo.update_exercise(conn, exercise.id, **fields)


def move_exercises(
    conn: sqlite3.Connection, exercise_ids: Sequence[int], *, module_id: int
) -> list[Exercise]:
    """Move rows to another module, keeping their schedule and their history.

    The row keeps its id, so its dates, its count, its media and every day-log
    entry pointing at it come with it. The log itself does not follow: an entry
    snapshots its `log_group` when it is started, so finished days read as they
    always did and only what is practised from now on subtotals into the new
    module's group.

    The whole move is one transaction. A name the target already uses stops all
    of it rather than the row it collides with, because a half-finished bulk
    move cannot be read off the page it leaves behind.
    """
    target = _module(conn, module_id)
    rows = [_exercise(conn, exercise_id) for exercise_id in exercise_ids]
    moving = [row for row in rows if row.module_id != target.id]
    _refuse_name_clash(conn, moving, target)
    with transaction(conn):
        moved = {
            row.id: repo.update_exercise(conn, row.id, module_id=target.id)
            for row in moving
        }
    return [moved.get(row.id, row) for row in rows]


def _refuse_name_clash(
    conn: sqlite3.Connection, moving: list[Exercise], target: Module
) -> None:
    """Names are unique within a module, whichever way a row arrives in one."""
    taken: set[str] = set()
    for row in moving:
        name = row.name.strip().lower()
        if name in taken or repo.find_exercises(conn, row.name, module_id=target.id):
            raise InUse(f"there is already a row called {row.name} in {target.name}")
        taken.add(name)


def archive_exercise(
    conn: sqlite3.Connection, exercise_id: int, *, now: datetime
) -> Exercise:
    """Take a row out of the queue, keeping the log it appears in readable."""
    return repo.update_exercise(conn, _exercise(conn, exercise_id).id, archived_at=now)


def restore_exercise(conn: sqlite3.Connection, exercise_id: int) -> Exercise:
    """Put an archived row back, if its name is still free."""
    exercise = _exercise(conn, exercise_id, include_archived=True)
    if repo.find_exercises(conn, exercise.name, module_id=exercise.module_id):
        raise InUse(f"a live row is already called {exercise.name}")
    return repo.update_exercise(conn, exercise.id, archived_at=None)


def delete_exercise(conn: sqlite3.Connection, exercise_id: int) -> None:
    """Delete a row. Refused once the day log points at it."""
    exercise = _exercise(conn, exercise_id, include_archived=True)
    if repo.count_entries_for_exercise(conn, exercise.id):
        raise InUse(
            f"{exercise.name} is in the day log; archive it rather than"
            " deleting the history"
        )
    repo.delete_exercise(conn, exercise.id)


def _module(
    conn: sqlite3.Connection, module_id: int, *, include_archived: bool = False
) -> Module:
    module = repo.get_module(conn, module_id)
    if module is None or (module.archived_at and not include_archived):
        raise NotFound(module_id)
    return module


def _exercise(
    conn: sqlite3.Connection, exercise_id: int, *, include_archived: bool = False
) -> Exercise:
    exercise = repo.get_exercise(conn, exercise_id)
    if exercise is None or (exercise.archived_at and not include_archived):
        raise NotFound(exercise_id)
    return exercise
