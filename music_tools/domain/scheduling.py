"""When an exercise comes back — the five algorithms from bass.gs.

Fibonacci-ish intervals with a +/-5% jitter, two variants that scale the whole
table, and two that ignore it and shuffle the exercise to one end of the
module's queue.

One deliberate behaviour change from the sheet, recorded in
`docs/plans/00-practice-app.md`: the sheet multiplied the interval by
`100/percent`, so a tune practised under tempo came back *later* than one
already up to speed — backwards. Here the interval is multiplied by the tempo
ratio, so it comes back sooner, and the one-day floor moves after the scaling
so nothing can be scheduled for the same day.

Pure: no database, no clock, and the rng is an argument.
"""

import math
import random
from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum

INTERVALS = (1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120)

JITTER = 0.05
SHORT_FACTOR = 0.5
LONG_FACTOR = 1.5


class Algorithm(StrEnum):
    NORMAL = "normal"
    SHORT = "short"
    LONG = "long"
    ROTATE = "rotate"
    HOLD = "hold"  # the sheet's "No Rotation"


def round_half_up(value: float) -> int:
    """Apps Script's `Math.round`, which Python's banker's rounding is not."""
    return math.floor(value + 0.5)


def interval_table(algorithm: Algorithm) -> tuple[int, ...]:
    """The table an algorithm reads: the base one, halved, or one-and-a-half."""
    if algorithm is Algorithm.SHORT:
        return tuple(math.ceil(days * SHORT_FACTOR) for days in INTERVALS)
    if algorithm is Algorithm.LONG:
        return tuple(math.ceil(days * LONG_FACTOR) for days in INTERVALS)
    return INTERVALS


def next_due(
    *,
    algorithm: Algorithm,
    count: int,
    last_practiced: date,
    ratio: float | None,
    module_dues: Sequence[date],
    rng: random.Random,
    current_due: date | None = None,
) -> date:
    """The date an exercise comes back.

    `count` arrives already incremented, as the sheet does it. `module_dues`
    is what ROTATE and HOLD scan: ROTATE is passed the exercise's own due date
    as well, HOLD is not, because the sheet's two scans disagree on exactly
    that. `current_due` is only read by HOLD, which may not push a date back.
    """
    if algorithm is Algorithm.ROTATE:
        return _rotate(last_practiced, module_dues, rng)
    if algorithm is Algorithm.HOLD:
        return _hold(last_practiced, module_dues, current_due)
    return _from_table(algorithm, count, last_practiced, ratio, rng)


def _from_table(
    algorithm: Algorithm,
    count: int,
    last_practiced: date,
    ratio: float | None,
    rng: random.Random,
) -> date:
    table = interval_table(algorithm)
    days: float = table[min(count, len(table) - 1)]
    days += round_half_up(days * JITTER * rng.uniform(-1, 1))
    if ratio is not None:
        days *= ratio
    return last_practiced + timedelta(days=round_half_up(max(1.0, days)))


def _rotate(
    last_practiced: date, module_dues: Sequence[date], rng: random.Random
) -> date:
    """Put it at the back of the queue, give or take a couple of days."""
    behind = max(module_dues) if module_dues else last_practiced
    return behind + timedelta(days=rng.randint(-1, 2))


def _hold(
    last_practiced: date, module_dues: Sequence[date], current_due: date | None
) -> date:
    """Practised it, but it is not learned; keep it at the front."""
    if not module_dues:
        return current_due if current_due is not None else last_practiced
    candidate = min(module_dues) - timedelta(days=1)
    if current_due is None or current_due > candidate:
        return candidate
    return current_due
