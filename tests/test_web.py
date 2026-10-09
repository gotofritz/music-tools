"""The browser front end: routes in, HTML fragments out.

`docs/plans/03-web.md`. The routes are thin over `domain/session.py` and
`domain/catalogue.py`, so this suite is about what reaches the page — the
markup HTMX swaps on, and the numbers the spreadsheet used to show.

The clock and the rng are dependencies, overridden here the way `cli.py`
injects them, so a test can pin "now" without `freezegun`.
"""

import re
from datetime import date, datetime, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from music_tools.db import repository as repo
from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.domain import media, session
from music_tools.web import deps
from music_tools.web.app import create_app
from music_tools.web.deps import get_now, get_rng
from music_tools.web.views import PAGE_OF_DAYS
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


def start(client, exercise_id: int, **headers: str):
    """Playing it now: the click a module row's start button sends."""
    return client.post(f"/exercises/{exercise_id}/start", headers=hx(**headers))


def stop(client, exercise_id: int, **headers: str):
    """Finished with it: the click a module row's stop button sends."""
    return client.post(f"/exercises/{exercise_id}/stop", headers=hx(**headers))


def running(conn):
    """The entry being practised, straight out of the database."""
    day = repo.get_day(conn, TODAY)
    return repo.running_entry(conn, day_id=day.id) if day else None


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
    """The `sample_day` block, as the spreadsheet totalled it: 00:19, 00:34, 00:53."""
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


def test_the_templates_are_read_once_with_the_code_that_answers_them():
    # a running server that picks up new markup while still running the old
    # routes swaps fragments into targets those routes know nothing about
    assert deps.env.auto_reload is False


def test_the_root_page_is_the_practice_day(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "2026-07-05" in response.text


def test_two_apps_do_not_share_a_database(tmp_path, le_freak, db_path):
    """`create_app(db_path)` is a factory, not a module-level singleton."""
    other = tmp_path / "other.db"
    migrate(open_db(other))

    assert "le freak" in TestClient(create_app(db_path)).get("/modules/songs").text
    assert TestClient(create_app(other)).get("/modules/songs").status_code == 404


# --- Step 2: today ----------------------------------------------------------


def test_with_nothing_running_there_are_no_entries_and_no_clock_to_stop(client):
    page = client.get("/").text
    assert 'id="entry-' not in page
    assert "stop the clock" not in page  # there is no clock to stop any more


def test_starting_an_exercise_logs_it_straight_away(client, conn, le_freak):
    response = start(client, le_freak.id, referer="http://localhost/modules/songs")

    assert response.status_code == 200
    entry = running(conn)
    assert entry is not None
    assert entry.description == "le freak"
    assert entry.started_at == NOW
    # started, not scheduled: the count only moves when it is done
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 8


def test_the_running_entry_is_a_card_on_the_today_page(client, conn, le_freak):
    start(client, le_freak.id)

    page = client.get("/").text

    assert 'id="now-playing"' in page
    assert "le freak" in page
    assert "since 22:47" in page
    assert f'action="/entries/{running(conn).id}/done"' in page
    assert f'action="/entries/{running(conn).id}/discard"' in page


def test_starting_the_next_one_closes_the_one_before_it(
    client, conn, le_freak, espresso
):
    start(client, le_freak.id)

    start(client, espresso.id)

    day = repo.get_day(conn, TODAY)
    assert day is not None
    entries = repo.entries_for_day(conn, day.id)
    assert [(entry.description, entry.ended_at is None) for entry in entries] == [
        ("le freak", False),
        ("espresso", True),
    ]


def test_starting_the_next_one_schedules_the_one_it_closed(
    client, conn, le_freak, espresso
):
    start(client, le_freak.id)

    start(client, espresso.id)

    # closed by the next start, and scheduled the normal way: nothing else will
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    assert after.next_due == date(2026, 8, 10)


def test_a_form_post_without_htmx_redirects_back_to_the_page(client, le_freak):
    """No JavaScript: a real form, a real redirect, a working app."""
    response = client.post(f"/exercises/{le_freak.id}/start", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_starting_an_exercise_that_is_not_there_is_404(client, conn):
    response = client.post("/exercises/404/start", headers=hx())

    assert response.status_code == 404
    assert repo.list_days(conn) == []


def test_the_log_renders_in_start_order_with_the_sheets_subtotals(client, sample_block):
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


def test_the_nav_names_every_module(client, songs, slap):
    page = client.get("/").text

    assert 'href="/modules/songs"' in page
    assert 'href="/modules/slap"' in page


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
    start(client, le_freak.id)

    response = client.post(f"/entries/{running(conn).id}/done", headers=hx())

    assert response.status_code == 200
    assert "le freak" in response.text  # the line it closed, in today's log
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    assert after.next_due == date(2026, 8, 10)
    day = repo.get_day(conn, TODAY)
    assert day is not None
    logged = [entry for entry in repo.entries_for_day(conn, day.id) if entry.ended_at]
    assert [entry.description for entry in logged] == ["le freak"]
    assert logged[0].bpm == pytest.approx(87.78)


def test_done_answers_with_the_log_and_swaps_the_totals_out_of_band(
    client, conn, le_freak
):
    start(client, le_freak.id)

    response = client.post(
        f"/entries/{running(conn).id}/done", headers=hx(referer="http://localhost/")
    )

    assert '<section id="day-log"' in response.text
    assert '<section id="day-totals" hx-swap-oob="true"' in response.text
    assert 'id="clock"' not in response.text  # the clock is gone, card and all


def test_done_from_a_module_page_answers_with_the_row(client, conn, le_freak, songs):
    start(client, le_freak.id)

    response = client.post(
        f"/entries/{running(conn).id}/done",
        headers=hx(referer=f"http://localhost/modules/{songs.slug}"),
    )

    assert f'id="exercise-{le_freak.id}"' in response.text
    assert "start" in response.text  # finished, so the row offers a start again
    assert '<section id="day-log"' not in response.text
    assert '<section id="day-totals" hx-swap-oob="true"' in response.text


def test_hold_leaves_the_front_of_the_queue_where_it_is(
    client, conn, le_freak, espresso
):
    start(client, le_freak.id)

    client.post(f"/entries/{running(conn).id}/done?algorithm=hold", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.next_due == date(2026, 7, 1)  # nothing earlier to jump in front of


def test_rotate_sends_it_past_the_last_date_in_the_module(
    client, conn, le_freak, espresso
):
    start(client, le_freak.id)

    client.post(f"/entries/{running(conn).id}/done?algorithm=rotate", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.next_due == espresso.next_due  # the back of the queue, jitter aside


def test_done_on_an_unknown_entry_is_404_and_writes_nothing(client, conn):
    response = client.post("/entries/404/done", headers=hx())

    assert response.status_code == 404
    assert repo.list_days(conn) == []


def test_done_on_a_finished_line_is_409(client, conn, le_freak):
    start(client, le_freak.id)
    entry_id = running(conn).id
    client.post(f"/entries/{entry_id}/done", headers=hx())

    response = client.post(f"/entries/{entry_id}/done", headers=hx())

    assert response.status_code == 409
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9  # counted once, not twice


def test_done_twice_counts_twice(client, conn, le_freak):
    start(client, le_freak.id)
    client.post(f"/entries/{running(conn).id}/done", headers=hx())
    start(client, le_freak.id)
    client.post(f"/entries/{running(conn).id}/done", headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    # Not idempotent on purpose: practising something twice in a session is
    # normal, and deduping by exercise would lose the second block of time.
    assert after.practiced_count == 10


def test_a_false_start_is_discarded_and_logs_nothing(client, conn, le_freak):
    start(client, le_freak.id)
    entry_id = running(conn).id

    response = client.post(f"/entries/{entry_id}/discard", headers=hx())

    assert response.status_code == 200
    day = repo.get_day(conn, TODAY)
    assert day is not None
    assert repo.entries_for_day(conn, day.id) == []
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 8  # nothing was practised, so nothing moved


def test_discarding_a_finished_line_is_409(client, conn, le_freak):
    start(client, le_freak.id)
    entry_id = running(conn).id
    client.post(f"/entries/{entry_id}/done", headers=hx())

    response = client.post(f"/entries/{entry_id}/discard", headers=hx())

    assert response.status_code == 409
    assert repo.get_entry(conn, entry_id) is not None


def test_discarding_an_unknown_entry_is_404(client):
    assert client.post("/entries/404/discard", headers=hx()).status_code == 404


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
    start(client, le_freak.id)
    client.post(f"/entries/{running(conn).id}/done", headers=hx())

    client.patch(
        f"/exercises/{le_freak.id}", data={"name": "Le Freak (Chic)"}, headers=hx()
    )

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


def test_a_new_row_is_due_straight_away(client, conn, songs):
    """A row added mid-session is something to play now, not an undated one.

    Everything that asks what is due — `practice next`, the due count on
    `module list` — reads a date, so an undated row is invisible to all of
    them. A row typed in during a session is due in that session.
    """
    client.post(
        "/exercises",
        data={"module_id": str(songs.id), "name": "love me jeje"},
        headers=hx(),
    )

    added = repo.find_exercises(conn, "love me jeje")
    assert [row.next_due for row in added] == [TODAY]
    assert repo.exercises_due(conn, on=TODAY) == added


def test_the_empty_boxes_on_a_row_say_what_they_are_for(client, songs, le_freak):
    """A blank input in a table is a mystery; the label is only for readers."""
    page = client.get("/modules/songs").text
    row = page[page.index('id="exercise-%d"' % le_freak.id) :]
    row = row[: row.index("</tr>")]

    assert 'placeholder="80% or 96"' in row  # speed
    assert 'placeholder="target BPM"' in row
    assert 'placeholder="notes"' in row


# --- the days before today, under today -------------------------------------


@pytest.fixture
def earlier_days(conn):
    """A page of finished days and one more, before the pinned one."""
    for number in range(1, PAGE_OF_DAYS + 2):
        day = date(2026, 6, number)
        record = repo.create_day(conn, day=day)
        entry = repo.create_entry(
            conn, day_id=record.id, started_at=datetime(2026, 6, number, 20)
        )
        repo.close_entry(
            conn,
            entry.id,
            ended_at=datetime(2026, 6, number, 20, 15),
            description=f"day {number}",
            log_group="TECHNIQUE",
        )
    return None


def test_today_shows_the_days_before_it_newest_first(client, earlier_days):
    page = client.get("/").text

    assert page.index("2026-06-06") < page.index("2026-06-05")
    assert "00:15" in page  # each day's total
    assert "day 6" in page  # and what was played


def test_today_no_longer_lists_what_is_due(client, le_freak):
    """The queue belongs to the module pages; today is the log."""
    page = client.get("/").text

    assert "le freak" not in page
    assert 'href="/modules/songs"' in page  # still one click away


def test_only_a_page_of_days_is_shown_with_a_way_to_get_more(client, earlier_days):
    page = client.get("/").text

    assert "2026-06-01" not in page  # the oldest, one past the page
    assert "load more" in page
    assert 'href="/days?before=2026-06-02"' in page  # carry on from the last shown


def test_load_more_returns_the_next_page_and_its_own_button(client, earlier_days):
    response = client.get("/days?before=2026-06-02", headers=hx())

    assert response.status_code == 200
    assert "2026-06-01" in response.text
    assert "2026-06-06" not in response.text  # the page above it, not repeated
    assert "load more" not in response.text  # nothing older to ask for


def test_the_load_more_link_is_a_whole_page_without_htmx(client, earlier_days):
    """No JavaScript: a real link to a real page, not a naked fragment."""
    response = client.get("/days?before=2026-06-02")

    assert "<html" in response.text
    assert "2026-06-01" in response.text


def test_a_day_with_no_history_behind_it_offers_nothing_to_load(client):
    assert "load more" not in client.get("/").text


# --- earlier days are collapsed (Phase 10, step 1) -----------------------------


def _details(page: str) -> list[str]:
    return re.findall(r"<details\b[^>]*>", page)


def test_every_earlier_day_is_a_collapsed_details_with_a_summary(client, earlier_days):
    page = client.get("/").text

    tags = _details(page)
    assert len(tags) == PAGE_OF_DAYS
    assert all(" open" not in tag for tag in tags)
    assert page.count("<summary") == PAGE_OF_DAYS
    summary = re.search(r"<summary.*?</summary>", page, re.S)
    assert summary is not None
    assert "2026-06-21" in summary.group(0)  # newest first
    assert "00:15" in summary.group(0)
    assert "TECHNIQUE" in summary.group(0)


def test_todays_log_is_not_collapsible(client, sample_block):
    page = client.get("/").text
    assert "00:19" in page
    log = page[page.index('id="day-log"') : page.index('id="history"')]

    assert "<details" not in log


def test_one_button_flips_collapse_all_and_expand_all(client, earlier_days):
    page = client.get("/").text

    assert page.count('id="toggle-days"') == 1
    assert "expand all" in page  # every load starts collapsed


def test_no_toggle_when_there_is_no_history(client):
    assert "toggle-days" not in client.get("/").text


def test_load_more_days_arrive_as_collapsed_details(client, earlier_days):
    page = client.get("/days?before=2026-06-02", headers=hx()).text

    assert len(_details(page)) == 1
    assert " open" not in _details(page)[0]


def test_a_day_page_is_open_and_its_edits_redraw_it_open(client, conn, earlier_days):
    page = client.get("/days/2026-06-06").text
    assert _details(page)
    assert all(" open" in tag for tag in _details(page))

    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.entries_for_day(conn, day.id)[0]
    amended = client.patch(
        f"/entries/{entry.id}", data={"notes": "x"}, headers=hx()
    ).text
    assert _details(amended)
    assert all(" open" in tag for tag in _details(amended))


# --- the picker (Phase 10, step 2) ---------------------------------------------


def test_the_picker_is_one_button_per_live_module_in_tab_order(
    client, conn, slap, songs
):
    archived = repo.create_module(conn, name="OLD", log_group="TECHNIQUE")
    repo.update_module(conn, archived.id, archived_at=NOW)

    page = client.get("/picker", headers=hx()).text

    assert page.index("SLAP") < page.index("SONGS")
    assert "OLD" not in page
    assert 'hx-get="/picker/slap"' in page
    assert 'hx-get="/picker/songs"' in page
    assert "<table" not in page  # buttons only until one is clicked


def test_a_modules_list_has_its_name_on_top_and_its_live_rows_due_first(
    client, conn, songs, le_freak, espresso
):
    gone = repo.create_exercise(conn, module_id=songs.id, name="gone", next_due=TODAY)
    repo.update_exercise(conn, gone.id, archived_at=NOW)

    page = client.get("/picker/songs", headers=hx()).text

    assert 'class="picker-list"' in page
    assert page.index("<h3") < page.index("le freak") < page.index("espresso")
    assert "SONGS" in page[page.index("<h3") :][:80]
    assert "gone" not in page


def test_the_list_is_the_tabs_table_minus_what_only_a_tab_needs(
    client, songs, le_freak
):
    page = client.get("/picker/songs", headers=hx()).text
    table = page[page.index("<table") : page.index("</table>")]

    for absent in (
        'type="checkbox"',
        "archive",
        "stop",
        "media",
        "<template",
        "hx-patch",
    ):
        assert absent not in table
    assert "66%" in table and "133" in table  # speed and target, read-only


def test_clicking_a_row_starts_it_with_the_tabs_own_call(client, songs, le_freak):
    page = client.get("/picker/songs", headers=hx()).text

    assert f'hx-post="/exercises/{le_freak.id}/start"' in page
    assert f'action="/exercises/{le_freak.id}/start"' in page  # and with no JS
    assert 'hx-target="#day-log"' in page


def test_the_open_modules_button_closes_the_list_and_a_close_control_does_too(
    client, slap, songs, le_freak
):
    page = client.get("/picker/songs", headers=hx()).text

    assert 'hx-get="/picker/slap"' in page  # the others still open theirs
    assert 'hx-get="/picker/songs"' not in page  # this one now hides it
    assert 'class="picker-close"' in page
    assert page.count('hx-get="/picker"') >= 2  # the active button, and the close


def test_a_picker_for_an_unknown_or_archived_module_is_404(client, conn, songs):
    assert client.get("/picker/nothing", headers=hx()).status_code == 404

    repo.update_module(conn, songs.id, archived_at=NOW)
    assert client.get("/picker/songs", headers=hx()).status_code == 404


# --- START is a picker, a stop is a start (Phase 10, steps 3 and 4) -----------


def test_with_nothing_running_start_reveals_the_picker_and_opens_no_line(
    client, conn, songs, le_freak
):
    page = client.get("/").text
    now_playing = page[page.index('id="now-playing"') : page.index("<h2>Log</h2>")]

    assert ">START<" in now_playing
    assert 'hx-get="/picker"' in now_playing
    assert 'id="picker"' not in now_playing  # revealed by the click, not drawn
    assert running(conn) is None
    assert repo.get_day(conn, TODAY) is None  # a false start leaves nothing behind


def test_the_bare_post_entries_start_is_gone(client, conn):
    response = client.post("/entries", headers=hx())

    assert response.status_code in (404, 405)
    assert running(conn) is None


def test_the_picker_without_htmx_is_a_page_of_its_own(client, songs, le_freak):
    page = client.get("/picker/songs").text

    assert "<html" in page
    assert "le freak" in page


def test_starting_a_row_from_the_picker_shows_it_running_with_no_picker(
    client, conn, songs, le_freak
):
    response = client.post(
        f"/exercises/{le_freak.id}/start", headers=hx(referer="http://localhost/")
    )

    assert '<section id="day-log"' in response.text
    assert "le freak" in response.text
    assert 'id="picker"' not in response.text
    day = repo.get_day(conn, TODAY)
    assert day is not None
    assert len(repo.entries_for_day(conn, day.id)) == 1


def test_the_running_card_has_the_five_stops_in_place_of_the_pulldown(
    client, conn, le_freak
):
    start(client, le_freak.id)

    page = client.get("/").text
    card = page[page.index('id="now-playing"') : page.index("<h2>Log</h2>")]

    assert "<select" not in card
    assert ">done<" not in card
    entry_id = running(conn).id
    for algorithm in ("normal", "short", "long", "rotate", "hold"):
        assert re.search(rf'<button[^>]*name="algorithm"[^>]*value="{algorithm}"', card)
    assert f'hx-post="/entries/{entry_id}/done"' in card
    assert f'action="/entries/{entry_id}/done"' in card
    assert f'action="/entries/{entry_id}/discard"' in card  # discard stays


@pytest.mark.parametrize("algorithm", ["normal", "short", "long", "rotate", "hold"])
def test_every_stop_logs_the_entry_and_moves_the_schedule_then_offers_the_picker(
    client, conn, songs, le_freak, algorithm
):
    start(client, le_freak.id)

    response = client.post(
        f"/entries/{running(conn).id}/done",
        data={"algorithm": algorithm},
        headers=hx(referer="http://localhost/"),
    )

    assert running(conn) is None
    day = repo.get_day(conn, TODAY)
    assert day is not None
    assert [e.description for e in repo.entries_for_day(conn, day.id)] == ["le freak"]
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    assert 'id="picker"' in response.text  # the same state as after START
    assert 'hx-get="/picker/songs"' in response.text


def test_discard_lands_on_the_picker_too(client, conn, songs, le_freak):
    start(client, le_freak.id)

    response = client.post(
        f"/entries/{running(conn).id}/discard", headers=hx(referer="http://localhost/")
    )

    assert 'id="picker"' in response.text
    assert running(conn) is None


def test_a_stop_from_a_module_page_does_not_draw_a_picker(
    client, conn, songs, le_freak
):
    start(client, le_freak.id)

    response = stop(client, le_freak.id, referer="http://localhost/modules/songs")

    assert 'id="picker"' not in response.text


# --- the current exercise, editable in place (Phase 10, step 5) ---------------------


def _card(page: str) -> str:
    return page[page.index('id="now-playing"') : page.index("<h2>Log</h2>")]


def test_the_running_card_carries_the_tab_rows_editable_cells(
    client, conn, songs, le_freak
):
    start(client, le_freak.id)

    card = _card(client.get("/").text)

    assert 'id="now-exercise"' in card
    for field in ("name", "speed", "target_bpm", "notes"):
        assert f'id="exercise-{le_freak.id}-{field}"' in card
    assert f'hx-patch="/exercises/{le_freak.id}"' in card
    assert 'hx-target="#now-exercise"' in card
    assert 'value="le freak"' in card
    assert "of 133" not in card and "133" in card  # the target, as its own cell


def test_an_ad_hoc_line_has_no_exercise_to_edit(client, conn):
    session.start_ad_hoc(conn, rng=SteadyRandom(), description="warm-up", now=NOW)

    assert 'id="now-exercise"' not in _card(client.get("/").text)


def test_an_edit_aimed_at_the_card_answers_with_the_card_cells_only(
    client, conn, songs, le_freak, loop_wav
):
    media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    response = client.patch(
        f"/exercises/{le_freak.id}",
        data={"notes": "watch the thumb", "speed": "70%"},
        headers=hx(**{"HX-Target": "now-exercise"}),
    )

    assert response.status_code == 200
    assert response.text.lstrip().startswith("<div")
    assert 'id="now-exercise"' in response.text
    assert "watch the thumb" in response.text
    assert "<tr" not in response.text  # not the tab's row
    # nothing the player is made of: playback and the waveform keep going
    for player in ("<audio", "data-peaks-url", 'class="player"', "now-media"):
        assert player not in response.text
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert (after.notes, after.speed) == ("watch the thumb", "70%")


def test_an_edit_aimed_at_the_tabs_row_still_answers_with_the_row(
    client, songs, le_freak
):
    response = client.patch(
        f"/exercises/{le_freak.id}",
        data={"speed": "70%"},
        headers=hx(**{"HX-Target": f"exercise-{le_freak.id}"}),
    )

    assert f'<tr id="exercise-{le_freak.id}"' in response.text
    assert 'id="now-exercise"' not in response.text


def test_a_refused_edit_in_the_card_is_a_message_not_a_redraw(
    client, conn, songs, le_freak, espresso
):
    start(client, le_freak.id)

    response = client.patch(
        f"/exercises/{le_freak.id}",
        data={"name": "espresso"},
        headers=hx(**{"HX-Target": "now-exercise"}),
    )

    assert response.status_code == 409
    assert "now-exercise" not in response.headers.get("HX-Retarget", "")


# --- media, edited inline (Phase 10, step 6) ----------------------------------------


def test_the_card_embeds_the_media_list_and_the_attach_forms(
    client, conn, songs, le_freak, loop_wav
):
    media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    card = _card(client.get("/").text)

    assert 'id="now-media-list"' in card
    assert 'id="media-list"' not in card
    assert 'hx-target="#now-media-list"' in card
    for kind in ("file", "youtube", "score", "text"):
        assert f'<input type="hidden" name="kind" value="{kind}">' in card
    assert "<audio" in card  # the player is still the card's


def test_the_media_page_keeps_its_own_list_and_forms(client, le_freak, roots):
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert 'id="media-list"' in page
    assert 'id="now-media-list"' not in page
    assert 'hx-target="#media-list"' in page


def _from_card(**headers: str) -> dict[str, str]:
    return hx(**{"HX-Target": "now-media-list"}, **headers)


def test_attaching_from_the_card_answers_with_the_list_and_the_new_players(
    client, conn, songs, le_freak, loop_wav
):
    start(client, le_freak.id)

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(loop_wav)},
        headers=_from_card(),
    )

    source = media.exercise_media(conn, exercise_id=le_freak.id)[0].sources[0]
    assert response.status_code == 200
    assert 'id="now-media-list"' in response.text
    assert 'id="media-players" hx-swap-oob="true"' in response.text
    assert f'src="/media/{source.id}/audio"' in response.text
    assert 'id="media-list"' not in response.text


def test_removing_and_reordering_from_the_card_redraw_the_players(
    client, conn, songs, le_freak, loop_wav
):
    first = media.attach(
        conn, exercise_id=le_freak.id, kind="text", body="one", now=NOW
    )
    media.attach(conn, exercise_id=le_freak.id, kind="text", body="two", now=NOW)
    start(client, le_freak.id)

    moved = client.post(
        f"/media/{first.id}/move", data={"direction": "down"}, headers=_from_card()
    )
    removed = client.delete(f"/media/{first.id}", headers=_from_card())

    for response in (moved, removed):
        assert 'id="now-media-list"' in response.text
        assert 'id="media-players" hx-swap-oob="true"' in response.text


def test_naming_and_mixing_a_track_from_the_card_leaves_the_player_alone(
    client, conn, songs, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    response = client.patch(
        f"/media/{source.id}",
        data={"label": "bass", "gain": "0.5"},
        headers=_from_card(),
    )

    assert 'id="now-media-list"' in response.text
    assert "media-players" not in response.text  # no oob, so no new <audio>
    assert "<audio" not in response.text
    group = media.exercise_media(conn, exercise_id=le_freak.id)[0].group
    assert group is not None
    labelled = client.post(
        f"/groups/{group.id}/label", data={"label": "stems"}, headers=_from_card()
    )
    assert "media-players" not in labelled.text


def test_the_media_page_writes_are_unchanged(client, conn, le_freak, loop_wav):
    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(loop_wav)},
        headers=hx(),
    )

    assert 'id="media-list"' in response.text
    assert "media-players" not in response.text


def test_a_refused_attach_from_the_card_is_a_message(
    client, conn, songs, le_freak, roots
):
    start(client, le_freak.id)

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": "/nowhere/else.wav"},
        headers=_from_card(),
    )

    assert response.status_code == 400
    assert media.exercise_media(conn, exercise_id=le_freak.id) == []


# --- the tabs read as configuration (Phase 10, step 7) -------------------------------


def test_a_module_page_says_where_a_session_is_run(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert 'class="config-note muted"' in page
    assert 'href="/"' in page[page.index('class="config-note muted"') :][:300]
    assert "start" in page and "stop" in page  # still useful, still there


# --- the site icon -------------------------------------------------------------------


def test_every_page_links_the_svg_favicon_and_the_app_serves_it(client, songs):
    for url in ("/", "/modules/songs"):
        assert (
            '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">'
            in client.get(url).text
        )

    icon = client.get("/static/favicon.svg")

    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")
    assert icon.text.lstrip().startswith("<svg")


# --- day summaries as equal cells with a duration bar -------------------------------


def _cells(page: str, day: str) -> list[str]:
    block = page[page.index(f'id="day-{day}"') :]
    block = block[: block.index("</summary>")]
    return re.findall(r'<span class="group-cell".*?</span>\s*</span>', block, re.S)


def _first(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    assert found is not None, (pattern, text)
    return found.group(1)


def test_every_log_group_is_a_cell_even_with_no_time_that_day(
    client, slap, songs, earlier_days
):
    cells = _cells(client.get("/").text, "2026-06-06")

    assert len(cells) == 2  # TECHNIQUE had time, REPERTOIRE did not
    assert "TECHNIQUE" in cells[0] and "00:15" in cells[0]
    assert "REPERTOIRE" in cells[1] and "00:00" in cells[1]


def test_the_cells_follow_module_order_and_share_a_group_once(
    client, conn, slap, songs, earlier_days
):
    repo.create_module(conn, name="ETUDES", log_group="TECHNIQUE")  # same group

    cells = _cells(client.get("/").text, "2026-06-06")

    assert [("TECHNIQUE" in c, "REPERTOIRE" in c) for c in cells] == [
        (True, False),
        (False, True),
    ]


def test_a_group_the_day_used_but_no_module_has_is_a_cell_too(
    client, conn, slap, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.create_entry(conn, day_id=day.id, started_at=datetime(2026, 6, 6, 21))
    repo.close_entry(
        conn,
        entry.id,
        ended_at=datetime(2026, 6, 6, 21, 5),
        description="jam",
        log_group="OLD GROUP",
    )

    cells = _cells(client.get("/").text, "2026-06-06")

    assert any("OLD GROUP" in c and "00:05" in c for c in cells)


def test_equal_times_are_equal_bars_and_each_group_has_a_colour(
    client, conn, slap, songs, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.create_entry(conn, day_id=day.id, started_at=datetime(2026, 6, 6, 21))
    repo.close_entry(
        conn,
        entry.id,
        ended_at=datetime(2026, 6, 6, 21, 15),
        description="le freak",
        log_group="REPERTOIRE",
    )

    cells = _cells(client.get("/").text, "2026-06-06")

    widths = [_first(r"width: ([\d.]+)%", c) for c in cells]
    assert [float(w) for w in widths] == [100.0, 100.0]
    colours = [_first(r"--c: ([^;\"]+)", c) for c in cells]
    assert len(set(colours)) == 2


def _add_time(conn, day, *, minutes: int, log_group: str):
    record = repo.get_day(conn, day) or repo.create_day(conn, day=day)
    started = datetime.combine(day, time(21))
    entry = repo.create_entry(conn, day_id=record.id, started_at=started)
    repo.close_entry(
        conn,
        entry.id,
        ended_at=started.replace(minute=minutes % 60, hour=21 + minutes // 60),
        description=log_group.lower(),
        log_group=log_group,
    )


def test_bars_share_one_scale_across_every_day_shown(client, conn, slap):
    jazz = repo.create_module(conn, name="JAZZ", log_group="JAZZ")
    assert jazz is not None
    _add_time(conn, date(2026, 6, 10), minutes=20, log_group="JAZZ")
    _add_time(conn, date(2026, 6, 11), minutes=60, log_group="JAZZ")

    page = client.get("/").text

    def width(day: str) -> float:
        cell = next(c for c in _cells(page, day) if "JAZZ" in c)
        return float(_first(r"width: ([\d.]+)%", cell))

    assert width("2026-06-11") == pytest.approx(100.0)
    assert width("2026-06-10") == pytest.approx(100 / 3, abs=0.01)  # 20 of 60 min


def test_every_cell_carries_its_seconds_for_the_page_to_rescale_by(
    client, slap, songs, earlier_days
):
    cells = _cells(client.get("/").text, "2026-06-06")

    assert 'data-seconds="900"' in cells[0]
    assert 'data-seconds="0"' in cells[1]


def test_a_group_with_no_time_has_an_empty_bar(client, slap, songs, earlier_days):
    cells = _cells(client.get("/").text, "2026-06-06")

    assert "width: 0%" in cells[1]


def test_the_load_more_days_carry_the_same_cells(client, slap, songs, earlier_days):
    page = client.get("/days?before=2026-06-02", headers=hx()).text

    assert page.count('class="group-cell"') == 2


def test_the_summary_has_no_disclosure_triangle(client):
    css = client.get("/static/app.css").text

    assert "details.day > summary" in css
    assert "list-style: none" in css
    assert "::-webkit-details-marker" in css


# --- correcting a line of the log, in place -------------------------------------------


def test_every_finished_line_is_editable_in_place_with_no_edit_mode(
    client, sample_block, conn
):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    page = client.get("/").text

    assert 'value="019 Tempo Builder"' in page
    assert f'hx-patch="/entries/{entry.id}"' in page
    assert "/edit" not in page  # no mode to ask for
    assert ">save<" not in page  # and no row to save


def test_a_cell_saves_when_it_changes_and_keeps_its_id_to_keep_the_focus(
    client, sample_block, conn
):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    page = client.get("/").text

    for field in (
        "started_at",
        "ended_at",
        "description",
        "notes",
        "speed",
        "log_group",
    ):
        assert f'id="entry-{entry.id}-{field}"' in page
    assert page.count('hx-trigger="change"') >= 6


def test_the_running_line_has_no_boxes(client, conn, le_freak):
    start(client, le_freak.id)
    entry = running(conn)
    assert entry is not None

    page = client.get("/").text

    assert f'hx-patch="/entries/{entry.id}"' not in page


def test_earlier_days_are_editable_in_place_too(client, earlier_days):
    page = client.get("/").text

    assert 'value="day 6"' in page
    assert "/edit" not in page


def test_the_old_edit_page_is_gone(client, earlier_days):
    assert client.get("/days/2026-06-06/edit").status_code == 404


def test_a_day_is_a_whole_page_without_htmx(client, earlier_days):
    response = client.get("/days/2026-06-06")

    assert "<html" in response.text
    assert 'value="day 6"' in response.text


def test_emptying_a_box_clears_the_field(client, conn, sample_block):
    entry = repo.entries_for_day(conn, sample_block.id)[0]
    client.patch(f"/entries/{entry.id}", data={"notes": "left hand"}, headers=hx())

    client.patch(f"/entries/{entry.id}", data={"notes": ""}, headers=hx())

    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert not after.notes


def test_emptying_the_description_leaves_the_line_named(client, conn, sample_block):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    client.patch(f"/entries/{entry.id}", data={"description": ""}, headers=hx())

    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert after.description == "019 Tempo Builder"


def test_a_day_nothing_was_logged_on_is_404(client):
    assert client.get("/days/2020-01-01").status_code == 404


def test_amending_a_past_entry_redraws_that_day_with_its_new_total(
    client, conn, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.entries_for_day(conn, day.id)[0]

    response = client.patch(
        f"/entries/{entry.id}",
        data={"ended_at": "20:45", "description": "day 6, longer than I thought"},
        headers=hx(),
    )

    assert response.status_code == 200
    assert 'id="day-2026-06-06"' in response.text  # the block that was edited
    assert "00:45" in response.text  # 20:00 to the new 20:45
    assert 'value="day 6, longer than I thought"' in response.text
    assert "<input" in response.text  # the next line may be wrong too
    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert after.ended_at == datetime(2026, 6, 6, 20, 45)


def test_amending_todays_entry_redraws_the_log_and_the_totals(
    client, conn, sample_block
):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    response = client.patch(f"/entries/{entry.id}", data={"speed": "72%"}, headers=hx())

    assert '<section id="day-log"' in response.text
    assert '<section id="day-totals" hx-swap-oob="true"' in response.text
    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert after.speed == "72%"


def test_a_plain_form_post_amends_an_entry_too(client, conn, sample_block):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    response = client.post(
        f"/entries/{entry.id}", data={"notes": "left hand only"}, headers=hx()
    )

    assert response.status_code == 200
    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert after.notes == "left hand only"


def test_the_running_entry_cannot_be_edited_by_hand(client, conn, le_freak):
    start(client, le_freak.id)
    entry = running(conn)
    assert entry is not None

    response = client.patch(
        f"/entries/{entry.id}", data={"description": "guessing"}, headers=hx()
    )

    assert response.status_code == 409
    assert running(conn) is not None


def test_an_unreadable_time_is_refused_rather_than_guessed(client, conn, sample_block):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    response = client.patch(
        f"/entries/{entry.id}", data={"ended_at": "half past"}, headers=hx()
    )

    assert response.status_code == 400
    after = repo.get_entry(conn, entry.id)
    assert after is not None
    assert after.ended_at == datetime(2026, 7, 5, 22, 34)  # unchanged


def test_amending_an_entry_that_is_not_there_is_404(client):
    assert client.patch("/entries/404", data={"speed": "90"}).status_code == 404


# --- taking a line out of the log -------------------------------------------


def test_a_line_can_be_removed(client, conn, sample_block):
    entry = repo.entries_for_day(conn, sample_block.id)[0]  # 22:27-22:34, 00:07

    response = client.delete(f"/entries/{entry.id}", headers=hx())

    assert response.status_code == 200
    assert repo.get_entry(conn, entry.id) is None
    assert "019 Tempo Builder" not in response.text
    assert "00:46" in response.text  # the day total, seven minutes lighter


def test_removing_a_line_from_an_earlier_day_redraws_that_day(
    client, conn, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.entries_for_day(conn, day.id)[0]

    response = client.delete(f"/entries/{entry.id}", headers=hx())

    assert 'id="day-2026-06-06"' in response.text
    assert "00:00" in response.text  # nothing left on it
    assert repo.get_entry(conn, entry.id) is None


def test_the_remove_button_is_on_every_finished_line_and_asks_first(
    client, conn, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.entries_for_day(conn, day.id)[0]

    page = client.get("/days/2026-06-06", headers=hx()).text

    assert f'action="/entries/{entry.id}/delete"' in page
    assert "hx-confirm" in page  # one click from gone is one click too few


def test_a_plain_form_post_removes_a_line_too(client, conn, sample_block):
    """No JavaScript: HTML forms cannot send DELETE, so POST does it."""
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    response = client.post(f"/entries/{entry.id}/delete", headers=hx())

    assert response.status_code == 200
    assert repo.get_entry(conn, entry.id) is None


def test_the_running_line_cannot_be_removed(client, conn, le_freak):
    start(client, le_freak.id)
    entry = running(conn)
    assert entry is not None

    response = client.delete(f"/entries/{entry.id}", headers=hx())

    assert response.status_code == 409
    assert repo.get_entry(conn, entry.id) is not None


def test_removing_a_line_that_is_not_there_is_404(client):
    assert client.delete("/entries/404", headers=hx()).status_code == 404


# --- taking a row out of a module -------------------------------------------


def test_a_row_can_be_archived_from_its_module(client, conn, songs, le_freak):
    response = client.post(f"/exercises/{le_freak.id}/archive", headers=hx())

    assert response.status_code == 200
    assert response.text.strip() == ""  # the row goes, and nothing replaces it
    assert "le freak" not in client.get("/modules/songs").text


def test_archiving_a_row_keeps_the_log_it_appears_in(client, conn, le_freak):
    start(client, le_freak.id)
    client.post(f"/entries/{running(conn).id}/done", headers=hx())

    client.post(f"/exercises/{le_freak.id}/archive", headers=hx())

    day = repo.get_day(conn, TODAY)
    assert day is not None
    logged = [entry for entry in repo.entries_for_day(conn, day.id) if entry.ended_at]
    assert [entry.description for entry in logged] == ["le freak"]
    # archived, not deleted: the log still has a row to point at
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.archived_at == NOW


def test_the_module_page_offers_the_button_and_asks_first(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert f'action="/exercises/{le_freak.id}/archive"' in page
    assert "hx-confirm" in page  # one click from gone is one click too few


def test_archiving_a_row_that_is_not_there_is_404(client):
    assert client.post("/exercises/404/archive", headers=hx()).status_code == 404


def test_archiving_without_htmx_goes_back_to_the_module(client, songs, le_freak):
    response = client.post(
        f"/exercises/{le_freak.id}/archive",
        headers={"Referer": "http://testserver/modules/songs"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/modules/songs"


# --- the material on the card -----------------------------------------------


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A scores directory of our own; every path in is confined to it."""
    root = tmp_path / "TUNES"
    root.mkdir()
    monkeypatch.setenv("MUSIC_TOOLS_MEDIA_ROOTS", str(root))
    return root


@pytest.fixture
def loop_wav(roots):
    """Four seconds of silence, exported as a real file. No binary fixtures."""
    from pydub import AudioSegment

    path = roots / "S" / "le freak" / "loop.wav"
    path.parent.mkdir(parents=True)
    AudioSegment.silent(duration=4000).export(path, format="wav")
    return path


def test_the_card_plays_the_file_attached_to_the_exercise(
    client, conn, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    page = client.get("/").text

    assert f'src="/media/{source.id}/audio"' in page
    assert "<audio" in page
    assert "loop.wav" in page


def test_a_single_track_player_has_a_volume_slider(client, conn, le_freak, loop_wav):
    media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    page = client.get("/").text
    player = page[page.index('class="player"') : page.index("</audio>")]
    volume = page[page.index('class="volume"') :][:300]

    assert 'class="volume"' in page
    assert 'type="range"' in volume and 'min="0"' in volume and 'max="1"' in volume
    assert 'aria-label="volume"' in volume
    assert player  # inside the player's own controls, not beside it


def test_a_track_set_gets_no_volume_slider_of_its_own(client, conn, le_freak, loop_wav):
    from pydub import AudioSegment

    drums = loop_wav.with_name("drums.wav")
    AudioSegment.silent(duration=4000).export(drums, format="wav")
    first = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="file",
        path=str(drums),
        group_id=first.group_id,
        now=NOW,
    )
    start(client, le_freak.id)

    assert 'class="volume"' not in client.get("/").text


def test_a_youtube_attachment_is_an_embed_with_the_link_behind_it(
    client, conn, le_freak
):
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="youtube",
        url="https://www.youtube.com/watch?v=Kt2GdFbdVxo",
        now=NOW,
    )
    start(client, le_freak.id)

    page = client.get("/").text

    # the one card that needs the network; the link is what is left without it
    assert 'src="https://www.youtube.com/embed/Kt2GdFbdVxo"' in page
    assert 'href="https://www.youtube.com/watch?v=Kt2GdFbdVxo"' in page


def test_a_url_that_is_not_youtube_is_left_as_a_link(client, conn, le_freak):
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="youtube",
        url="https://example.com/not-a-video",
        now=NOW,
    )
    start(client, le_freak.id)

    page = client.get("/").text

    assert "<iframe" not in page
    assert 'href="https://example.com/not-a-video"' in page


def test_text_is_shown_as_text(client, conn, le_freak):
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="text",
        body="Bb minor pentatonic, two octaves",
        now=NOW,
    )
    start(client, le_freak.id)

    assert "Bb minor pentatonic, two octaves" in client.get("/").text


def test_an_exercise_with_nothing_attached_says_so(client, le_freak):
    start(client, le_freak.id)

    assert "Nothing attached to this one yet" in client.get("/").text


def test_the_file_route_serves_what_is_on_disk(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.get(f"/media/{source.id}/file")

    assert response.status_code == 200
    assert response.content == loop_wav.read_bytes()


def test_the_file_route_refuses_a_path_outside_the_roots(
    client, conn, le_freak, loop_wav, tmp_path, monkeypatch
):
    """The roots can be narrowed later, and a stored path is not a promise."""
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    elsewhere = tmp_path / "OTHER"
    elsewhere.mkdir()
    monkeypatch.setenv("MUSIC_TOOLS_MEDIA_ROOTS", str(elsewhere))

    assert client.get(f"/media/{source.id}/file").status_code == 403


def test_the_file_route_is_409_naming_the_path_when_the_file_has_gone(
    client, conn, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    loop_wav.unlink()

    response = client.get(f"/media/{source.id}/file")

    assert response.status_code == 409
    assert str(loop_wav) in response.text


def test_the_file_route_says_it_accepts_ranges_and_types_the_content(
    client, conn, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.get(f"/media/{source.id}/file")

    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] in ("audio/x-wav", "audio/wav")


def test_a_range_request_gets_206_and_a_correct_content_range(
    client, conn, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    whole = loop_wav.read_bytes()

    response = client.get(f"/media/{source.id}/file", headers={"Range": "bytes=10-19"})

    assert response.status_code == 206
    assert response.content == whole[10:20]
    assert response.headers["content-range"] == f"bytes 10-19/{len(whole)}"


def test_an_open_ended_range_runs_to_the_end_of_the_file(
    client, conn, le_freak, loop_wav
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    whole = loop_wav.read_bytes()

    response = client.get(f"/media/{source.id}/file", headers={"Range": "bytes=100-"})

    assert response.status_code == 206
    assert response.content == whole[100:]
    assert response.headers["content-range"] == (
        f"bytes 100-{len(whole) - 1}/{len(whole)}"
    )


def test_a_range_past_the_end_is_416(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    size = loop_wav.stat().st_size

    response = client.get(
        f"/media/{source.id}/file", headers={"Range": f"bytes={size + 10}-"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{size}"


def test_the_file_route_is_404_for_media_that_is_not_there(client):
    assert client.get("/media/404/file").status_code == 404


def test_a_module_row_offers_start_and_stop_whatever_is_running(
    client, conn, songs, le_freak
):
    page = client.get("/modules/songs").text
    assert f'action="/exercises/{le_freak.id}/start"' in page
    assert f'action="/exercises/{le_freak.id}/stop"' in page

    start(client, le_freak.id)

    page = client.get("/modules/songs").text
    # both buttons stay put; the row that is running also offers a discard
    assert f'action="/exercises/{le_freak.id}/start"' in page
    assert f'action="/exercises/{le_freak.id}/stop"' in page
    assert f'action="/entries/{running(conn).id}/discard"' in page


def test_stop_finishes_the_row_that_is_running(client, conn, le_freak, songs):
    start(client, le_freak.id)

    response = stop(
        client, le_freak.id, referer=f"http://localhost/modules/{songs.slug}"
    )

    assert response.status_code == 200
    assert f'id="exercise-{le_freak.id}"' in response.text
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    assert running(conn) is None


def test_stopping_a_row_re_sorts_the_queue_it_came_from(
    client, conn, songs, le_freak, espresso
):
    # le freak is the overdue one, espresso is due on the 20th; stopping le
    # freak schedules it past espresso, so the two swap places
    start(client, le_freak.id)

    response = stop(
        client, le_freak.id, referer=f"http://localhost/modules/{songs.slug}"
    )

    assert 'id="queue"' in response.text  # the whole queue, not the row alone
    assert response.text.index(f'id="exercise-{espresso.id}"') < response.text.index(
        f'id="exercise-{le_freak.id}"'
    )


def test_done_from_a_module_page_re_sorts_the_queue_too(
    client, conn, songs, le_freak, espresso
):
    start(client, le_freak.id)

    response = client.post(
        f"/entries/{running(conn).id}/done",
        headers=hx(referer=f"http://localhost/modules/{songs.slug}"),
    )

    assert response.text.index(f'id="exercise-{espresso.id}"') < response.text.index(
        f'id="exercise-{le_freak.id}"'
    )


def test_stop_takes_the_algorithm_the_row_chose(client, conn, le_freak, espresso):
    start(client, le_freak.id)

    client.post(
        f"/exercises/{le_freak.id}/stop", data={"algorithm": "rotate"}, headers=hx()
    )

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.next_due == espresso.next_due  # the back of the queue, jitter aside


def test_stop_on_a_row_that_is_not_the_running_one_changes_nothing(
    client, conn, le_freak, espresso
):
    start(client, le_freak.id)

    response = stop(client, espresso.id)

    assert response.status_code == 200
    assert running(conn).description == "le freak"  # still playing
    after = repo.get_exercise(conn, espresso.id)
    assert after is not None
    assert after.practiced_count == 2


def test_stop_with_nothing_running_changes_nothing(client, conn, le_freak):
    response = stop(client, le_freak.id)

    assert response.status_code == 200
    assert repo.list_days(conn) == []
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 8


def test_stop_with_nothing_running_logs_the_stretch_since_the_last_line(
    client, conn, le_freak
):
    day = repo.create_day(conn, day=TODAY)
    repo.create_entry(
        conn,
        day_id=day.id,
        started_at=datetime(2026, 7, 5, 21, 50),
        ended_at=datetime(2026, 7, 5, 22, 20),
        description="warm-up",
    )

    response = stop(client, le_freak.id)

    assert response.status_code == 200
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9
    logged = repo.entries_for_day(conn, day.id)[-1]
    assert logged.description == "le freak"
    assert logged.started_at == datetime(2026, 7, 5, 22, 20, 0, 1)
    assert logged.ended_at == NOW


def test_stop_on_an_exercise_that_is_not_there_is_404(client, conn):
    assert client.post("/exercises/404/stop", headers=hx()).status_code == 404


def test_stop_without_htmx_redirects_back_to_the_page(client, le_freak):
    start(client, le_freak.id)

    response = client.post(f"/exercises/{le_freak.id}/stop", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_starting_the_row_that_is_already_running_does_not_restart_it(
    client, conn, le_freak
):
    start(client, le_freak.id)
    entry_id = running(conn).id

    start(client, le_freak.id)

    day = repo.get_day(conn, TODAY)
    assert day is not None
    assert [entry.id for entry in repo.entries_for_day(conn, day.id)] == [entry_id]
    assert running(conn).started_at == NOW


# --- attaching media from the page ------------------------------------------


def test_the_media_page_lists_the_roots_paths_are_confined_to(client, le_freak, roots):
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert "le freak" in page
    assert str(roots) in page  # a path is typed in, so say where it may point


def test_a_path_pasted_in_quotes_is_attached_without_them(
    client, conn, le_freak, loop_wav
):
    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": f"'{loop_wav}'"},
        headers=hx(),
    )

    assert response.status_code == 200
    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert cards[0].sources[0].path == str(loop_wav)


def test_a_file_is_attached_from_the_page(client, conn, le_freak, loop_wav):
    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(loop_wav), "label": "the loop"},
        headers=hx(),
    )

    assert response.status_code == 200
    assert 'id="media-list"' in response.text
    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert [card.kind for card in cards] == ["file"]
    assert cards[0].sources[0].label == "the loop"


def test_attaching_the_same_file_twice_is_a_409_with_a_message(
    client, conn, le_freak, loop_wav
):
    data = {"kind": "file", "path": str(loop_wav)}
    client.post(f"/exercises/{le_freak.id}/media", data=data, headers=hx())

    response = client.post(f"/exercises/{le_freak.id}/media", data=data, headers=hx())

    assert response.status_code == 409
    assert "loop.wav" in response.text
    assert len(media.exercise_media(conn, exercise_id=le_freak.id)) == 1


def test_a_youtube_url_is_attached_from_the_page(client, conn, le_freak):
    client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "youtube", "url": "https://youtu.be/Kt2GdFbdVxo"},
        headers=hx(),
    )

    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert [card.sources[0].url for card in cards] == ["https://youtu.be/Kt2GdFbdVxo"]


def test_text_is_attached_from_the_page(client, conn, le_freak):
    client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "text", "body": "two octaves, thumb on the E"},
        headers=hx(),
    )

    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert cards[0].sources[0].body == "two octaves, thumb on the E"


def test_a_path_outside_the_roots_is_refused_with_a_message(
    client, conn, le_freak, roots, tmp_path
):
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(outside)},
        headers=hx(),
    )

    assert response.status_code == 400
    assert "outside the configured roots" in response.text
    assert media.exercise_media(conn, exercise_id=le_freak.id) == []


def test_a_score_can_be_a_pdf(client, conn, le_freak, roots):
    score = roots / "tune.pdf"
    score.write_bytes(b"%PDF-1.4\n")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "score", "path": str(score)},
        headers=hx(),
    )

    assert response.status_code == 200
    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert [card.sources[0].path for card in cards] == [str(score)]


def test_a_refusal_comes_back_where_htmx_will_show_it(
    client, le_freak, roots, tmp_path
):
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "score", "path": str(outside)},
        headers=hx(),
    )

    assert response.status_code == 400
    # a 4xx lands in the slot the page keeps for it, not in the list it was
    # aimed at: the attachment that is there already stays on screen
    assert response.headers["HX-Retarget"] == "#problem"
    assert response.headers["HX-Reswap"] == "outerHTML"
    assert 'id="problem"' in response.text
    assert "outside the configured roots" in response.text


def test_a_refusal_without_htmx_is_a_page_rather_than_json(
    client, le_freak, roots, tmp_path
):
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "score", "path": str(outside)},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "outside the configured roots" in response.text


def test_the_page_carries_the_slot_a_refusal_lands_in(client, le_freak, roots):
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert 'id="problem"' in page
    # htmx throws a 4xx body away unless the page's own config says otherwise
    assert '"[45].."' in page


def test_a_file_that_is_not_there_is_refused_with_a_message(client, le_freak, roots):
    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(roots / "nothing.wav")},
        headers=hx(),
    )

    assert response.status_code == 400
    assert "nothing.wav" in response.text


def test_attaching_to_an_exercise_that_is_not_there_is_404(client, roots):
    response = client.post(
        "/exercises/404/media", data={"kind": "text", "body": "x"}, headers=hx()
    )

    assert response.status_code == 404


def test_a_kind_without_what_it_needs_is_refused_by_the_page(client, le_freak, roots):
    response = client.post(
        f"/exercises/{le_freak.id}/media", data={"kind": "text"}, headers=hx()
    )

    assert response.status_code == 400


def test_an_attachment_can_be_removed_from_the_page(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.delete(f"/media/{source.id}", headers=hx())

    assert response.status_code == 200
    assert media.exercise_media(conn, exercise_id=le_freak.id) == []
    assert loop_wav.exists()  # referenced, never owned


def test_a_plain_form_post_removes_an_attachment_too(client, conn, le_freak, loop_wav):
    """No JavaScript: HTML forms cannot send DELETE, so POST does it."""
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.post(f"/media/{source.id}/delete", headers=hx())

    assert response.status_code == 200
    assert media.exercise_media(conn, exercise_id=le_freak.id) == []


def test_removing_an_attachment_that_is_not_there_is_404(client):
    assert client.delete("/media/404", headers=hx()).status_code == 404


def test_attachments_can_be_reordered_from_the_page(client, conn, le_freak, loop_wav):
    first = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    media.attach(conn, exercise_id=le_freak.id, kind="text", body="notes", now=NOW)

    response = client.post(
        f"/media/{first.id}/move", data={"direction": "down"}, headers=hx()
    )

    assert response.status_code == 200
    cards = media.exercise_media(conn, exercise_id=le_freak.id)
    assert [card.kind for card in cards] == ["text", "file"]


def test_a_direction_nobody_knows_is_refused(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.post(
        f"/media/{source.id}/move", data={"direction": "sideways"}, headers=hx()
    )

    assert response.status_code == 400


def test_a_second_file_makes_a_track_set_from_the_page(
    client, conn, le_freak, loop_wav, roots
):
    from pydub import AudioSegment

    bass = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    drums = roots / "S" / "le freak" / "drums.wav"
    AudioSegment.silent(duration=4000).export(drums, format="wav")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={
            "kind": "file",
            "path": str(drums),
            "label": "drums",
            "group_id": str(bass.group_id),
        },
        headers=hx(),
    )

    assert response.status_code == 200
    card = media.exercise_media(conn, exercise_id=le_freak.id)[0]
    assert card.is_set
    assert [track.label for track in card.sources] == [None, "drums"]


def test_a_member_that_disagrees_on_length_is_refused_with_the_file_named(
    client, conn, le_freak, loop_wav, roots
):
    from pydub import AudioSegment

    bass = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    short = roots / "S" / "le freak" / "half.wav"
    AudioSegment.silent(duration=2000).export(short, format="wav")

    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "file", "path": str(short), "group_id": str(bass.group_id)},
        headers=hx(),
    )

    assert response.status_code == 409
    assert "half.wav" in response.text
    assert not media.exercise_media(conn, exercise_id=le_freak.id)[0].is_set


def test_a_track_is_named_and_mixed_from_the_page(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.post(
        f"/media/{source.id}",
        data={"label": "bass DI", "gain": "0.5", "pan": "-0.4", "muted": "on"},
        headers=hx(),
    )

    assert response.status_code == 200
    after = repo.get_media_source(conn, source.id)
    assert after is not None
    assert (after.label, after.gain, after.pan, after.muted) == (
        "bass DI",
        0.5,
        -0.4,
        True,
    )


def test_a_mix_a_mixer_could_not_mean_is_refused(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.post(f"/media/{source.id}", data={"pan": "3"}, headers=hx())

    assert response.status_code == 400


def test_a_set_is_labelled_as_a_whole_from_the_page(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.post(
        f"/groups/{source.group_id}/label", data={"label": "stems"}, headers=hx()
    )

    assert response.status_code == 200
    assert media.exercise_media(conn, exercise_id=le_freak.id)[0].label == "stems"


def test_the_module_page_links_to_an_exercises_media(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert f'href="/exercises/{le_freak.id}/media"' in page


def test_attaching_without_htmx_redirects_back_to_the_media_page(
    client, le_freak, roots
):
    """No JavaScript: a real form, a real redirect, a working app."""
    response = client.post(
        f"/exercises/{le_freak.id}/media",
        data={"kind": "text", "body": "two octaves"},
        headers={"Referer": f"http://testserver/exercises/{le_freak.id}/media"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/exercises/{le_freak.id}/media"


def test_the_media_page_is_404_for_an_exercise_that_is_not_there(client):
    assert client.get("/exercises/404/media").status_code == 404


# --- Moving rows between modules (#29) --------------------------------------


def move(client, *, from_slug: str, module_id: int, exercise_ids: list[int], **headers):
    """The click the move bar sends: the ticked rows, and where they go."""
    return client.post(
        f"/modules/{from_slug}/move",
        data={
            "module_id": str(module_id),
            "exercise_id": [str(exercise_id) for exercise_id in exercise_ids],
        },
        headers=hx(**headers),
    )


def test_ticked_rows_leave_the_queue_they_were_on(
    client, conn, slap, songs, le_freak, espresso
):
    response = move(
        client,
        from_slug="songs",
        module_id=slap.id,
        exercise_ids=[le_freak.id, espresso.id],
    )

    assert response.status_code == 200
    assert repo.exercises_due(conn, module_id=songs.id) == []
    assert [row.name for row in repo.exercises_due(conn, module_id=slap.id)] == [
        "le freak",
        "espresso",
    ]


def test_the_answer_is_the_queue_the_rows_left(client, slap, songs, le_freak, espresso):
    """A move takes rows off the page, so the fragment is the whole tbody."""
    response = move(
        client, from_slug="songs", module_id=slap.id, exercise_ids=[le_freak.id]
    )

    assert f'id="exercise-{espresso.id}"' in response.text
    assert f'id="exercise-{le_freak.id}"' not in response.text


def test_moving_one_row_is_one_ticked_box(client, conn, slap, songs, le_freak):
    response = move(
        client, from_slug="songs", module_id=slap.id, exercise_ids=[le_freak.id]
    )

    assert response.status_code == 200
    assert [row.module_id for row in repo.find_exercises(conn, "le freak")] == [slap.id]


def test_a_move_keeps_the_schedule_and_the_log(client, conn, slap, songs, le_freak):
    start(client, le_freak.id)
    stop(client, le_freak.id)
    before = repo.get_exercise(conn, le_freak.id)
    assert before is not None

    move(client, from_slug="songs", module_id=slap.id, exercise_ids=[le_freak.id])

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert (after.next_due, after.practiced_count) == (
        before.next_due,
        before.practiced_count,
    )
    day = repo.get_day(conn, TODAY)
    assert day is not None
    entries = repo.entries_for_day(conn, day.id)
    assert [entry.log_group for entry in entries] == ["REPERTOIRE"]


def test_ticking_nothing_moves_nothing(client, conn, slap, songs, le_freak):
    response = move(client, from_slug="songs", module_id=slap.id, exercise_ids=[])

    assert response.status_code == 200
    assert [row.name for row in repo.exercises_due(conn, module_id=songs.id)] == [
        "le freak"
    ]


def test_a_name_the_target_already_uses_is_refused(client, conn, slap, songs, le_freak):
    twin = repo.create_exercise(conn, module_id=slap.id, name="le freak")

    response = move(
        client, from_slug="songs", module_id=slap.id, exercise_ids=[le_freak.id]
    )

    assert response.status_code == 409
    assert [row.module_id for row in repo.exercises_due(conn, module_id=songs.id)] == [
        songs.id
    ]
    assert [row.id for row in repo.exercises_due(conn, module_id=slap.id)] == [twin.id]


def test_moving_into_a_module_that_is_not_there_is_404(client, songs, le_freak):
    response = move(
        client, from_slug="songs", module_id=404, exercise_ids=[le_freak.id]
    )

    assert response.status_code == 404


def test_moving_a_row_that_is_not_there_is_404(client, slap, songs):
    assert (
        move(
            client, from_slug="songs", module_id=slap.id, exercise_ids=[404]
        ).status_code
        == 404
    )


def test_moving_from_a_module_that_is_not_there_is_404(client, slap, le_freak):
    response = move(
        client, from_slug="nope", module_id=slap.id, exercise_ids=[le_freak.id]
    )

    assert response.status_code == 404


def test_a_move_without_htmx_redirects_back_to_the_page(client, slap, songs, le_freak):
    """No JavaScript: the checkboxes are still in the form, the form still posts."""
    response = client.post(
        "/modules/songs/move",
        data={
            "module_id": str(slap.id),
            "exercise_id": [str(le_freak.id)],
        },
        headers={"Referer": "http://testserver/modules/songs"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/modules/songs"


def test_the_move_bar_offers_every_other_live_module(client, slap, songs, le_freak):
    page = client.get("/modules/songs").text

    assert f'<option value="{slap.id}">SLAP</option>' in page
    assert f'<option value="{songs.id}">' not in page


def test_a_row_carries_a_tick_box_tied_to_the_move_form(client, songs, le_freak):
    page = client.get("/modules/songs").text
    row = page[page.index('id="exercise-%d"' % le_freak.id) :]
    row = row[: row.index("</tr>")]

    assert 'name="exercise_id"' in row
    assert f'value="{le_freak.id}"' in row
    assert 'form="move"' in row


def test_with_nowhere_to_move_to_there_is_no_move_bar(client, songs, le_freak):
    """One module is the whole catalogue: the bar would offer nothing."""
    page = client.get("/modules/songs").text

    assert 'id="move"' not in page


def test_an_archived_module_is_not_offered_as_a_target(
    client, conn, slap, songs, le_freak
):
    repo.update_module(conn, slap.id, archived_at=NOW)

    page = client.get("/modules/songs").text

    assert 'id="move"' not in page


# --- Issues 34-38: form fixes, the start button, the running row ------------


def test_a_target_bpm_that_is_not_a_number_is_a_400_not_a_crash(client, conn, le_freak):
    response = client.patch(
        f"/exercises/{le_freak.id}", data={"target_bpm": "---"}, headers=hx()
    )

    assert response.status_code == 400
    assert "---" in response.text
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.target_bpm == 133.0


def test_adding_a_row_with_a_target_bpm_that_is_not_a_number_is_a_400(client, songs):
    response = client.post(
        "/exercises",
        data={"module_id": songs.id, "name": "x", "target_bpm": "fast"},
        headers=hx(),
    )

    assert response.status_code == 400


def test_a_blank_target_bpm_clears_it(client, conn, le_freak):
    response = client.patch(
        f"/exercises/{le_freak.id}", data={"target_bpm": ""}, headers=hx()
    )

    assert response.status_code == 200
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.target_bpm is None


def test_the_target_bpm_boxes_ask_the_browser_for_a_number(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert page.count('name="target_bpm"') == 2
    assert page.count('name="target_bpm" inputmode="decimal"') == 2


def test_notes_are_a_textarea_on_the_row_and_on_the_add_form(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert page.count("<textarea") == 2
    assert 'input type="text" name="notes"' not in page


def test_the_running_exercise_is_first_in_its_queue_and_marked(
    client, conn, songs, le_freak, espresso
):
    start(client, espresso.id)

    page = client.get("/modules/songs").text

    assert page.index(f'id="exercise-{espresso.id}"') < page.index(
        f'id="exercise-{le_freak.id}"'
    )
    assert f'id="exercise-{espresso.id}"\n    class="active' in page
    assert f'id="exercise-{le_freak.id}"\n    class="active' not in page


def test_starting_from_a_module_page_answers_with_the_running_row_first(
    client, songs, le_freak, espresso
):
    response = start(client, espresso.id, Referer="http://testserver/modules/songs")

    assert response.text.index(f'id="exercise-{espresso.id}"') < response.text.index(
        f'id="exercise-{le_freak.id}"'
    )


def test_an_exercise_row_saves_on_change_with_no_save_button(client, songs, le_freak):
    page = client.get("/modules/songs").text

    assert 'hx-trigger="change, submit"' in page
    assert ">save<" not in page
    assert f'id="exercise-{le_freak.id}-notes"' in page


def test_clearing_the_notes_on_a_row_clears_them(client, conn, le_freak):
    client.patch(f"/exercises/{le_freak.id}", data={"notes": "hi"}, headers=hx())

    client.patch(f"/exercises/{le_freak.id}", data={"notes": ""}, headers=hx())

    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert not after.notes


def test_a_track_saves_on_change_with_no_save_button(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert f'hx-patch="/media/{source.id}"' in page
    assert ">save<" not in page
    assert "name the set" not in page


def outside_templates(page: str) -> str:
    """The page as the browser first draws it: `<template>` is inert markup."""
    return re.sub(r"<template>.*?</template>", "", page, flags=re.S)


def test_the_log_shows_text_and_keeps_the_boxes_in_templates_until_a_click(
    client, sample_block
):
    page = client.get("/").text
    drawn = outside_templates(page)

    assert "<input" not in drawn
    assert "<textarea" not in drawn
    assert "019 Tempo Builder" in drawn  # plain text
    assert "<template>" in page  # and the box that replaces it
    assert 'class="cell-text" tabindex="0"' in page  # reachable by keyboard


def test_exercise_rows_show_text_until_a_click(client, songs, le_freak):
    page = client.get("/modules/songs").text
    drawn = outside_templates(
        page[page.index('<tbody id="queue">') : page.index("</tbody>")]
    )

    assert 'name="speed"' not in drawn
    assert 'name="notes"' not in drawn
    assert "le freak" in drawn


def test_a_track_shows_text_until_a_click(client, conn, le_freak, loop_wav):
    media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    drawn = outside_templates(client.get(f"/exercises/{le_freak.id}/media").text)

    assert 'name="gain"' not in drawn
    assert 'name="muted"' in drawn  # a checkbox is already a click


def test_notes_open_as_a_wide_box_of_at_least_two_lines(
    client, sample_block, songs, le_freak
):
    log = client.get("/").text
    row = client.get("/modules/songs").text
    row = row[row.index('<tbody id="queue">') : row.index("</tbody>")]

    for page in (log, row):
        assert 'class="cell-text wide"' in page
        assert re.search(r'<textarea class="cell"[^>]*rows="2"', page)
        assert 'cols="' not in " ".join(re.findall(r"<textarea.*?>", page, re.S))


def test_stop_on_a_row_closes_the_start_button_line_and_schedules_the_row(
    client, conn, le_freak
):
    session.start_ad_hoc(conn, rng=SteadyRandom(), description="Practice", now=NOW)

    response = stop(client, le_freak.id)

    assert response.status_code == 200
    assert running(conn) is None
    after = repo.get_exercise(conn, le_freak.id)
    assert after is not None
    assert after.practiced_count == 9


def test_stop_is_a_box_of_buttons_one_per_algorithm_not_a_dropdown(
    client, songs, le_freak
):
    page = client.get("/modules/songs").text
    row = page[page.index('<tbody id="queue">') : page.index("</tbody>")]
    box = row[row.index('class="stop-box"') : row.index("</fieldset>")]

    assert "<select" not in row
    assert "<legend>stop</legend>" in box
    for algorithm in ("normal", "short", "long", "rotate", "hold"):
        assert f'name="algorithm" value="{algorithm}"' in box
    assert box.count("<button") == 5


def test_a_stop_button_carries_its_algorithm_to_the_server(client, conn, le_freak):
    start(client, le_freak.id)

    response = client.post(
        f"/exercises/{le_freak.id}/stop", data={"algorithm": "hold"}, headers=hx()
    )

    assert response.status_code == 200
    assert running(conn) is None


def test_the_stop_buttons_are_flat_colours_that_step_down_as_a_column():
    css = (Path(deps.__file__).parent / "static" / "app.css").read_text()

    steps = re.findall(
        r"\.stop-box button:nth-of-type\((\d)\) \{ background: (#\w+); \}", css
    )
    assert [n for n, _ in steps] == ["1", "2", "3", "4", "5"]
    tones = [int(colour[1:3], 16) for _, colour in steps]
    assert tones == sorted(tones, reverse=True) and len(set(tones)) == 5
    assert "linear-gradient" not in css[css.index(".stop-box") :]


# --- playback: peaks, extracted audio, pitch (docs/plans/05-playback.md) ----


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """The render cache, kept out of the real data directory."""
    monkeypatch.setenv("MUSIC_TOOLS_DB", str(tmp_path / "data" / "practice.db"))
    return tmp_path / "data" / "cache"


@pytest.fixture
def lesson_mp4(roots):
    import subprocess

    path = roots / "S" / "lesson.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def test_peaks_come_back_as_min_max_pairs(client, conn, le_freak, loop_wav, cache):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.get(f"/media/{source.id}/peaks?buckets=50")

    assert response.status_code == 200
    peaks = response.json()["peaks"]
    assert len(peaks) == 50
    assert peaks[0] == [0.0, 0.0]  # four seconds of silence
    assert response.json()["duration"] == pytest.approx(4.0, abs=0.05)


def test_peaks_for_media_that_is_not_there_is_404(client, cache):
    assert client.get("/media/404/peaks").status_code == 404


def test_peaks_refuse_a_path_outside_the_roots(
    client, conn, le_freak, loop_wav, cache, tmp_path, monkeypatch
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    elsewhere = tmp_path / "OTHER"
    elsewhere.mkdir()
    monkeypatch.setenv("MUSIC_TOOLS_MEDIA_ROOTS", str(elsewhere))

    assert client.get(f"/media/{source.id}/peaks").status_code == 403


def test_a_bucket_count_nobody_could_draw_is_refused(
    client, conn, le_freak, loop_wav, cache
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    assert client.get(f"/media/{source.id}/peaks?buckets=0").status_code == 422
    assert client.get(f"/media/{source.id}/peaks?buckets=999999").status_code == 422


def test_the_audio_of_a_plain_file_is_the_file_itself(
    client, conn, le_freak, loop_wav, cache
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.get(f"/media/{source.id}/audio")

    assert response.status_code == 200
    assert response.content == loop_wav.read_bytes()
    assert not cache.exists()


def test_the_audio_of_a_video_is_extracted_into_the_cache(
    client, conn, le_freak, lesson_mp4, cache
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(lesson_mp4), now=NOW
    )

    response = client.get(f"/media/{source.id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] in ("audio/x-wav", "audio/wav")
    assert len(list(cache.glob("*.wav"))) == 1


def test_a_video_has_peaks_too(client, conn, le_freak, lesson_mp4, cache):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(lesson_mp4), now=NOW
    )

    peaks = client.get(f"/media/{source.id}/peaks?buckets=10").json()["peaks"]

    assert len(peaks) == 10
    assert max(high for _, high in peaks) > 0.1  # the sine, not silence


def test_a_pitch_shifted_audio_is_a_render_in_the_cache(
    client, conn, le_freak, loop_wav, cache
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    response = client.get(f"/media/{source.id}/audio?semitones=3")

    assert response.status_code == 200
    assert response.content != loop_wav.read_bytes()
    assert len(list(cache.glob("*.wav"))) == 1


def test_a_shift_beyond_an_octave_is_refused(client, conn, le_freak, loop_wav, cache):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )

    assert client.get(f"/media/{source.id}/audio?semitones=13").status_code == 422


def test_audio_answers_ranges_like_the_file_route(
    client, conn, le_freak, lesson_mp4, cache
):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(lesson_mp4), now=NOW
    )

    response = client.get(f"/media/{source.id}/audio", headers={"Range": "bytes=0-9"})

    assert response.status_code == 206


def test_audio_of_a_file_that_has_gone_is_409(client, conn, le_freak, loop_wav, cache):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    loop_wav.unlink()

    assert client.get(f"/media/{source.id}/audio").status_code == 409


def test_a_file_ffmpeg_cannot_read_is_a_409_naming_it(
    client, conn, le_freak, roots, cache
):
    junk = roots / "junk.mp4"
    junk.write_bytes(b"not a video")
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(junk), now=NOW
    )

    response = client.get(f"/media/{source.id}/audio")

    assert response.status_code == 409
    assert "junk.mp4" in response.text


# --- the speed slider writes back (Phase 5a step 6) --------------------------


def speed_of(conn, exercise_id: int) -> str | None:
    exercise = repo.get_exercise(conn, exercise_id)
    assert exercise is not None
    return exercise.speed


def test_the_slider_writes_the_speed_in_the_exercises_own_dialect(client, conn, songs):
    row = repo.create_exercise(
        conn, module_id=songs.id, name="percent", speed="66%", target_bpm=120
    )
    bare = repo.create_exercise(
        conn, module_id=songs.id, name="bare", speed="88", target_bpm=120
    )

    one = client.post(f"/exercises/{row.id}/speed", data={"ratio": "0.8"})
    two = client.post(f"/exercises/{bare.id}/speed", data={"ratio": "0.8"})

    assert one.status_code == two.status_code == 200
    assert one.json()["speed"] == "80%"
    assert two.json()["speed"] == "96"
    assert speed_of(conn, row.id) == "80%"
    assert speed_of(conn, bare.id) == "96"


def test_the_slider_answers_with_the_text_the_page_shows(client, conn, songs):
    row = repo.create_exercise(
        conn, module_id=songs.id, name="percent", speed="66%", target_bpm=120
    )

    answer = client.post(f"/exercises/{row.id}/speed", data={"ratio": "0.8"}).json()

    assert answer["text"] == "96 BPM (80%)"


def test_without_a_target_there_is_no_ratio_to_write(client, conn, songs):
    row = repo.create_exercise(conn, module_id=songs.id, name="x", speed="66%")

    response = client.post(f"/exercises/{row.id}/speed", data={"ratio": "0.8"})

    assert response.status_code == 400
    assert speed_of(conn, row.id) == "66%"


def test_a_ratio_the_slider_could_not_send_is_refused(client, conn, songs):
    row = repo.create_exercise(
        conn, module_id=songs.id, name="x", speed="66%", target_bpm=120
    )

    assert (
        client.post(f"/exercises/{row.id}/speed", data={"ratio": "1.5"}).status_code
        == 400
    )


def test_the_slider_on_a_missing_exercise_is_404(client):
    assert client.post("/exercises/404/speed", data={"ratio": "0.8"}).status_code == 404


def test_a_lone_file_gets_a_player_wired_to_its_urls(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    start(client, le_freak.id)

    page = client.get("/").text

    assert 'class="player"' in page
    assert f'data-peaks-url="/media/{source.id}/peaks"' in page
    assert f'data-audio-url="/media/{source.id}/audio"' in page
    assert f'data-speed-url="/exercises/{le_freak.id}/speed"' in page
    assert "/static/player.js" in page


def test_the_slider_starts_at_the_exercises_ratio(client, conn, songs, loop_wav):
    row = repo.create_exercise(
        conn, module_id=songs.id, name="x", speed="75%", target_bpm=120
    )
    media.attach(conn, exercise_id=row.id, kind="file", path=str(loop_wav), now=NOW)
    start(client, row.id)

    page = client.get("/").text

    assert 'data-ratio="0.75"' in page
    assert "disabled" not in page.split('class="speed"')[1].split("</label>")[0]


def test_with_no_target_the_slider_sits_at_one_and_is_disabled(
    client, conn, songs, loop_wav
):
    row = repo.create_exercise(conn, module_id=songs.id, name="x", speed="75%")
    media.attach(conn, exercise_id=row.id, kind="file", path=str(loop_wav), now=NOW)
    start(client, row.id)

    page = client.get("/").text
    slider = page.split('class="speed"')[1].split("</label>")[0]

    assert 'data-ratio="1"' in page
    assert "disabled" in slider
    assert "target" in slider  # says why


def test_a_track_set_keeps_its_stacked_players_until_5b(
    client, conn, le_freak, loop_wav, roots
):
    from pydub import AudioSegment

    drums = roots / "S" / "le freak" / "drums.wav"
    AudioSegment.silent(duration=4000).export(drums, format="wav")
    first = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="file",
        path=str(drums),
        group_id=first.group_id,
        now=NOW,
    )
    start(client, le_freak.id)

    page = client.get("/").text

    assert page.count("<audio") == 2
    assert 'class="player"' not in page


def test_the_media_page_says_how_to_add_a_sound_file(client, le_freak, roots):
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert 'id="how-to-attach"' in page
    assert "absolute path" in page  # what to type
    assert "Finder" in page  # and how to get one
    assert "start" in page  # and where it plays afterwards
    assert "semitones" in page or "pitch" in page


def test_an_empty_media_page_points_at_the_instructions(client, le_freak, roots):
    page = client.get(f"/exercises/{le_freak.id}/media").text

    assert 'href="#how-to-attach"' in page


def test_the_media_link_on_a_row_says_what_it_is_for(client, le_freak):
    page = client.get("/modules/songs").text

    assert "attach or play a sound file" in page  # the link's tooltip


def test_the_speed_and_target_are_edited_in_the_speed_column(client, le_freak):
    """The column headed speed is where a player goes to change the speed."""
    page = client.get("/modules/songs").text
    row = page.split(f'id="exercise-{le_freak.id}"')[1].split("</tr>")[0]
    cells = row.split("<td")
    speed_cell = next(c for c in cells if f'id="tempo-{le_freak.id}"' in c)
    name_cell = next(c for c in cells if 'name="name"' in c)

    for field in ("speed", "target_bpm"):
        assert f'id="exercise-{le_freak.id}-{field}"' in speed_cell
        assert f'id="exercise-{le_freak.id}-{field}"' not in name_cell


def test_speed_still_saves_from_its_own_form(client, conn, le_freak):
    response = client.patch(
        f"/exercises/{le_freak.id}", data={"speed": "70%"}, headers=hx()
    )

    assert response.status_code == 200
    assert speed_of(conn, le_freak.id) == "70%"


def test_a_track_sets_labels_and_players_sit_in_one_grid(
    client, conn, le_freak, loop_wav, roots
):
    from pydub import AudioSegment

    drums = roots / "S" / "le freak" / "drums.wav"
    AudioSegment.silent(duration=4000).export(drums, format="wav")
    first = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    media.attach(
        conn,
        exercise_id=le_freak.id,
        kind="file",
        path=str(drums),
        group_id=first.group_id,
        now=NOW,
    )
    start(client, le_freak.id)

    page = client.get("/").text
    grid = page.split('class="tracks"')[1].split("</article>")[0]

    assert grid.count('class="track"') == 2
    assert grid.count("<audio") == 2
    assert grid.count('class="track-name"') == 2
