"""The browser front end: routes in, HTML fragments out.

`docs/plans/03-web.md`. The routes are thin over `domain/session.py` and
`domain/catalogue.py`, so this suite is about what reaches the page — the
markup HTMX swaps on, and the numbers the spreadsheet used to show.

The clock and the rng are dependencies, overridden here the way `cli.py`
injects them, so a test can pin "now" without `freezegun`.
"""

from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from music_tools.db import repository as repo
from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.web.app import create_app
from music_tools.web.deps import get_now, get_rng
from tests.conftest import SteadyRandom

NOW = datetime(2026, 7, 5, 22, 47)
TODAY = date(2026, 7, 5)


@pytest.fixture
def db_path(tmp_path):
    """A migrated database on disk — the app opens its own connections."""
    path = tmp_path / "practice.db"
    conn = open_db(path)
    migrate(conn)
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    """A connection for the test to seed and inspect through."""
    conn = open_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def app(db_path):
    app = create_app(db_path)
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_rng] = lambda: SteadyRandom()
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def hx(**headers: str) -> dict[str, str]:
    """The headers HTMX sends; without them a form POST redirects instead."""
    return {"HX-Request": "true", **headers}


@pytest.fixture
def slap(conn):
    return repo.create_module(conn, name="SLAP", log_group="TECHNIQUE")


@pytest.fixture
def songs(conn):
    return repo.create_module(conn, name="SONGS", log_group="REPERTOIRE")


@pytest.fixture
def le_freak(conn, songs):
    return repo.create_exercise(
        conn,
        module_id=songs.id,
        name="le freak",
        speed="66%",
        target_bpm=133.0,
        practiced_count=8,
        last_practiced=date(2026, 6, 28),
        next_due=date(2026, 7, 1),
    )


@pytest.fixture
def espresso(conn, songs):
    """No target, and a speed that needs one: the row the module view flags."""
    return repo.create_exercise(
        conn,
        module_id=songs.id,
        name="espresso",
        speed="80%",
        practiced_count=2,
        next_due=date(2026, 7, 20),
    )


@pytest.fixture
def sample_block(conn):
    """The 2026-07-05 block of `docs/raw/BASS.csv`: 00:19, 00:34, 00:53."""
    day = repo.create_day(conn, day=TODAY)
    block = [
        ("22:27", "22:34", "TECHNIQUE", "019 Tempo Builder"),
        ("22:34", "22:46", "TECHNIQUE", "Page 3 The Slap Bass Program"),
        ("22:46", "23:03", "REPERTOIRE", "le freak"),
        ("23:03", "23:20", "REPERTOIRE", "love me jeje"),
    ]
    for started, ended, log_group, description in block:
        entry = repo.create_entry(
            conn,
            day_id=day.id,
            started_at=datetime.combine(day.day, time.fromisoformat(started)),
        )
        repo.close_entry(
            conn,
            entry.id,
            ended_at=datetime.combine(day.day, time.fromisoformat(ended)),
            description=description,
            log_group=log_group,
        )
    return day


# --- Step 1: the app factory ------------------------------------------------


def test_the_root_page_is_the_practice_day(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "2026-07-05" in response.text


def test_two_apps_do_not_share_a_database(tmp_path, le_freak, db_path):
    """`create_app(db_path)` is a factory, not a module-level singleton."""
    other = tmp_path / "other.db"
    migrate(open_db(other))

    assert "le freak" in TestClient(create_app(db_path)).get("/").text
    assert "le freak" not in TestClient(create_app(other)).get("/").text


# --- Step 2: today ----------------------------------------------------------


def test_with_no_day_started_the_page_offers_to_start_one(client):
    page = client.get("/").text
    assert 'action="/days"' in page
    assert "start a day" in page.lower()
    assert 'id="entry-' not in page


def test_starting_a_day_opens_a_running_entry(client, conn):
    response = client.post("/days", headers=hx())

    assert response.status_code == 200
    assert "22:47" in response.text
    assert "running" in response.text.lower()
    day = repo.get_day(conn, TODAY)
    assert day is not None
    assert repo.running_entry(conn, day_id=day.id) is not None


def test_starting_a_day_twice_does_not_open_a_second_one(client, conn):
    client.post("/days", headers=hx())
    client.post("/days", headers=hx())

    assert [day.day for day in repo.list_days(conn)] == [TODAY]


def test_a_form_post_without_htmx_redirects_back_to_the_page(client):
    """No JavaScript: a real form, a real redirect, a working app."""
    response = client.post("/days", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_the_log_renders_in_start_order_with_the_sheets_subtotals(
    client, sample_block
):
    page = client.get("/").text

    assert page.index("019 Tempo Builder") < page.index("le freak")
    assert page.index("le freak") < page.index("love me jeje")
    assert "00:19" in page  # TECHNIQUE
    assert "00:34" in page  # REPERTOIRE
    assert "00:53" in page  # the day
    assert "TECHNIQUE" in page and "REPERTOIRE" in page


def test_the_running_entry_counts_up_to_now(client, conn, sample_block):
    """Computed at render, server-side: no clock in the page."""
    repo.create_entry(
        conn,
        day_id=sample_block.id,
        started_at=datetime.combine(TODAY, time(22, 27)),
    )

    page = client.get("/").text

    assert "00:20" in page  # 22:27 to the pinned 22:47


def test_what_is_due_is_listed_and_what_is_not_is_left_out(
    client, le_freak, espresso
):
    page = client.get("/").text

    assert "le freak" in page  # overdue since 2026-07-01
    assert "espresso" not in page  # not due until 2026-07-20


def test_the_due_list_names_the_module_each_row_belongs_to(client, le_freak):
    assert "SONGS" in client.get("/").text
