"""The five algorithms, ported from `addNextDue` and friends in bass.gs.

Step 3 of docs/plans/02-domain.md. Pure: no database, no clock, and the rng
arrives as an argument.
"""

from datetime import date, timedelta

import pytest

from music_tools.domain.scheduling import (
    INTERVALS,
    Algorithm,
    interval_table,
    next_due,
    round_half_up,
)
from music_tools.domain.tempo import parse_tempo

LAST = date(2026, 7, 5)


def due(algorithm=Algorithm.NORMAL, *, count=0, ratio=None, dues=(), rng, current=None):
    return next_due(
        algorithm=algorithm,
        count=count,
        last_practiced=LAST,
        ratio=ratio,
        module_dues=list(dues),
        rng=rng,
        current_due=current,
    )


def test_the_table_is_the_sheets_table():
    assert INTERVALS == (1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120)


@pytest.mark.parametrize("count,days", [(0, 1), (1, 1), (4, 5), (8, 34)])
def test_normal_reads_the_table_at_the_post_increment_count(count, days, steady_rng):
    # The sheet increments before it schedules, so a row at x=8 is scheduled
    # with intervals[9] once the count arrives here as 9.
    assert due(count=count, rng=steady_rng) == LAST + timedelta(days=days)


def test_the_table_plateaus(steady_rng):
    assert due(count=99, rng=steady_rng) == LAST + timedelta(days=120)


def test_jitter_stays_within_five_percent_and_never_schedules_today(rng):
    seen = set()
    for _ in range(1000):
        days = (due(count=8, rng=rng) - LAST).days
        seen.add(days)
    assert min(seen) >= 34 - 2
    assert max(seen) <= 34 + 2
    assert len(seen) > 1  # the jitter is actually moving


def test_the_shortest_interval_cannot_jitter_down_to_nothing(rng):
    for _ in range(1000):
        assert due(count=0, rng=rng) == LAST + timedelta(days=1)


@pytest.mark.parametrize("value,rounded", [(2.5, 3), (-0.5, 0), (1.4, 1), (1.5, 2)])
def test_rounding_is_half_up_like_apps_script_not_bankers(value, rounded):
    assert round_half_up(value) == rounded


def test_short_and_long_scale_the_whole_table_with_ceil():
    assert interval_table(Algorithm.SHORT)[-1] == 60
    assert interval_table(Algorithm.LONG)[-1] == 180
    assert min(interval_table(Algorithm.SHORT)) >= 1


@pytest.mark.parametrize(
    "algorithm,count,days",
    [
        (Algorithm.SHORT, 0, 1),
        (Algorithm.SHORT, 99, 60),
        (Algorithm.LONG, 0, 2),
        (Algorithm.LONG, 99, 180),
    ],
)
def test_short_and_long(algorithm, count, days, steady_rng):
    assert due(algorithm, count=count, rng=steady_rng) == LAST + timedelta(days=days)


@pytest.mark.parametrize(
    "ratio,days",
    [(None, 34), (1.0, 34), (0.8, 27), (0.5, 17)],
)
def test_tempo_scales_the_interval_towards_sooner(ratio, days, steady_rng):
    # The sheet multiplied by 100/percent, so a tune under tempo came back
    # later. The port multiplies by the ratio, so it comes back sooner.
    assert due(count=8, ratio=ratio, rng=steady_rng) == LAST + timedelta(days=days)


def test_a_ratio_above_one_cannot_arrive_because_tempo_caps_it():
    assert parse_tempo("120", target_bpm=100.0).ratio == 1.0


def test_the_floor_is_applied_after_the_scaling_not_before(steady_rng):
    # bass.gs floors first, which was safe while scaling could only stretch.
    # A ratio of 0.2 over a 2-day interval would round to zero days there.
    assert due(count=2, ratio=0.2, rng=steady_rng) == LAST + timedelta(days=1)


def test_the_order_of_operations_is_pinned_to_an_exact_date(jittery_rng):
    # jitter (+2 on a 34-day interval), then the ratio, then the floor, then
    # the rounding: 34 + 2 = 36, x 0.8 = 28.8, rounds to 29.
    assert due(count=8, ratio=0.8, rng=jittery_rng) == date(2026, 8, 3)


def test_rotate_goes_behind_the_latest_due_date_in_the_module(steady_rng):
    dues = [date(2026, 8, 1), date(2026, 12, 3), date(2026, 9, 9)]

    assert due(Algorithm.ROTATE, dues=dues, rng=steady_rng) == date(2026, 12, 3)


def test_rotate_includes_the_exercises_own_due_date(steady_rng):
    # The sheet's max scan does not skip the current row, so a row already at
    # the back of the queue rotates from its own date, not the runner-up's.
    own = date(2027, 1, 5)

    assert due(Algorithm.ROTATE, dues=[date(2026, 8, 1), own], rng=steady_rng) == own


def test_rotate_offsets_by_minus_one_to_plus_two_days(rng):
    base = date(2026, 12, 3)
    offsets = {
        (due(Algorithm.ROTATE, dues=[base], rng=rng) - base).days for _ in range(200)
    }

    assert offsets == {-1, 0, 1, 2}


def test_rotate_with_nothing_to_rotate_behind_falls_back_to_today(steady_rng):
    # The sheet rotates from epoch 1970 here, which is a bug, not a behaviour.
    assert due(Algorithm.ROTATE, dues=[], rng=steady_rng) == LAST


def test_hold_brings_the_exercise_to_the_front_of_the_queue(steady_rng):
    dues = [date(2026, 8, 1), date(2026, 9, 9)]

    held = due(Algorithm.HOLD, dues=dues, rng=steady_rng, current=date(2026, 12, 3))

    assert held == date(2026, 7, 31)


def test_hold_never_pushes_a_date_back(steady_rng):
    already_sooner = date(2026, 7, 6)

    held = due(
        Algorithm.HOLD,
        dues=[date(2026, 8, 1)],
        rng=steady_rng,
        current=already_sooner,
    )

    assert held == already_sooner


def test_hold_excludes_the_exercises_own_due_date(steady_rng):
    # The sheet's min scan skips the current row; passing it in would hold the
    # exercise a day in front of itself, every time.
    own = date(2026, 8, 1)

    held = due(Algorithm.HOLD, dues=[date(2026, 9, 9)], rng=steady_rng, current=own)

    assert held == own


def test_hold_with_no_other_dated_rows_changes_nothing(steady_rng):
    current = date(2026, 12, 3)

    assert due(Algorithm.HOLD, dues=[], rng=steady_rng, current=current) == current


def test_hold_on_an_exercise_with_no_due_date_at_all(steady_rng):
    # The sheet would write 9999-12-30. Due today is the honest answer.
    assert due(Algorithm.HOLD, dues=[], rng=steady_rng, current=None) == LAST
