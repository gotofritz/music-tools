"""The click group, thin over the domain.

Step 8 of docs/plans/02-domain.md. Every command is a few lines; this suite is
about what the player sees, not about the schedule, which is pinned in
`test_scheduling.py`.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from music_tools.cli import practice

RAW = Path(__file__).parent.parent / "docs" / "raw"


@pytest.fixture
def run(tmp_path):
    """Invoke the CLI against a database of its own."""
    runner = CliRunner()
    db_path = tmp_path / "practice.db"

    def invoke(*args: str):
        return runner.invoke(practice, ["--db", str(db_path), *args])

    return invoke


YESTERDAY = date.today() - timedelta(days=1)
IN_A_MONTH = date.today() + timedelta(days=30)


@pytest.fixture
def stocked(run):
    """One module and three exercises, one of them a day overdue."""
    run("module", "add", "SONGS", "--log-group", "REPERTOIRE")
    run(
        "add",
        "SONGS",
        "le freak",
        "--speed",
        "66%",
        "--target-bpm",
        "133",
        "--due",
        YESTERDAY.isoformat(),
    )
    run("add", "SONGS", "espresso", "--speed", "fast", "--due", IN_A_MONTH.isoformat())
    run("add", "SONGS", "love me jeje", "--speed", "50%", "--target-bpm", "100")
    return run


def test_module_add_and_add(run):
    assert run("module", "add", "SLAP", "--log-group", "TECHNIQUE").exit_code == 0

    result = run("add", "SLAP", "Stomp!", "--speed", "80%", "--target-bpm", "133")

    assert result.exit_code == 0
    assert "Stomp!" in result.output


def test_next_orders_by_due_date_and_says_how_overdue(stocked, run):
    result = run("next")

    assert result.exit_code == 0
    heading, *lines = [line for line in result.output.splitlines() if line.strip()]
    assert heading.startswith("SONGS (REPERTOIRE)")
    assert "1 due of 3 rows" in heading
    assert "le freak" in lines[0]
    assert "1 day overdue" in lines[0]
    assert "espresso" in lines[1]
    assert "in 30 days" in lines[1]
    assert "love me jeje" in lines[2]  # undated rows come last


def test_next_takes_a_module(stocked, run):
    run("module", "add", "SLAP", "--log-group", "TECHNIQUE")
    run("add", "SLAP", "Stomp!")

    result = run("next", "SLAP")

    assert "Stomp!" in result.output
    assert "le freak" not in result.output


def test_tempo_renders_in_both_dialects_and_falls_back_to_the_raw_text(stocked, run):
    result = run("next")

    assert "87.8 BPM (66%)" in result.output
    assert "fast" in result.output


def test_done_prints_the_new_due_date_and_the_log_line(stocked, run):
    result = run("done", "le freak")

    assert result.exit_code == 0
    # first time practised: INTERVALS[1] is a day, and the jitter cannot move it
    assert (date.today() + timedelta(days=1)).isoformat() in result.output
    assert "le freak" in result.output
    assert "REPERTOIRE" in result.output


def test_done_takes_an_algorithm(stocked, run):
    result = run("done", "le freak", "--rotate")

    assert result.exit_code == 0
    # behind the latest due date in the module, give or take a couple of days
    rotated = {(IN_A_MONTH + timedelta(days=n)).isoformat() for n in (-1, 0, 1, 2)}
    assert any(day in result.output for day in rotated)


def test_done_on_an_unknown_exercise_lists_near_matches(stocked, run):
    result = run("done", "le freek")

    assert result.exit_code != 0
    assert "le freak" in result.output


def test_a_name_in_two_modules_has_to_be_disambiguated(stocked, run):
    run("module", "add", "SLAP", "--log-group", "TECHNIQUE")
    run("add", "SLAP", "le freak")

    result = run("done", "le freak")

    assert result.exit_code != 0
    assert "SONGS" in result.output
    assert "SLAP" in result.output

    assert run("done", "SONGS/le freak").exit_code == 0


def test_speed_retunes_an_exercise(stocked, run):
    result = run("speed", "le freak", "85%")

    assert result.exit_code == 0
    assert "113 BPM (85%)" in result.output  # 85% of 133, to one decimal


def test_day_new_starts_the_clock(run):
    result = run("day", "new")

    assert result.exit_code == 0
    assert date.today().isoformat() in result.output


def test_import_and_log_reproduce_the_sample_block(run):
    result = run(
        "import",
        "--modules",
        str(RAW / "BASS SONGS.csv"),
        "--day-log",
        str(RAW / "BASS.csv"),
    )

    assert result.exit_code == 0
    assert "4 exercises" in result.output

    log = run("log", "--day", "2026-07-05")

    assert "019 Tempo Builder" in log.output
    assert "TECHNIQUE" in log.output
    assert "00:19" in log.output
    assert "00:34" in log.output
    assert "00:53" in log.output


def test_log_defaults_to_today(stocked, run):
    run("done", "le freak")

    result = run("log")

    assert date.today().isoformat() in result.output
    assert "le freak" in result.output


def test_an_empty_database_says_so_rather_than_printing_nothing(run):
    assert "nothing" in run("next").output.lower()
    assert "nothing" in run("log").output.lower()


def test_db_dump_writes_a_backup_that_can_live_in_git(stocked, run, tmp_path):
    out = tmp_path / "backups" / "practice.sql"

    result = run("db", "dump", "--to", str(out))

    assert result.exit_code == 0
    dumped = out.read_text()
    assert "CREATE TABLE module" in dumped
    assert "le freak" in dumped


def test_start_runs_the_clock_from_now(run):
    result = run("start")

    assert result.exit_code == 0
    assert "clock running from" in result.output


def test_start_opens_the_day_when_there_is_not_one(run):
    run("start")

    log = run("log")

    assert date.today().isoformat() in log.output
    assert "(running)" in log.output


# --- the module is the unit --------------------------------------------------


def test_module_list_shows_each_queue_on_its_own(stocked, run):
    run("module", "add", "SLAP", "--log-group", "TECHNIQUE")
    run("add", "SLAP", "Stomp!", "--due", YESTERDAY.isoformat())

    result = run("module", "list")

    assert result.exit_code == 0
    songs, slap = [line for line in result.output.splitlines() if line.strip()][-2:]
    assert "SONGS" in songs and "3 rows" in songs and "1 due" in songs
    assert "SLAP" in slap and "1 row" in slap


def test_next_without_a_module_is_grouped_by_module(stocked, run):
    run("module", "add", "SLAP", "--log-group", "TECHNIQUE")
    run("add", "SLAP", "Stomp!", "--due", YESTERDAY.isoformat())

    result = run("next")

    assert result.output.index("SONGS") < result.output.index("le freak")
    assert result.output.index("SLAP") < result.output.index("Stomp!")
    # the module heading carries the queue, not each row
    assert "SONGS/le freak" not in result.output


def test_module_show_lists_the_whole_queue_due_or_not(stocked, run):
    result = run("module", "show", "SONGS")

    assert result.exit_code == 0
    assert "le freak" in result.output
    assert "love me jeje" in result.output  # undated, so never in `next --due`
    assert "REPERTOIRE" in result.output


def test_module_edit_retags_and_renames(stocked, run):
    assert run("module", "edit", "SONGS", "--log-group", "TUNES").exit_code == 0
    assert run("module", "rename", "SONGS", "REPERTOIRE").exit_code == 0

    listed = run("module", "list").output
    assert "REPERTOIRE" in listed
    assert "SONGS" not in listed


def test_module_archive_takes_the_whole_queue_out_and_restore_brings_it_back(
    stocked, run
):
    assert run("module", "archive", "SONGS").exit_code == 0
    assert "le freak" not in run("next").output

    assert run("module", "restore", "SONGS").exit_code == 0
    assert "le freak" in run("next").output


def test_module_delete_refuses_while_it_has_rows(stocked, run):
    result = run("module", "delete", "SONGS")

    assert result.exit_code != 0
    assert "archive" in result.output
    assert run("module", "delete", "SONGS", "--force").exit_code == 0
    assert "SONGS" not in run("module", "list").output


def test_a_row_can_be_edited_archived_and_deleted(stocked, run):
    assert (
        run("edit", "espresso", "--name", "Espresso", "--speed", "72%").exit_code == 0
    )
    assert "Espresso" in run("module", "show", "SONGS").output

    assert run("archive", "Espresso").exit_code == 0
    assert "Espresso" not in run("module", "show", "SONGS").output
    assert run("restore", "Espresso").exit_code == 0

    assert run("delete", "Espresso").exit_code == 0
    assert "Espresso" not in run("module", "show", "SONGS").output


def test_a_row_in_the_log_is_not_deleted(stocked, run):
    run("done", "le freak")

    result = run("delete", "le freak")

    assert result.exit_code != 0
    assert "archive" in result.output
