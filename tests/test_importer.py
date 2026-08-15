"""Carrying the spreadsheet's history over, against the real exports.

Step 7 of docs/plans/02-domain.md. The files in `docs/raw/` are tab-separated
despite the `.csv` extension, and carry a long tail of empty columns on every
row.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from music_tools.db import repository as repo
from music_tools.importer.sheets import import_sheets, split_trailing_note

RAW = Path(__file__).parent.parent / "docs" / "raw"
MODULE_FILE = RAW / "BASS SONGS.csv"
DAY_LOG = RAW / "BASS.csv"


def loaded[T](value: T | None) -> T:
    assert value is not None
    return value


@pytest.fixture
def imported(db):
    return import_sheets(db, modules=[MODULE_FILE], day_log=DAY_LOG)


def entry_at(db, when: datetime):
    day = loaded(repo.get_day(db, when.date()))
    return next(
        entry for entry in repo.entries_for_day(db, day.id) if entry.started_at == when
    )


def test_the_module_comes_from_the_file_name_and_the_log_group_from_a1(db, imported):
    module = loaded(repo.find_module(db, "SONGS"))

    assert module.name == "SONGS"
    assert module.log_group == "REPERTOIRE"


def test_the_exercises_come_over_with_their_schedule(db, imported):
    module = loaded(repo.find_module(db, "SONGS"))

    exercises = repo.exercises_due(db, module_id=module.id)

    assert [exercise.name for exercise in exercises] == [
        "Waitin' On Ya",
        "Didn't Cha Know",
        "le freak",
        "espresso",
    ]
    freak = exercises[2]
    assert freak.speed == "80%"
    assert freak.style == "DANCE"
    assert freak.practiced_count == 12
    assert freak.last_practiced == date(2026, 7, 17)
    assert freak.next_due == date(2026, 12, 3)
    # the sheet has no target column, and "80%" says nothing about what 100% is
    assert freak.target_bpm is None


def test_a_speed_in_the_bpm_dialect_is_kept_verbatim(db, imported):
    entry = entry_at(db, datetime(2026, 7, 6, 21, 24))

    assert entry.speed == "66/1"


def test_the_day_column_forward_fills_into_blocks(db, imported):
    assert [day.day for day in repo.list_days(db)] == [
        date(2026, 7, 5),
        date(2026, 7, 6),
        date(2026, 7, 9),
    ]


def test_the_entries_of_a_block_tile_the_session(db, imported):
    day = loaded(repo.get_day(db, date(2026, 7, 5)))

    entries = repo.entries_for_day(db, day.id)

    assert [entry.started_at.strftime("%H:%M") for entry in entries] == [
        "22:27",
        "22:34",
        "22:46",
        "23:03",
    ]
    assert [loaded(entry.ended_at).strftime("%H:%M") for entry in entries] == [
        "22:34",
        "22:46",
        "23:03",
        "23:20",
    ]


def test_the_module_column_forward_fills_within_the_block(db, imported):
    day = loaded(repo.get_day(db, date(2026, 7, 5)))

    groups = [entry.log_group for entry in repo.entries_for_day(db, day.id)]

    assert groups == ["TECHNIQUE", "TECHNIQUE", "REPERTOIRE", "REPERTOIRE"]


def test_a_trailing_parenthetical_splits_back_into_a_note(db, imported):
    entry = entry_at(db, datetime(2026, 7, 5, 22, 27))

    assert entry.description == "019 Tempo Builder"
    assert loaded(entry.notes).startswith("random tempo all the time")


@pytest.mark.parametrize(
    "written,description,note",
    [
        ("019 Tempo Builder (random tempo)", "019 Tempo Builder", "random tempo"),
        ("le freak", "le freak", None),
        ("a (b (c))", "a (b (c))", None),  # nested brackets stay put
        ("a (b", "a (b", None),  # unbalanced too
        ("(all of it)", "", "all of it"),
    ],
)
def test_split_trailing_note(written, description, note):
    assert split_trailing_note(written) == (description, note)


def test_an_entry_matching_an_exercise_is_linked_to_it(db, imported):
    freak = repo.find_exercises(db, "le freak")[0]

    entry = entry_at(db, datetime(2026, 7, 5, 22, 46))

    assert entry.exercise_id == freak.id


def test_an_entry_matching_nothing_is_kept_as_an_ad_hoc_entry(db, imported):
    entry = entry_at(db, datetime(2026, 7, 6, 21, 24))

    assert entry.exercise_id is None
    assert entry.description == "041 Skips"


def test_the_log_group_comes_from_the_log_not_from_the_exercise(db, imported):
    # 2026-07-09: "le freak" is a SONGS exercise, but the blank MODULE
    # forward-fills TECHNIQUE over its row, and the sheet's own subtotal
    # (01:07, the whole day) agrees. Snapshots come from the log.
    freak = repo.find_exercises(db, "le freak")[0]

    entry = entry_at(db, datetime(2026, 7, 9, 22, 25))

    assert entry.exercise_id == freak.id
    assert entry.log_group == "TECHNIQUE"


def test_a_dangling_from_is_expected_structure_not_a_problem(db, imported):
    day = loaded(repo.get_day(db, date(2026, 7, 9)))

    assert len(repo.entries_for_day(db, day.id)) == 2
    assert imported.problems == []


def test_the_formula_columns_are_ignored_because_they_are_recomputed(db, imported):
    from music_tools.domain.session import day_summary, format_duration

    summary = day_summary(db, day=date(2026, 7, 5))

    assert format_duration(summary.total_seconds) == "00:53"
    assert [format_duration(group.seconds) for group in summary.groups] == [
        "00:19",
        "00:34",
    ]


def test_a_second_run_changes_nothing(db, imported):
    def counts():
        return {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("module", "exercise", "practice_day", "practice_entry")
        }

    before = counts()
    again = import_sheets(db, modules=[MODULE_FILE], day_log=DAY_LOG)

    assert counts() == before
    assert again.exercises_created == 0
    assert again.entries_created == 0
    assert again.problems == []


def test_an_entry_whose_end_is_before_its_start_crossed_midnight(db, tmp_path):
    log = tmp_path / "BASS.csv"
    log.write_text(
        "DAY\tFROM\tTO\tTIME\tSPEED\tNOTES\tMODULE\n"
        "2026-07-05\t23:50\t00:20\t00:30\t80%\tle freak\tREPERTOIRE\n"
    )

    import_sheets(db, day_log=log)

    entry = entry_at(db, datetime(2026, 7, 5, 23, 50))
    assert entry.ended_at == datetime(2026, 7, 6, 0, 20)


def test_a_mangled_row_is_reported_and_the_rest_still_import(db, tmp_path):
    log = tmp_path / "BASS.csv"
    log.write_text(
        "DAY\tFROM\tTO\tTIME\tSPEED\tNOTES\tMODULE\n"
        "2026-07-05\thalf past\t22:34\t\t54\t019 Tempo Builder\tTECHNIQUE\n"
        "\t22:34\t22:46\t\t66\tPage 3\t\n"
    )

    report = import_sheets(db, day_log=log)

    assert len(report.problems) == 1
    assert "half past" in report.problems[0]
    assert report.entries_created == 1


def test_the_importer_is_driven_by_paths_not_by_a_working_directory(db):
    report = import_sheets(db, modules=[MODULE_FILE])

    assert report.modules_created == 1
    assert report.exercises_created == 4
    assert report.entries_created == 0
