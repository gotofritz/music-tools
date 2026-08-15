"""The models that cross the storage boundary.

Pydantic on the boundary, plain SQL behind it. Vocabulary, once, because the
sheet used one word for three things: a **module** is a practice area (SLAP,
SONGS); a **log group** is the coarser bucket the day log subtotals by
(TECHNIQUE, REPERTOIRE); a **style** is the per-row tag (NEOSOUL, RNB), which
is a label and nothing reads it.
"""

import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, field_validator


class Module(BaseModel):
    """A practice area — one sheet, back when it was a spreadsheet."""

    id: int
    name: str
    slug: str
    log_group: str
    instrument: str = "bass"
    position: int = 0
    archived_at: datetime | None = None


class Exercise(BaseModel):
    """One row of a module: what to practise, how fast, and when next."""

    id: int
    module_id: int
    name: str
    style: str | None = None
    speed: str | None = None  # verbatim, as typed
    target_bpm: float | None = None
    practiced_count: int = 0
    last_practiced: date | None = None
    next_due: date | None = None
    notes: str | None = None
    recorded: str | None = None
    last_recorded: str | None = None
    extra: dict[str, Any] | None = None
    archived_at: datetime | None = None

    @field_validator("extra", mode="before")
    @classmethod
    def _load_json(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value


class PracticeDay(BaseModel):
    """A day of practice, bounded at 4am rather than midnight."""

    id: int
    day: date
    notes: str | None = None


class PracticeEntry(BaseModel):
    """One line of the day log.

    `description`, `speed`, `bpm` and `log_group` are snapshots: the log is a
    record, and renaming an exercise must not rewrite it.
    """

    id: int
    day_id: int
    exercise_id: int | None = None  # null = ad-hoc entry
    started_at: datetime
    ended_at: datetime | None = None  # null = running right now
    speed: str | None = None
    bpm: float | None = None
    description: str = ""
    log_group: str | None = None
    notes: str | None = None


class DoneResult(BaseModel):
    """What `mark_done` did: the schedule moved, and the clock ticked over."""

    exercise: Exercise
    closed: PracticeEntry
    opened: PracticeEntry


class RestartResult(BaseModel):
    """What `restart_clock` did: a fresh entry, and the gap it threw away."""

    opened: PracticeEntry
    dropped_seconds: int


class GroupTotal(BaseModel):
    """A log group's subtotal within a day."""

    log_group: str
    seconds: int


class DaySummary(BaseModel):
    """A day block: its entries, its subtotals and its total."""

    day: date
    entries: list[PracticeEntry] = []
    groups: list[GroupTotal] = []
    total_seconds: int = 0
