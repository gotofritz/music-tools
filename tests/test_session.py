"""The repository, marking an exercise done, and the day totals.

Steps 4 to 6 of docs/plans/02-domain.md. The first half is storage — SQL in,
pydantic out. The second half is `doneExercise_`, which did five things at
once and here does them in one transaction.
"""

from datetime import date, datetime, timedelta

import pytest

from music_tools.db import repository as repo
from music_tools.db.connection import transaction
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import (
    day_summary,
    format_duration,
    mark_done,
    practice_day_for,
    restart_clock,
    start_day,
)

NOW = datetime(2026, 7, 5, 22, 27)


def loaded[T](value: T | None) -> T:
    """A row the test just wrote is always there; this says so to the checker."""
    assert value is not None
    return value


@pytest.fixture
def slap(db):
    return repo.create_module(db, name="SLAP", log_group="TECHNIQUE")


@pytest.fixture
def songs(db):
    return repo.create_module(db, name="SONGS", log_group="REPERTOIRE")


@pytest.fixture
def stomp(db, slap):
    return repo.create_exercise(
        db,
        module_id=slap.id,
        name="Stomp!",
        speed="80%",
        target_bpm=133.0,
        practiced_count=8,
        last_practiced=date(2026, 6, 1),
        next_due=date(2026, 7, 1),
    )


# --- Step 4: the repository -------------------------------------------------


def test_a_module_round_trips_and_gets_a_slug(db):
    module = repo.create_module(db, name="BASS SLAP", log_group="TECHNIQUE")

    assert module.slug == "bass-slap"
    assert repo.get_module(db, module.id) == module
    assert repo.find_module(db, "bass slap") == module


def test_an_exercise_round_trips_with_a_target(db, stomp):
    assert repo.get_exercise(db, stomp.id) == stomp
    assert stomp.target_bpm == 133.0
    assert stomp.speed == "80%"


def test_an_exercise_round_trips_without_a_target(db, songs):
    exercise = repo.create_exercise(db, module_id=songs.id, name="le freak")

    stored = loaded(repo.get_exercise(db, exercise.id))
    assert stored.target_bpm is None
    assert stored.practiced_count == 0
    assert stored.extra is None


def test_the_extra_column_carries_json(db, songs):
    exercise = repo.create_exercise(
        db, module_id=songs.id, name="espresso", extra={"tuning": "drop D"}
    )

    assert loaded(repo.get_exercise(db, exercise.id)).extra == {"tuning": "drop D"}


def test_exercises_come_back_by_due_date_with_nulls_last(db, songs):
    for name, due in [
        ("late", date(2026, 12, 3)),
        ("undated", None),
        ("early", date(2026, 8, 1)),
    ]:
        repo.create_exercise(db, module_id=songs.id, name=name, next_due=due)

    ordered = repo.exercises_due(db, module_id=songs.id)

    assert [exercise.name for exercise in ordered] == ["early", "late", "undated"]


def test_only_what_is_due_comes_back_when_a_date_is_given(db, songs):
    repo.create_exercise(db, module_id=songs.id, name="due", next_due=date(2026, 8, 1))
    repo.create_exercise(
        db, module_id=songs.id, name="later", next_due=date(2027, 1, 1)
    )
    repo.create_exercise(db, module_id=songs.id, name="undated")

    due = repo.exercises_due(db, module_id=songs.id, on=date(2026, 8, 1))

    assert [exercise.name for exercise in due] == ["due"]


def test_archived_exercises_are_left_out(db, songs):
    repo.create_exercise(db, module_id=songs.id, name="kept", next_due=date(2026, 8, 1))
    gone = repo.create_exercise(db, module_id=songs.id, name="gone")
    repo.update_exercise(db, gone.id, archived_at=NOW)

    assert [e.name for e in repo.exercises_due(db, module_id=songs.id)] == ["kept"]


def test_module_dues_can_exclude_the_row_being_scheduled(db, songs):
    one = repo.create_exercise(
        db, module_id=songs.id, name="one", next_due=date(2026, 8, 1)
    )
    repo.create_exercise(db, module_id=songs.id, name="two", next_due=date(2026, 9, 9))
    repo.create_exercise(db, module_id=songs.id, name="undated")

    assert repo.module_dues(db, module_id=songs.id) == [
        date(2026, 8, 1),
        date(2026, 9, 9),
    ]
    assert repo.module_dues(db, module_id=songs.id, excluding=one.id) == [
        date(2026, 9, 9)
    ]


def test_a_write_inside_a_failed_transaction_leaves_nothing_behind(db, songs):
    with pytest.raises(RuntimeError):
        with transaction(db):
            repo.create_exercise(db, module_id=songs.id, name="doomed")
            raise RuntimeError("boom")

    assert repo.find_exercises(db, "doomed") == []


def test_an_exercise_name_is_unique_within_its_module(db, songs, slap):
    repo.create_exercise(db, module_id=songs.id, name="le freak")

    with pytest.raises(Exception):
        repo.create_exercise(db, module_id=songs.id, name="le freak")

    # ... but the same name in another module is a different exercise
    assert repo.create_exercise(db, module_id=slap.id, name="le freak").id is not None


# --- Step 5: marking an exercise done ---------------------------------------


def test_done_moves_the_schedule(db, stomp, steady_rng):
    result = mark_done(
        db,
        exercise_id=stomp.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=steady_rng,
    )

    assert result.exercise.practiced_count == 9
    assert result.exercise.last_practiced == date(2026, 7, 5)
    # count 9 reads INTERVALS[9] = 55, scaled by the 80% ratio: 44 days
    assert result.exercise.next_due == date(2026, 7, 5) + timedelta(days=44)


def test_done_closes_the_running_entry_and_opens_the_next(db, stomp, steady_rng):
    start_day(db, now=datetime(2026, 7, 5, 22, 20))

    result = mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    assert result.closed.started_at == datetime(2026, 7, 5, 22, 20)
    assert result.closed.ended_at == NOW
    assert result.opened.started_at == NOW
    assert result.opened.ended_at is None


def test_the_closed_entry_is_a_snapshot(db, stomp, slap, steady_rng):
    result = mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )
    repo.update_exercise(db, stomp.id, name="Stomp! (renamed)", speed="100%")

    entry = loaded(repo.get_entry(db, result.closed.id))
    assert entry.description == "Stomp!"
    assert entry.speed == "80%"
    assert entry.bpm == pytest.approx(106.4)  # 80% of 133
    assert entry.log_group == "TECHNIQUE"
    assert entry.exercise_id == stomp.id


def test_done_with_no_day_open_starts_one_from_that_moment(db, stomp, steady_rng):
    result = mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    assert repo.get_day(db, date(2026, 7, 5)) is not None
    assert result.closed.started_at == NOW
    assert result.closed.ended_at == NOW


def test_a_running_entry_left_over_from_an_earlier_day_is_discarded(
    db, stomp, steady_rng
):
    start_day(db, now=datetime(2026, 7, 4, 21, 0))  # nobody stopped the clock

    mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    yesterday = loaded(repo.get_day(db, date(2026, 7, 4)))
    assert repo.entries_for_day(db, yesterday.id) == []


def test_done_is_one_transaction(db, stomp, slap, steady_rng, monkeypatch):
    day = start_day(db, now=datetime(2026, 7, 5, 22, 20))
    running = loaded(repo.running_entry(db, day_id=day.id))

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    # the last write mark_done does: everything before it must roll back
    monkeypatch.setattr(repo, "create_entry", explode)

    with pytest.raises(RuntimeError):
        mark_done(
            db,
            exercise_id=stomp.id,
            algorithm=Algorithm.NORMAL,
            now=NOW,
            rng=steady_rng,
        )

    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 8
    assert loaded(repo.get_entry(db, running.id)).ended_at is None


def test_hold_scans_the_module_without_the_exercise_itself(db, slap, stomp, steady_rng):
    repo.create_exercise(
        db, module_id=slap.id, name="Skips", next_due=date(2026, 6, 15)
    )

    # stomp is due 2026-07-01; the day in front of the *other* row is sooner
    result = mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.HOLD, now=NOW, rng=steady_rng
    )

    assert result.exercise.next_due == date(2026, 6, 14)


def test_rotate_scans_the_module_including_the_exercise_itself(db, slap, steady_rng):
    back = repo.create_exercise(
        db, module_id=slap.id, name="Skips", next_due=date(2027, 1, 5)
    )

    result = mark_done(
        db, exercise_id=back.id, algorithm=Algorithm.ROTATE, now=NOW, rng=steady_rng
    )

    assert result.exercise.next_due == date(2027, 1, 5)


# --- Step 6: days, totals and the 4am boundary ------------------------------


@pytest.mark.parametrize(
    "now,day",
    [
        (datetime(2026, 7, 6, 1, 30), date(2026, 7, 5)),
        (datetime(2026, 7, 6, 4, 30), date(2026, 7, 6)),
        (datetime(2026, 7, 6, 3, 59), date(2026, 7, 5)),
        (datetime(2026, 7, 6, 22, 0), date(2026, 7, 6)),
    ],
)
def test_practice_past_midnight_belongs_to_the_evening_it_started(now, day):
    assert practice_day_for(now) == day


def test_an_entry_across_midnight_counts_forwards(db, songs):
    day = start_day(db, now=datetime(2026, 7, 5, 23, 50))
    entry = loaded(repo.running_entry(db, day_id=day.id))
    repo.close_entry(
        db,
        entry.id,
        ended_at=datetime(2026, 7, 6, 0, 20),
        description="le freak",
        log_group="REPERTOIRE",
    )

    summary = day_summary(db, day=date(2026, 7, 5))

    assert summary.total_seconds == 30 * 60


def test_the_sample_day_totals_match_the_spreadsheet(db, sample_day):
    summary = day_summary(db, day=date(2026, 7, 5))

    assert [
        (group.log_group, format_duration(group.seconds)) for group in summary.groups
    ] == [
        ("TECHNIQUE", "00:19"),
        ("REPERTOIRE", "00:34"),
    ]
    assert format_duration(summary.total_seconds) == "00:53"


def test_log_groups_need_not_be_contiguous(db, sample_day):
    # TECHNIQUE, REPERTOIRE, then TECHNIQUE again: one subtotal, not two.
    day = loaded(repo.get_day(db, date(2026, 7, 5)))
    entry = repo.create_entry(
        db, day_id=day.id, started_at=datetime(2026, 7, 5, 23, 20), description="extra"
    )
    repo.close_entry(
        db,
        entry.id,
        ended_at=datetime(2026, 7, 5, 23, 30),
        description="extra",
        log_group="TECHNIQUE",
    )

    summary = day_summary(db, day=date(2026, 7, 5))

    assert [group.log_group for group in summary.groups] == ["TECHNIQUE", "REPERTOIRE"]
    assert format_duration(summary.groups[0].seconds) == "00:29"
    assert format_duration(summary.total_seconds) == "01:03"


def test_a_running_entry_counts_up_to_now(db, songs):
    day = start_day(db, now=datetime(2026, 7, 5, 22, 0))
    entry = loaded(repo.running_entry(db, day_id=day.id))
    repo.close_entry(
        db,
        entry.id,
        ended_at=datetime(2026, 7, 5, 22, 10),
        description="le freak",
        log_group="REPERTOIRE",
    )
    repo.create_entry(
        db,
        day_id=day.id,
        started_at=datetime(2026, 7, 5, 22, 10),
        log_group="REPERTOIRE",
    )

    summary = day_summary(db, day=date(2026, 7, 5), now=datetime(2026, 7, 5, 22, 25))

    assert format_duration(summary.total_seconds) == "00:25"


def test_a_stale_running_entry_adds_nothing_to_an_earlier_day(db, songs):
    start_day(db, now=datetime(2026, 7, 4, 21, 0))

    summary = day_summary(db, day=date(2026, 7, 4), now=datetime(2026, 7, 5, 22, 25))

    assert summary.total_seconds == 0


# --- Starting again after a break -------------------------------------------


def test_start_discards_the_gap_and_runs_from_now(db, songs, steady_rng):
    day = start_day(db, now=datetime(2026, 7, 5, 22, 20))

    result = restart_clock(db, now=datetime(2026, 7, 5, 23, 40))

    assert result.opened.started_at == datetime(2026, 7, 5, 23, 40)
    assert result.opened.ended_at is None
    assert result.dropped_seconds == 80 * 60
    # one entry, running from the restart: the 80 minutes are simply not there
    entries = repo.entries_for_day(db, day.id)
    assert [entry.started_at for entry in entries] == [datetime(2026, 7, 5, 23, 40)]


def test_start_leaves_what_was_already_logged_alone(db, stomp, steady_rng):
    mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    restart_clock(db, now=datetime(2026, 7, 5, 23, 40))

    day = loaded(repo.get_day(db, date(2026, 7, 5)))
    entries = repo.entries_for_day(db, day.id)
    assert [entry.description for entry in entries] == ["Stomp!", ""]
    assert loaded(entries[0].ended_at) == NOW


def test_the_gap_is_never_practice_time(db, stomp, steady_rng):
    mark_done(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )
    restart_clock(db, now=datetime(2026, 7, 5, 23, 40))

    summary = day_summary(db, day=date(2026, 7, 5), now=datetime(2026, 7, 5, 23, 50))

    # the 10 minutes since the restart, and none of the 73 before it
    assert format_duration(summary.total_seconds) == "00:10"


def test_start_with_no_day_open_starts_one(db):
    result = restart_clock(db, now=datetime(2026, 7, 5, 22, 20))

    assert repo.get_day(db, date(2026, 7, 5)) is not None
    assert result.opened.started_at == datetime(2026, 7, 5, 22, 20)
    assert result.dropped_seconds == 0


def test_start_discards_a_clock_left_running_on_an_earlier_day(db):
    start_day(db, now=datetime(2026, 7, 4, 21, 0))

    restart_clock(db, now=datetime(2026, 7, 5, 22, 20))

    yesterday = loaded(repo.get_day(db, date(2026, 7, 4)))
    assert repo.entries_for_day(db, yesterday.id) == []
