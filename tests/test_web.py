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


# --- Step 3: a module view --------------------------------------------------


def test_a_module_lists_its_queue_due_first(client, songs, le_freak, espresso):
    page = client.get("/modules/songs").text

    assert page.index("le freak") < page.index("espresso")
    assert "SONGS" in page
    assert "x8" in page  # the count
    assert "2026-07-01" in page  # the due date
    assert "overdue" in page  # and that it is one


def test_speed_reads_as_bpm_when_there_is_a_target_and_verbatim_when_not(
    client, songs, le_freak, conn
):
    repo.create_exercise(conn, module_id=songs.id, name="jeje", speed="fastish")

    page = client.get("/modules/songs").text

    assert "87.8 BPM (66%)" in page
    assert "fastish" in page


def test_a_row_with_no_target_is_flagged(client, songs, le_freak, espresso):
    page = client.get("/modules/songs").text
    row = page[page.index('id="exercise-%d"' % espresso.id) :]

    assert "no target" in row[: row.index("</tr>")]


def test_an_unknown_module_is_404(client):
    assert client.get("/modules/nope").status_code == 404


def test_an_archived_row_is_not_in_the_queue(client, conn, songs, le_freak):
    repo.update_exercise(conn, le_freak.id, archived_at=NOW)

    assert "le freak" not in client.get("/modules/songs").text


# --- Step 4: done, in one click ---------------------------------------------


def test_done_moves_the_schedule_and_logs_the_time(client, conn, le_freak):
    client.post("/days", headers=hx())

    response = client.post(f"/exercises/{le_freak.id}/done", headers=hx())

    assert response.status_code == 200
    assert "2026-08-10" in response.text  # 55 days, scaled by the 66% ratio
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    assert after.next_due == date(2026, 8, 10)
    day = repo.get_day(conn, TODAY)
    assert day is not None
    logged = [entry for entry in repo.entries_for_day(conn, day.id) if entry.ended_at]
    assert [entry.description for entry in logged] == ["le freak"]
    assert logged[0].bpm == pytest.approx(87.78)


def test_done_swaps_the_log_and_the_totals_out_of_band(client, le_freak):
    response = client.post(f"/exercises/{le_freak.id}/done", headers=hx())

    assert f'id="exercise-{le_freak.id}"' in response.text
    assert '<section id="day-log" hx-swap-oob="true"' in response.text
    assert '<section id="day-totals" hx-swap-oob="true"' in response.text
    assert '<div id="clock" class="clock" hx-swap-oob="true"' in response.text


def test_hold_leaves_the_front_of_the_queue_where_it_is(
    client, conn, le_freak, espresso
):
    client.post(f"/exercises/{le_freak.id}/done?algorithm=hold", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.next_due == date(2026, 7, 1)  # nothing earlier to jump in front of


def test_rotate_sends_it_past_the_last_date_in_the_module(
    client, conn, le_freak, espresso
):
    client.post(f"/exercises/{le_freak.id}/done?algorithm=rotate", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.next_due == espresso.next_due  # the back of the queue, jitter aside


def test_done_on_an_unknown_exercise_is_404_and_writes_nothing(client, conn):
    response = client.post("/exercises/404/done", headers=hx())

    assert response.status_code == 404
    assert repo.list_days(conn) == []


def test_done_twice_counts_twice(client, conn, le_freak):
    client.post(f"/exercises/{le_freak.id}/done", headers=hx())
    client.post(f"/exercises/{le_freak.id}/done", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    # Not idempotent on purpose: practising something twice in a session is
    # normal, and deduping by exercise would lose the second block of time.
    assert after.practiced_count == 10


def test_an_ad_hoc_entry_logs_time_against_no_exercise(client, conn):
    client.post("/days", headers=hx())

    response = client.post(
        "/entries",
        data={"description": "warm-up", "log_group": "TECHNIQUE"},
        headers=hx(),
    )

    assert response.status_code == 200
    day = repo.get_day(conn, TODAY)
    assert day is not None
    closed = [entry for entry in repo.entries_for_day(conn, day.id) if entry.ended_at]
    assert [(entry.description, entry.exercise_id) for entry in closed] == [
        ("warm-up", None)
    ]


def test_stopping_the_clock_ends_the_session(client, conn):
    client.post("/days", headers=hx())
    day = repo.get_day(conn, TODAY)
    assert day is not None
    running = repo.running_entry(conn, day_id=day.id)
    assert running is not None

    response = client.post(f"/entries/{running.id}/stop", headers=hx())

    assert response.status_code == 200
    assert repo.running_entry(conn, day_id=day.id) is None
    # The tail of a session is time nobody attributed, and the app does not
    # invent an attribution for it — the same rule `restart_clock` follows.
    assert repo.entries_for_day(conn, day.id) == []


def test_stopping_an_unknown_entry_is_404(client):
    assert client.post("/entries/404/stop", headers=hx()).status_code == 404


# --- Step 5: editing in place -----------------------------------------------


def test_editing_the_speed_stores_it_verbatim_and_re_renders_the_row(
    client, conn, le_freak
):
    response = client.patch(
        f"/exercises/{le_freak.id}", data={"speed": "85%"}, headers=hx()
    )

    assert response.status_code == 200
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.speed == "85%"
    assert "113 BPM (85%)" in response.text  # 85% of the 133 target


def test_a_plain_form_post_edits_the_row_too(client, conn, le_freak):
    """HTML forms only send GET and POST; one handler, registered twice."""
    response = client.post(
        f"/exercises/{le_freak.id}", data={"speed": "90"}, headers=hx()
    )

    assert response.status_code == 200
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.speed == "90"


def test_setting_a_target_re_resolves_every_percentage_on_the_row(
    client, conn, espresso
):
    response = client.patch(
        f"/exercises/{espresso.id}", data={"target_bpm": "100"}, headers=hx()
    )

    assert "80 BPM (80%)" in response.text
    after = repo.get_exercise(conn, espresso.id)
    assert after is not None
    assert after.target_bpm == 100.0


def test_renaming_a_row_does_not_rewrite_the_log(client, conn, le_freak):
    client.post(f"/exercises/{le_freak.id}/done", headers=hx())

    client.patch(f"/exercises/{le_freak.id}", data={"name": "Le Freak (Chic)"}, headers=hx())

    day = repo.get_day(conn, TODAY)
    assert day is not None
    closed = [entry for entry in repo.entries_for_day(conn, day.id) if entry.ended_at]
    assert [entry.description for entry in closed] == ["le freak"]


def test_editing_an_unknown_row_is_404(client):
    assert client.patch("/exercises/404", data={"speed": "90"}).status_code == 404


def test_a_name_that_is_already_taken_is_refused(client, conn, le_freak, espresso):
    response = client.patch(
        f"/exercises/{espresso.id}", data={"name": "le freak"}, headers=hx()
    )

    assert response.status_code == 409
    after = repo.get_exercise(conn, espresso.id)
    assert after is not None
    assert after.name == "espresso"


def test_the_tempo_endpoint_resolves_what_is_being_typed(client, le_freak):
    response = client.get(f"/exercises/{le_freak.id}/tempo?written=123/2")

    assert response.status_code == 200
    assert "246 BPM" in response.text


def test_the_tempo_endpoint_stays_quiet_on_half_typed_input(client, le_freak):
    """A keystroke, not a submission: nothing here is an error."""
    response = client.get(f"/exercises/{le_freak.id}/tempo?written=12%2F")

    assert response.status_code == 200
    assert "?" in response.text


def test_adding_an_exercise_puts_it_in_the_module(client, conn, songs):
    response = client.post(
        "/exercises",
        data={"module_id": str(songs.id), "name": "love me jeje", "speed": "70%"},
        headers=hx(),
    )

    assert response.status_code == 200
    added = repo.find_exercises(conn, "love me jeje")
    assert [row.speed for row in added] == ["70%"]
    assert "love me jeje" in response.text


def test_adding_a_row_that_is_already_there_is_refused(client, songs, le_freak):
    response = client.post(
        "/exercises",
        data={"module_id": str(songs.id), "name": "le freak"},
        headers=hx(),
    )

    assert response.status_code == 409
