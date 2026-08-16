"""The one-off importer: the spreadsheet's history, carried over.

The exports are tab-separated despite the `.csv` extension and carry a long
tail of empty columns on every row. Two shapes:

- **A module sheet** (`BASS SONGS.csv`) — one row per exercise. The module name
  comes from the file name, less the `BASS ` the exports all carry; the first
  header cell gives the log group, which is the `A1` the Apps Script read.
- **The day log** (`BASS.csv`) — one row per entry, in day blocks. `DAY` is
  written only on the first row of a block and `MODULE` only when it changes,
  so both forward-fill. The subtotal and total columns are formula results and
  are ignored, because they are recomputed.

Rows that cannot be parsed are collected into the report and never dropped in
silence. Running it twice changes nothing: exercises key on (module, name),
entries on (day, started_at).
"""

import csv
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from pydantic import BaseModel

from music_tools.db import repository as repo
from music_tools.db.connection import transaction

# Module sheets, from the constants at the top of bass.gs.
COL_SPEED = 0
COL_NAME = 1
COL_STYLE = 2
COL_COUNT = 3
COL_LAST_PRACTICED = 4
COL_NEXT_DUE = 5
COL_NOTES = 6
COL_RECORDED = 7
COL_LAST_RECORDED = 8

# The day log.
COL_DAY = 0
COL_FROM = 1
COL_TO = 2
COL_DURATION = 3  # a formula result: recomputed, never read
COL_SPEED_LOG = 4
COL_DESC = 5
COL_LOG_GROUP = 6

_TRAILING_NOTE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")


class ImportReport(BaseModel):
    """What an import did, and what it could not make sense of."""

    modules_created: int = 0
    exercises_created: int = 0
    exercises_updated: int = 0
    days_created: int = 0
    entries_created: int = 0
    entries_updated: int = 0
    problems: list[str] = []


def split_trailing_note(written: str) -> tuple[str, str | None]:
    """Undo `desc += " (" + notes + ")"`, and leave anything odd alone."""
    match = _TRAILING_NOTE.match(written)
    if match is None or "(" in match.group(1):
        return written, None
    return match.group(1), match.group(2)


def module_name_from(path: Path) -> str:
    """`BASS SONGS.csv` -> `SONGS`.

    Every sheet in the export is named for the instrument and then the module.
    There is only ever one instrument, so the first word is dropped — unless
    it is the whole name, which is the sheet the day log lives on.
    """
    first, _, rest = path.stem.partition(" ")
    return (rest or first).strip()


def import_sheets(
    conn: sqlite3.Connection,
    *,
    modules: Sequence[Path] = (),
    day_log: Path | None = None,
) -> ImportReport:
    """Import module sheets and then the day log, in one transaction."""
    report = ImportReport()
    with transaction(conn):
        for path in modules:
            _import_module(conn, Path(path), report)
        if day_log is not None:
            _import_day_log(conn, Path(day_log), report)
    return report


def read_rows(path: Path) -> Iterator[list[str]]:
    """Tab-separated, with the tail of empty columns trimmed off each row."""
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            while row and not row[-1].strip():
                row.pop()
            yield [cell.strip() for cell in row]


def _import_module(conn: sqlite3.Connection, path: Path, report: ImportReport) -> None:
    rows = list(read_rows(path))
    if not rows:
        report.problems.append(f"{path.name}: empty file")
        return

    name = module_name_from(path)
    log_group = _cell(rows[0], COL_SPEED) or name
    module = repo.find_module(conn, name)
    if module is None:
        module = repo.create_module(conn, name=name, log_group=log_group)
        report.modules_created += 1

    for number, row in enumerate(rows[1:], start=2):
        exercise_name = _cell(row, COL_NAME)
        if not exercise_name:
            continue
        try:
            fields = {
                "style": _cell(row, COL_STYLE) or None,
                "speed": _cell(row, COL_SPEED) or None,
                "practiced_count": int(_cell(row, COL_COUNT) or 0),
                "last_practiced": _parse_date(_cell(row, COL_LAST_PRACTICED)),
                "next_due": _parse_date(_cell(row, COL_NEXT_DUE)),
                "notes": _cell(row, COL_NOTES) or None,
                "recorded": _cell(row, COL_RECORDED) or None,
                "last_recorded": _cell(row, COL_LAST_RECORDED) or None,
                "extra": _extra(rows[0], row),
            }
        except ValueError as error:
            report.problems.append(f"{path.name}:{number}: {error}")
            continue

        existing = repo.find_exercises(conn, exercise_name, module_id=module.id)
        if existing:
            repo.update_exercise(conn, existing[0].id, **fields)
            report.exercises_updated += 1
        else:
            repo.create_exercise(
                conn, module_id=module.id, name=exercise_name, **fields
            )
            report.exercises_created += 1


def _import_day_log(conn: sqlite3.Connection, path: Path, report: ImportReport) -> None:
    day: date | None = None
    log_group: str | None = None

    for number, row in enumerate(read_rows(path), start=1):
        if number == 1 or not any(row):
            continue  # the header, and the blank rows at the end

        if _cell(row, COL_DAY):
            day = _parse_date(_cell(row, COL_DAY))
            log_group = None  # a blank MODULE means "same as above" *in the block*
        if _cell(row, COL_LOG_GROUP):
            log_group = _cell(row, COL_LOG_GROUP)

        started = _cell(row, COL_FROM)
        ended = _cell(row, COL_TO)
        if not started or not ended:
            # The dangling FROM the running clock wrote into the next row.
            # Expected structure, not a mangled row.
            continue
        if day is None:
            report.problems.append(f"{path.name}:{number}: entry before any day")
            continue

        try:
            started_at = datetime.combine(day, _parse_time(started))
            ended_at = datetime.combine(day, _parse_time(ended))
        except ValueError as error:
            report.problems.append(f"{path.name}:{number}: {error}")
            continue
        if ended_at < started_at:
            ended_at += timedelta(days=1)  # the session crossed midnight

        description, notes = split_trailing_note(_cell(row, COL_DESC))
        matches = repo.find_exercises(conn, description) if description else []
        fields = {
            "exercise_id": matches[0].id if len(matches) == 1 else None,
            "ended_at": ended_at,
            "speed": _cell(row, COL_SPEED_LOG) or None,
            "description": description,
            "log_group": log_group,
            "notes": notes,
        }
        if len(matches) > 1:
            report.problems.append(
                f"{path.name}:{number}: '{description}' is in "
                f"{len(matches)} modules; kept as an ad-hoc entry"
            )

        record = repo.get_day(conn, day)
        if record is None:
            record = repo.create_day(conn, day=day)
            report.days_created += 1

        existing = repo.entry_at(conn, day_id=record.id, started_at=started_at)
        if existing:
            repo.update_entry(conn, existing.id, **fields)
            report.entries_updated += 1
        else:
            repo.create_entry(conn, day_id=record.id, started_at=started_at, **fields)
            report.entries_created += 1


def _cell(row: Sequence[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"cannot read the time '{value}'") from None


def _extra(header: Sequence[str], row: Iterable[str]) -> dict[str, str] | None:
    """Per-module oddities past the shared column shape, as JSON (A4)."""
    extra = {
        _cell(header, index) or f"column_{index}": value
        for index, value in enumerate(row)
        if index > COL_LAST_RECORDED and value.strip()
    }
    return extra or None
