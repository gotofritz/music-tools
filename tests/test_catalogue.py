"""Modules and their rows: the catalogue, as opposed to the session.

A module is the fundamental abstraction — a practice area, independent of
every other one, holding rows. `domain/session.py` is about practising;
this is about keeping the catalogue itself in order.

Deleting is guarded here rather than in the repository, because refusing to
delete something with history is a decision, and the repository does not make
those.
"""

from datetime import date, datetime

import pytest

from music_tools.db import repository as repo
from music_tools.domain.catalogue import (
    InUse,
    archive_exercise,
    archive_module,
    delete_exercise,
    delete_module,
    module_overview,
    rename_module,
    restore_exercise,
    restore_module,
    update_exercise,
    update_module,
)
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import finish_entry, start_exercise

NOW = datetime(2026, 7, 5, 22, 27)
TODAY = date(2026, 7, 5)


def loaded[T](value: T | None) -> T:
    assert value is not None
    return value


def practised(db, exercise_id, rng):
    """Start an exercise and finish it: one line in the log, and a schedule."""
    started = start_exercise(db, exercise_id=exercise_id, now=NOW)
    return finish_entry(
        db,
        entry_id=started.entry.id,
        algorithm=Algorithm.NORMAL,
        now=NOW,
        rng=rng,
    )


@pytest.fixture
def slap(db):
    return repo.create_module(db, name="SLAP", log_group="TECHNIQUE")


@pytest.fixture
def songs(db):
    return repo.create_module(db, name="SONGS", log_group="REPERTOIRE")


@pytest.fixture
def stocked(db, slap, songs):
    repo.create_exercise(
        db, module_id=slap.id, name="Stomp!", next_due=date(2026, 7, 1)
    )
    repo.create_exercise(db, module_id=slap.id, name="Skips", next_due=date(2026, 7, 5))
    repo.create_exercise(
        db, module_id=songs.id, name="le freak", next_due=date(2026, 12, 3)
    )
    repo.create_exercise(db, module_id=songs.id, name="espresso")
    return slap, songs


# --- reading the catalogue --------------------------------------------------


def test_the_overview_counts_each_module_on_its_own(db, stocked):
    overview = module_overview(db, today=TODAY)

    assert [(row.module.name, row.exercises, row.due) for row in overview] == [
        ("SLAP", 2, 2),  # one overdue, one due today
        ("SONGS", 2, 0),
    ]
    assert overview[0].next_due == date(2026, 7, 1)
    assert overview[1].next_due == date(2026, 12, 3)


def test_a_module_with_no_rows_is_still_a_module(db, slap):
    overview = module_overview(db, today=TODAY)

    assert overview[0].exercises == 0
    assert overview[0].due == 0
    assert overview[0].next_due is None


def test_archived_rows_are_not_counted(db, slap):
    kept = repo.create_exercise(
        db, module_id=slap.id, name="kept", next_due=date(2026, 7, 1)
    )
    gone = repo.create_exercise(
        db, module_id=slap.id, name="gone", next_due=date(2026, 7, 1)
    )
    archive_exercise(db, gone.id, now=NOW)

    assert module_overview(db, today=TODAY)[0].exercises == 1
    assert repo.exercises_due(db, module_id=slap.id) == [
        loaded(repo.get_exercise(db, kept.id))
    ]


def test_an_archived_module_drops_out_of_the_overview_and_out_of_next(db, stocked):
    slap, _ = stocked

    archive_module(db, slap.id, now=NOW)

    assert [row.module.name for row in module_overview(db, today=TODAY)] == ["SONGS"]
    # ... and its rows stop turning up in what is due across all modules
    assert all(
        exercise.module_id != slap.id for exercise in repo.exercises_due(db, on=TODAY)
    )


def test_restoring_a_module_brings_its_rows_back(db, stocked):
    slap, _ = stocked
    archive_module(db, slap.id, now=NOW)

    restore_module(db, slap.id)

    assert [row.module.name for row in module_overview(db, today=TODAY)] == [
        "SLAP",
        "SONGS",
    ]


# --- editing ----------------------------------------------------------------


def test_renaming_a_module_moves_its_slug_too(db, slap):
    renamed = rename_module(db, slap.id, "BASS SLAP")

    assert renamed.name == "BASS SLAP"
    assert renamed.slug == "bass-slap"
    assert loaded(repo.find_module(db, "bass-slap")).id == slap.id


def test_a_module_cannot_be_renamed_over_another(db, slap, songs):
    with pytest.raises(InUse):
        rename_module(db, slap.id, "SONGS")

    assert loaded(repo.get_module(db, slap.id)).name == "SLAP"


def test_a_module_can_be_retagged_and_reordered(db, slap):
    updated = update_module(db, slap.id, log_group="REPERTOIRE", position=9)

    assert updated.log_group == "REPERTOIRE"
    assert updated.position == 9


def test_editing_a_row_leaves_the_log_alone(db, slap, steady_rng):
    exercise = repo.create_exercise(db, module_id=slap.id, name="Stomp!", speed="80%")
    result = practised(db, exercise.id, steady_rng)

    update_exercise(db, exercise.id, name="Stomp! (Godsmack)", speed="90%")

    assert loaded(repo.get_entry(db, result.closed.id)).description == "Stomp!"
    assert loaded(repo.get_exercise(db, exercise.id)).name == "Stomp! (Godsmack)"


def test_a_row_cannot_be_renamed_over_a_sibling(db, slap):
    one = repo.create_exercise(db, module_id=slap.id, name="Stomp!")
    repo.create_exercise(db, module_id=slap.id, name="Skips")

    with pytest.raises(InUse):
        update_exercise(db, one.id, name="Skips")


def test_a_row_may_take_the_name_of_an_archived_one(db, slap):
    gone = repo.create_exercise(db, module_id=slap.id, name="Stomp!")
    archive_exercise(db, gone.id, now=NOW)

    revived = repo.create_exercise(db, module_id=slap.id, name="Stomp!")

    assert revived.id != gone.id


def test_restoring_a_row_whose_name_is_taken_is_refused(db, slap):
    gone = repo.create_exercise(db, module_id=slap.id, name="Stomp!")
    archive_exercise(db, gone.id, now=NOW)
    repo.create_exercise(db, module_id=slap.id, name="Stomp!")

    with pytest.raises(InUse):
        restore_exercise(db, gone.id)


# --- deleting ---------------------------------------------------------------


def test_an_empty_module_can_be_deleted(db, slap):
    delete_module(db, slap.id)

    assert repo.get_module(db, slap.id) is None


def test_a_module_with_rows_is_not_deleted_by_accident(db, stocked):
    slap, _ = stocked

    with pytest.raises(InUse):
        delete_module(db, slap.id)

    assert repo.get_module(db, slap.id) is not None


def test_a_module_with_rows_can_be_deleted_on_purpose(db, slap):
    exercise = repo.create_exercise(db, module_id=slap.id, name="Stomp!")

    delete_module(db, slap.id, force=True)

    assert repo.get_module(db, slap.id) is None
    assert repo.get_exercise(db, exercise.id) is None


def test_a_module_whose_rows_are_in_the_log_is_never_hard_deleted(db, slap, steady_rng):
    exercise = repo.create_exercise(db, module_id=slap.id, name="Stomp!")
    practised(db, exercise.id, steady_rng)

    with pytest.raises(InUse):
        delete_module(db, slap.id, force=True)

    assert repo.get_exercise(db, exercise.id) is not None


def test_a_row_with_no_history_can_be_deleted(db, slap):
    exercise = repo.create_exercise(db, module_id=slap.id, name="Stomp!")

    delete_exercise(db, exercise.id)

    assert repo.get_exercise(db, exercise.id) is None


def test_a_row_in_the_day_log_is_archived_rather_than_deleted(db, slap, steady_rng):
    exercise = repo.create_exercise(db, module_id=slap.id, name="Stomp!")
    practised(db, exercise.id, steady_rng)

    with pytest.raises(InUse) as raised:
        delete_exercise(db, exercise.id)

    assert "archive" in str(raised.value)
    assert repo.get_exercise(db, exercise.id) is not None
