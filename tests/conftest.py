"""Shared fixtures.

The marker fixtures are hand-written text, small enough to read in a diff.
Each is offset well into an imaginary recording, because Transcribe! writes
the timestamps of the original track and `Score.build` has to shift them back.

The practice-app fixtures are the other half: an in-memory database, and the
seeded `random.Random` that every scheduling call takes, because nothing in
`domain/` is allowed to reach for the module-level `random`.
"""

import random
from datetime import date, datetime, time
from pathlib import Path

import pytest

from music_tools.db import repository
from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.loop import Score, parse_markers

FIXTURES = Path(__file__).parent / "fixtures"

# Every fixture is written on a half-second beat, so the durations below are
# the ones that make the last bar end exactly where the audio does.
DURATIONS = {
    "d51": 8.0,
    "d51x": 8.0,
    "jackson5": 9.0,
    "pickup": 7.0,
    "endmarker": 6.0,
    # longer than the score: the bare 93 marker closes it at 6.0
    "twoway": 7.0,
}


@pytest.fixture
def fixture_path():
    """Locate a marker fixture by its stem."""

    def locate(name: str) -> Path:
        return FIXTURES / f"{name}.txt"

    return locate


@pytest.fixture
def build_score(fixture_path):
    """Read a marker fixture into a Score, at its natural snippet duration."""

    def build(name: str, duration: float | None = None) -> Score:
        entries = parse_markers(fixture_path(name))
        return Score.build(entries, DURATIONS[name] if duration is None else duration)

    return build


@pytest.fixture
def write_markers(tmp_path):
    """Write marker lines to a file, for the one-off shapes with no fixture."""

    def write(lines: str) -> Path:
        path = tmp_path / "markers.txt"
        path.write_text(lines.strip() + "\n")
        return path

    return write


@pytest.fixture
def d51(build_score):
    """The score every pattern test is written against."""
    return build_score("d51")


@pytest.fixture
def memory_db():
    """A connection with the pragmas set, but no schema."""
    conn = open_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db(memory_db):
    """A migrated, empty practice database."""
    migrate(memory_db)
    return memory_db


@pytest.fixture
def rng():
    """The seeded rng every scheduling call takes; never the global one."""
    return random.Random(20260715)


class SteadyRandom(random.Random):
    """A `random.Random` with the randomness dialled out.

    The scheduler takes an rng rather than reaching for the module-level one,
    which is what makes an exact date assertable. Every draw returns the value
    it was built with.
    """

    def __init__(self, *, uniform_value: float = 0.0, randint_value: int = 0):
        super().__init__(0)
        self.uniform_value = uniform_value
        self.randint_value = randint_value

    def uniform(self, a: float, b: float) -> float:
        return self.uniform_value

    def randint(self, a: int, b: int) -> int:
        return self.randint_value


@pytest.fixture
def steady_rng():
    """No jitter at all: the interval comes out of the table unchanged."""
    return SteadyRandom()


@pytest.fixture
def jittery_rng():
    """Jitter pinned to its positive extreme, for the order-of-operations test."""
    return SteadyRandom(uniform_value=1.0, randint_value=2)


@pytest.fixture
def sample_day(db):
    """A day block copied out of the spreadsheet, as entries.

    The subtotals the spreadsheet's own formulas produced for it are 00:19,
    00:34 and 00:53, which is what the port reproduces. The sheet itself is
    gone; these four rows are the record of what it did.
    """
    day = repository.create_day(db, day=date(2026, 7, 5))
    block = [
        ("22:27", "22:34", "TECHNIQUE", "019 Tempo Builder"),
        ("22:34", "22:46", "TECHNIQUE", "Page 3 The Slap Bass Program"),
        ("22:46", "23:03", "REPERTOIRE", "le freak"),
        ("23:03", "23:20", "REPERTOIRE", "love me jeje"),
    ]
    for started, ended, log_group, description in block:
        entry = repository.create_entry(
            db,
            day_id=day.id,
            started_at=datetime.combine(day.day, time.fromisoformat(started)),
            description=description,
            log_group=log_group,
        )
        repository.close_entry(
            db,
            entry.id,
            ended_at=datetime.combine(day.day, time.fromisoformat(ended)),
            description=description,
            log_group=log_group,
        )
    return day
