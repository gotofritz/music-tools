"""The repository, starting and finishing an exercise, and the day totals.

Steps 4 to 6 of docs/plans/02-domain.md, reworked by step 2 of
docs/plans/04-exercise-media.md. The first half is storage — SQL in, pydantic
out. The second half used to be `doneExercise_`, which tiled the session end to
end; now **start** opens an entry and **done** closes it, and the gaps between
them are gaps.
"""

from datetime import date, datetime, timedelta

import pytest

from music_tools.db import repository as repo
from music_tools.db.connection import transaction
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import (
    EntryClosed,
    EntryRunning,
    UnknownEntry,
    UnknownExercise,
    amend_entry,
    current_entry,
    day_summary,
    delete_entry,
    discard_entry,
    entry_duration,
    finish_entry,
    format_duration,
    practice_day_for,
    recent_days,
    start_ad_hoc,
    start_day,
    start_exercise,
    stop_exercise,
)
from tests.conftest import SteadyRandom

NOW = datetime(2026, 7, 5, 22, 27)
#: Jitter dialled out, so the dates a start schedules are assertable.
RNG = SteadyRandom()


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


# --- Step 5: start, and done ------------------------------------------------


def done(db, entry_id, rng, *, algorithm=Algorithm.NORMAL, now=None, notes=None):
    """`finish_entry` with the arguments every test would repeat."""
    return finish_entry(
        db,
        entry_id=entry_id,
        algorithm=algorithm,
        now=now if now is not None else NOW,
        rng=rng,
        notes=notes,
    )


def test_starting_an_exercise_logs_it_straight_away(db, stomp, slap):
    result = start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    assert result.entry.exercise_id == stomp.id
    assert result.entry.started_at == NOW
    assert result.entry.ended_at is None
    assert result.closed is None
    # snapshotted at the start, because that is when the line becomes visible
    assert result.entry.description == "Stomp!"
    assert result.entry.speed == "80%"
    assert result.entry.bpm == pytest.approx(106.4)  # 80% of 133
    assert result.entry.log_group == "TECHNIQUE"


def test_starting_an_exercise_opens_the_day_it_falls_in(db, stomp):
    start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    assert repo.get_day(db, date(2026, 7, 5)) is not None


def test_starting_does_not_move_the_schedule(db, stomp):
    start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    still = loaded(repo.get_exercise(db, stomp.id))
    assert still.practiced_count == 8
    assert still.next_due == date(2026, 7, 1)


def test_the_snapshot_does_not_follow_a_rename(db, stomp, slap):
    result = start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    repo.update_exercise(db, stomp.id, name="Stomp! (renamed)", speed="100%")

    assert loaded(repo.get_entry(db, result.entry.id)).description == "Stomp!"


def test_starting_the_next_exercise_closes_the_one_that_was_running(db, slap, stomp):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG)

    result = start_exercise(db, exercise_id=other.id, now=NOW, rng=RNG)

    # attributed when it was started, so closing it at that instant is honest
    assert loaded(result.closed).description == "Stomp!"
    assert loaded(result.closed).ended_at == NOW
    assert current_entry(db, now=NOW) == result.entry


def test_closing_the_previous_entry_schedules_it_the_normal_way(db, slap, stomp):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG)

    start_exercise(db, exercise_id=other.id, now=NOW, rng=RNG)

    # nobody else is going to move it: the start that closed it says `done`
    moved = loaded(repo.get_exercise(db, stomp.id))
    assert moved.practiced_count == 9
    assert moved.last_practiced == date(2026, 7, 5)
    # count 9 reads INTERVALS[9] = 55, scaled by the 80% ratio: 44 days
    assert moved.next_due == date(2026, 7, 5) + timedelta(days=44)


def test_something_ad_hoc_also_schedules_what_it_closed(db, stomp):
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG)

    start_ad_hoc(db, description="warm-up", now=NOW, rng=RNG)

    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 9


def test_starting_the_exercise_already_running_leaves_it_where_it_was(db, stomp):
    first = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    again = start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    # the same line, still running from when it was really started
    assert again.entry.id == first.entry.id
    assert again.entry.started_at == datetime(2026, 7, 5, 22, 20)
    assert again.closed is None
    day = loaded(repo.get_day(db, date(2026, 7, 5)))
    assert len(repo.entries_for_day(db, day.id)) == 1


def test_starting_an_exercise_that_is_not_there_writes_nothing(db):
    with pytest.raises(Exception):
        start_exercise(db, exercise_id=404, now=NOW, rng=RNG)

    assert repo.list_days(db) == []


def test_something_ad_hoc_is_started_against_no_exercise(db):
    result = start_ad_hoc(
        db, description="warm-up", log_group="TECHNIQUE", now=NOW, rng=RNG
    )

    assert result.entry.exercise_id is None
    assert result.entry.description == "warm-up"
    assert result.entry.log_group == "TECHNIQUE"
    assert result.entry.ended_at is None


def test_done_closes_the_entry_and_moves_the_schedule(db, stomp, steady_rng):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    result = done(db, started.entry.id, steady_rng)

    assert loaded(result.exercise).practiced_count == 9
    assert loaded(result.exercise).last_practiced == date(2026, 7, 5)
    # count 9 reads INTERVALS[9] = 55, scaled by the 80% ratio: 44 days
    assert loaded(result.exercise).next_due == date(2026, 7, 5) + timedelta(days=44)
    assert result.closed.started_at == datetime(2026, 7, 5, 22, 20)
    assert result.closed.ended_at == NOW
    assert current_entry(db, now=NOW) is None  # nothing follows it


def test_done_keeps_the_snapshot_the_start_took(db, stomp, slap, steady_rng):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )
    repo.update_exercise(db, stomp.id, name="Stomp! (renamed)", speed="100%")

    result = done(db, started.entry.id, steady_rng)

    assert result.closed.description == "Stomp!"
    assert result.closed.speed == "80%"
    assert result.closed.log_group == "TECHNIQUE"
    assert result.closed.exercise_id == stomp.id


def test_done_writes_a_note_when_one_is_given(db, stomp, steady_rng):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    result = done(db, started.entry.id, steady_rng, notes="left hand only")

    assert result.closed.notes == "left hand only"


def test_stop_finishes_the_exercise_that_is_running(db, stomp, steady_rng):
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG)

    result = stop_exercise(
        db,
        exercise_id=stomp.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=steady_rng,
    )

    assert loaded(loaded(result).exercise).practiced_count == 9
    assert loaded(result).closed.ended_at == NOW
    assert current_entry(db, now=NOW) is None


def test_stop_addressed_to_another_exercise_does_nothing(db, slap, stomp, steady_rng):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    result = stop_exercise(
        db,
        exercise_id=other.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=steady_rng,
    )

    assert result is None
    assert loaded(current_entry(db, now=NOW)).id == started.entry.id
    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 8


def test_stop_with_nothing_running_does_nothing(db, stomp, steady_rng):
    result = stop_exercise(
        db,
        exercise_id=stomp.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=steady_rng,
    )

    assert result is None
    assert repo.list_days(db) == []
    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 8


def test_stop_with_nothing_running_backfills_from_the_last_line(
    db, slap, stomp, steady_rng
):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    start_exercise(db, exercise_id=other.id, now=datetime(2026, 7, 5, 21, 50), rng=RNG)
    stop_exercise(
        db,
        exercise_id=other.id,
        algorithm=Algorithm.NORMAL,
        now=datetime(2026, 7, 5, 22, 10),
        rng=steady_rng,
    )

    result = stop_exercise(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    entry = loaded(result).closed
    # a microsecond after the line before it: the stretch since is this one
    assert entry.started_at == datetime(2026, 7, 5, 22, 10, 0, 1)
    assert entry.ended_at == NOW
    assert entry.exercise_id == stomp.id
    assert entry.description == "Stomp!"
    assert entry.speed == "80%"
    assert entry.log_group == "TECHNIQUE"
    assert loaded(loaded(result).exercise).practiced_count == 9
    assert current_entry(db, now=NOW) is None


def test_a_backfilled_stop_takes_the_algorithm_it_is_given(db, slap, stomp, steady_rng):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    start_exercise(db, exercise_id=other.id, now=datetime(2026, 7, 5, 21, 50), rng=RNG)
    stop_exercise(
        db,
        exercise_id=other.id,
        algorithm=Algorithm.NORMAL,
        now=datetime(2026, 7, 5, 22, 10),
        rng=steady_rng,
    )

    result = stop_exercise(
        db, exercise_id=stomp.id, algorithm=Algorithm.HOLD, now=NOW, rng=steady_rng
    )

    # HOLD keeps the row where it was due rather than reading the interval
    assert loaded(loaded(result).exercise).next_due == date(2026, 7, 1)


def test_stop_backfills_nothing_when_the_last_line_ends_at_now(
    db, slap, stomp, steady_rng
):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    start_exercise(db, exercise_id=other.id, now=datetime(2026, 7, 5, 21, 50), rng=RNG)
    stop_exercise(
        db,
        exercise_id=other.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=steady_rng,
    )

    result = stop_exercise(
        db, exercise_id=stomp.id, algorithm=Algorithm.NORMAL, now=NOW, rng=steady_rng
    )

    assert result is None
    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 8


def test_stop_for_an_exercise_that_is_not_there_is_refused(db, steady_rng):
    with pytest.raises(UnknownExercise):
        stop_exercise(
            db,
            exercise_id=404,
            algorithm=Algorithm.NORMAL,
            now=NOW,
            rng=steady_rng,
        )


def test_done_on_an_ad_hoc_entry_closes_it_and_schedules_nothing(db, steady_rng):
    started = start_ad_hoc(
        db, description="jam", now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    result = done(db, started.entry.id, steady_rng)

    assert result.exercise is None
    assert result.closed.ended_at == NOW


def test_done_twice_is_refused(db, stomp, steady_rng):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )
    done(db, started.entry.id, steady_rng)

    with pytest.raises(EntryClosed):
        done(db, started.entry.id, steady_rng)

    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 9


def test_done_on_an_entry_that_is_not_there_is_an_error(db, steady_rng):
    with pytest.raises(UnknownEntry):
        done(db, 404, steady_rng)


def test_done_is_one_transaction(db, stomp, slap, steady_rng, monkeypatch):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    # the last write done does: the close before it must roll back
    monkeypatch.setattr(repo, "update_exercise", explode)

    with pytest.raises(RuntimeError):
        done(db, started.entry.id, steady_rng)

    assert loaded(repo.get_exercise(db, stomp.id)).practiced_count == 8
    assert loaded(repo.get_entry(db, started.entry.id)).ended_at is None


def test_hold_scans_the_module_without_the_exercise_itself(db, slap, stomp, steady_rng):
    repo.create_exercise(
        db, module_id=slap.id, name="Skips", next_due=date(2026, 6, 15)
    )
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    # stomp is due 2026-07-01; the day in front of the *other* row is sooner
    result = done(db, started.entry.id, steady_rng, algorithm=Algorithm.HOLD)

    assert loaded(result.exercise).next_due == date(2026, 6, 14)


def test_rotate_scans_the_module_including_the_exercise_itself(db, slap, steady_rng):
    back = repo.create_exercise(
        db, module_id=slap.id, name="Skips", next_due=date(2027, 1, 5)
    )
    started = start_exercise(
        db, exercise_id=back.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    result = done(db, started.entry.id, steady_rng, algorithm=Algorithm.ROTATE)

    assert loaded(result.exercise).next_due == date(2027, 1, 5)


# --- a false start, and the day boundary ------------------------------------


def test_a_false_start_is_discarded_rather_than_logged(db, stomp):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )

    discard_entry(db, entry_id=started.entry.id)

    assert repo.get_entry(db, started.entry.id) is None
    assert day_summary(db, day=date(2026, 7, 5), now=NOW).total_seconds == 0


def test_a_finished_line_is_not_discarded(db, stomp, steady_rng):
    started = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 20), rng=RNG
    )
    done(db, started.entry.id, steady_rng)

    with pytest.raises(EntryClosed):
        discard_entry(db, entry_id=started.entry.id)


def test_discarding_something_that_is_not_there_is_an_error(db):
    with pytest.raises(UnknownEntry):
        discard_entry(db, entry_id=404)


def test_an_entry_left_running_from_an_earlier_day_is_discarded(db, stomp):
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 4, 21, 0), rng=RNG)

    start_exercise(db, exercise_id=stomp.id, now=NOW, rng=RNG)

    yesterday = loaded(repo.get_day(db, date(2026, 7, 4)))
    assert repo.entries_for_day(db, yesterday.id) == []


def test_nothing_is_running_before_anything_is_started(db, stomp):
    assert current_entry(db, now=NOW) is None

    start_day(db, now=NOW)

    # a day on its own is not a clock: an entry exists once one is started
    assert current_entry(db, now=NOW) is None


def test_the_gap_between_two_entries_is_not_practice_time(db, slap, stomp, steady_rng):
    other = repo.create_exercise(db, module_id=slap.id, name="Skips")
    first = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 0), rng=RNG
    )
    done(db, first.entry.id, steady_rng, now=datetime(2026, 7, 5, 22, 10))

    # twenty minutes of coffee, then something else for ten
    second = start_exercise(
        db, exercise_id=other.id, now=datetime(2026, 7, 5, 22, 30), rng=RNG
    )
    done(db, second.entry.id, steady_rng, now=datetime(2026, 7, 5, 22, 40))

    summary = day_summary(db, day=date(2026, 7, 5), now=datetime(2026, 7, 5, 22, 45))
    assert format_duration(summary.total_seconds) == "00:20"


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
    entry = repo.create_entry(
        db,
        day_id=day.id,
        started_at=datetime(2026, 7, 5, 23, 50),
        description="le freak",
        log_group="REPERTOIRE",
    )
    repo.close_entry(db, entry.id, ended_at=datetime(2026, 7, 6, 0, 20))

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


def test_a_running_entry_counts_up_to_now(db, songs, stomp, steady_rng):
    first = start_exercise(
        db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 0), rng=RNG
    )
    done(db, first.entry.id, steady_rng, now=datetime(2026, 7, 5, 22, 10))
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 5, 22, 10), rng=RNG)

    summary = day_summary(db, day=date(2026, 7, 5), now=datetime(2026, 7, 5, 22, 25))

    assert format_duration(summary.total_seconds) == "00:25"


def test_a_stale_running_entry_adds_nothing_to_an_earlier_day(db, songs, stomp):
    start_exercise(db, exercise_id=stomp.id, now=datetime(2026, 7, 4, 21, 0), rng=RNG)

    summary = day_summary(db, day=date(2026, 7, 4), now=datetime(2026, 7, 5, 22, 25))

    assert summary.total_seconds == 0


# --- the days before today --------------------------------------------------


@pytest.fixture
def three_days(db, slap):
    """Three days of one entry each, a week apart."""
    for day, hour in ((date(2026, 7, 1), 20), (date(2026, 7, 3), 21), (NOW.date(), 22)):
        record = repo.create_day(db, day=day)
        entry = repo.create_entry(
            db,
            day_id=record.id,
            started_at=datetime(day.year, day.month, day.day, hour),
        )
        repo.close_entry(
            db,
            entry.id,
            ended_at=datetime(day.year, day.month, day.day, hour, 30),
            description="Stomp!",
            log_group="TECHNIQUE",
        )
    return None


def test_recent_days_reads_backwards_from_today(db, three_days):
    days = recent_days(db, before=NOW.date(), limit=10)

    assert [summary.day for summary in days] == [date(2026, 7, 3), date(2026, 7, 1)]
    assert format_duration(days[0].total_seconds) == "00:30"
    assert [entry.description for entry in days[0].entries] == ["Stomp!"]


def test_recent_days_stops_at_the_limit_and_carries_on_from_a_date(db, three_days):
    first = recent_days(db, before=NOW.date(), limit=1)

    assert [summary.day for summary in first] == [date(2026, 7, 3)]

    next_page = recent_days(db, before=first[-1].day, limit=1)

    assert [summary.day for summary in next_page] == [date(2026, 7, 1)]


def test_recent_days_is_empty_when_nothing_came_before(db, slap):
    assert recent_days(db, before=NOW.date(), limit=5) == []


# --- amending what the log says ---------------------------------------------


@pytest.fixture
def logged(db, slap):
    """One finished entry on the sample day, and the clock running after it."""
    day = repo.create_day(db, day=NOW.date())
    entry = repo.create_entry(db, day_id=day.id, started_at=NOW)
    repo.close_entry(
        db,
        entry.id,
        ended_at=NOW + timedelta(minutes=20),
        description="Stomp!",
        speed="80%",
        log_group="TECHNIQUE",
    )
    return repo.create_entry(db, day_id=day.id, started_at=NOW + timedelta(minutes=20))


def test_amending_an_entry_rewrites_only_what_was_given(db, logged):
    entry = repo.entries_for_day(db, logged.day_id)[0]

    amended = amend_entry(db, entry_id=entry.id, description="Stomp! (Godsmack)")

    assert amended.description == "Stomp! (Godsmack)"
    assert amended.speed == "80%"  # untouched
    assert amended.log_group == "TECHNIQUE"
    assert amended.started_at == NOW


def test_amending_the_times_moves_the_day_total(db, logged):
    entry = repo.entries_for_day(db, logged.day_id)[0]

    amend_entry(db, entry_id=entry.id, ended_at=NOW + timedelta(minutes=35))

    summary = day_summary(db, day=NOW.date())
    assert format_duration(summary.total_seconds) == "00:35"


def test_an_entry_that_crossed_midnight_keeps_its_own_dates(db, logged):
    entry = repo.entries_for_day(db, logged.day_id)[0]

    amended = amend_entry(
        db,
        entry_id=entry.id,
        started_at=datetime(2026, 7, 5, 23, 50),
        ended_at=datetime(2026, 7, 6, 0, 20),
    )

    assert entry_duration(amended) == 30 * 60


def test_the_running_entry_is_not_amended_here(db, logged):
    """The clock is the clock: `done` and `stop` write it, not the editor."""
    with pytest.raises(EntryRunning):
        amend_entry(db, entry_id=logged.id, description="whatever I am playing")


def test_amending_something_that_is_not_there_is_an_error(db):
    with pytest.raises(UnknownEntry):
        amend_entry(db, entry_id=404, description="nothing")


def test_a_line_can_be_taken_out_of_the_log(db, logged):
    entry = repo.entries_for_day(db, logged.day_id)[0]

    delete_entry(db, entry_id=entry.id)

    assert repo.get_entry(db, entry.id) is None
    assert day_summary(db, day=NOW.date()).total_seconds == 0


def test_the_running_line_is_not_deleted_by_hand(db, logged):
    """The clock again: `stop` drops it, and knows what that means."""
    with pytest.raises(EntryRunning):
        delete_entry(db, entry_id=logged.id)


def test_deleting_something_that_is_not_there_is_an_error(db):
    with pytest.raises(UnknownEntry):
        delete_entry(db, entry_id=404)
