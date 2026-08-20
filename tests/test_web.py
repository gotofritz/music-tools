"""The browser front end: routes in, HTML fragments out.

`docs/plans/03-web.md`. The routes are thin over `domain/session.py` and
`domain/catalogue.py`, so this suite is about what reaches the page — the
markup HTMX swaps on, and the numbers the spreadsheet used to show.

The clock and the rng are dependencies, overridden here the way `cli.py`
injects them, so a test can pin "now" without `freezegun`.
"""

from datetime import date, datetime, time
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from music_tools.db import repository as repo
from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.domain import media
from music_tools.web import deps
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


def test_with_nothing_running_the_page_says_so(client):
    page = client.get("/").text
    assert "Nothing running" in page
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


def test_an_ad_hoc_entry_starts_against_no_exercise(client, conn):
    response = client.post(
        "/entries",
        data={"description": "warm-up", "log_group": "TECHNIQUE"},
        headers=hx(),
    )

    assert response.status_code == 200
    entry = running(conn)
    assert entry is not None
    assert (entry.description, entry.exercise_id) == ("warm-up", None)


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
    """Six finished days before the pinned one, one entry each."""
    for number in range(1, 7):
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

    assert "2026-06-01" not in page  # the sixth-oldest, past the page of 5
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


# --- correcting a line of the log -------------------------------------------


def test_the_log_is_read_only_until_you_ask_to_edit_it(client, sample_block, conn):
    entry = repo.entries_for_day(conn, sample_block.id)[0]

    page = client.get("/").text

    assert f'action="/entries/{entry.id}"' not in page  # no forms lying around
    assert "<input" not in page
    assert "019 Tempo Builder" in page  # just the day, as written
    assert 'href="/days/2026-07-05/edit"' in page  # and a way in


def test_the_edit_button_opens_that_day_and_nothing_else(client, earlier_days):
    page = client.get("/").text

    assert 'href="/days/2026-06-06/edit"' in page
    assert 'href="/days/2026-06-05/edit"' in page  # one per day, not one for all


def test_editing_a_day_puts_boxes_round_its_lines(client, earlier_days):
    response = client.get("/days/2026-06-06/edit", headers=hx())

    assert response.status_code == 200
    assert 'id="day-2026-06-06"' in response.text  # the same block, swapped
    assert 'value="day 6"' in response.text
    assert 'value="20:00"' in response.text
    assert 'href="/days/2026-06-06"' in response.text  # and a way back out


def controls(page: str) -> list[dict[str, str]]:
    """The boxes and buttons on a page, with the attributes they carry.

    A form cannot span table cells — the browser closes it at the first
    `</td>` — so a box in a later cell reaches its form only through the
    `form` attribute. Reading that attribute back is as close as a
    server-side test gets to the parse the browser will do.
    """
    found: list[dict[str, str]] = []

    class Reader(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in {"input", "button", "select"}:
                found.append({"tag": tag, **{key: value or "" for key, value in attrs}})

    Reader().feed(page)
    return found


def test_every_box_on_an_edit_row_names_the_form_it_belongs_to(
    client, conn, sample_block
):
    page = client.get("/days/2026-07-05/edit", headers=hx()).text
    boxes = controls(page)

    for entry in repo.entries_for_day(conn, sample_block.id):
        form_id = f"entry-{entry.id}-edit"
        assert f'id="{form_id}"' in page
        mine = [box for box in boxes if box.get("form") == form_id]
        assert {box["name"] for box in mine if box["tag"] == "input"} == {
            "started_at",
            "ended_at",
            "description",
            "notes",
            "speed",
            "log_group",
        }
        # the button too: it sits in the last cell, outside the form's element
        assert [box for box in mine if box["tag"] == "button"]


def test_leaving_edit_mode_gives_the_plain_day_back(client, earlier_days):
    response = client.get("/days/2026-06-06", headers=hx())

    assert "<input" not in response.text
    assert "day 6" in response.text
    assert 'href="/days/2026-06-06/edit"' in response.text


def test_todays_own_log_is_editable_the_same_way(client, sample_block):
    response = client.get("/days/2026-07-05/edit", headers=hx())

    assert '<section id="day-log"' in response.text  # today is the log, not a block
    assert 'value="019 Tempo Builder"' in response.text


def test_a_day_nothing_was_logged_on_is_404(client):
    assert client.get("/days/2020-01-01/edit").status_code == 404


def test_the_edit_link_is_a_whole_page_without_htmx(client, earlier_days):
    response = client.get("/days/2026-06-06/edit")

    assert "<html" in response.text
    assert 'value="day 6"' in response.text


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
    assert "<input" in response.text  # still editing: the next line may be wrong too
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


def test_a_line_can_be_removed_while_the_day_is_open_for_editing(
    client, conn, sample_block
):
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


def test_the_remove_button_is_only_there_in_edit_mode_and_asks_first(
    client, conn, earlier_days
):
    day = repo.get_day(conn, date(2026, 6, 6))
    assert day is not None
    entry = repo.entries_for_day(conn, day.id)[0]

    plain = client.get("/days/2026-06-06", headers=hx()).text
    editing = client.get("/days/2026-06-06/edit", headers=hx()).text

    assert f"/entries/{entry.id}/delete" not in plain
    assert f'action="/entries/{entry.id}/delete"' in editing
    assert "hx-confirm" in editing  # one click from gone is one click too few


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

    assert f'src="/media/{source.id}/file"' in page
    assert "<audio" in page
    assert "loop.wav" in page


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


def test_the_file_route_is_404_when_the_file_has_gone(client, conn, le_freak, loop_wav):
    source = media.attach(
        conn, exercise_id=le_freak.id, kind="file", path=str(loop_wav), now=NOW
    )
    loop_wav.unlink()

    assert client.get(f"/media/{source.id}/file").status_code == 404


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
