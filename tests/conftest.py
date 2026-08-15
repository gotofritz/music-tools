"""Shared fixtures.

The marker fixtures are hand-written text, small enough to read in a diff.
Each is offset well into an imaginary recording, because Transcribe! writes
the timestamps of the original track and `Score.build` has to shift them back.

The practice-app fixtures are the other half: an in-memory database, and the
seeded `random.Random` that every scheduling call takes, because nothing in
`domain/` is allowed to reach for the module-level `random`.
"""

import random
from pathlib import Path

import pytest

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
