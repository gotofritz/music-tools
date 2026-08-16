"""The speed column, parsed.

Transcribe! works in percentages of the original recording; GarageBand and
metronome apps work in BPM. Both dialects get typed into the same column, so
the app parses it rather than treating it as a label:

    123      123 BPM
    123/1    the same, spelled out
    123/2    123 a minute, one every 2nd beat  -> 246
    123/0.5  123 a minute, one every half beat -> 61.5
    66%      66% of the exercise's target_bpm

`ratio = bpm / target_bpm` is what the scheduler uses: it is what makes the
two dialects comparable. Anything unparseable is kept verbatim and resolves to
unknown — the column has years of free text in it and nothing here may raise.
"""

import re
from dataclasses import dataclass

_NUMBER = r"\d+(?:\.\d+)?"
_PERCENT = re.compile(rf"^\s*({_NUMBER})\s*%\s*$")
_BPM = re.compile(rf"^\s*({_NUMBER})\s*(?:/\s*({_NUMBER})\s*)?$")


@dataclass(frozen=True)
class Tempo:
    """A speed as typed, and what it resolves to against a target."""

    written: str  # exactly as typed, byte for byte
    bpm: float | None
    target_bpm: float | None
    ratio: float | None  # bpm / target_bpm, capped at 1.0


def parse_tempo(written: str, target_bpm: float | None = None) -> Tempo:
    """Resolve a written speed against a target. Total: never raises."""
    bpm = _resolve_bpm(written, target_bpm)
    return Tempo(
        written=written,
        bpm=bpm,
        target_bpm=target_bpm,
        ratio=_resolve_ratio(bpm, target_bpm),
    )


def format_tempo(tempo: Tempo) -> str:
    """`87.8 BPM (66%)` — the notation carries intent the number loses."""
    if tempo.bpm is None:
        return tempo.written
    number = _trim(tempo.bpm)
    if tempo.written.strip() == number:
        return f"{number} BPM"
    return f"{number} BPM ({tempo.written.strip()})"


def _resolve_bpm(written: str, target_bpm: float | None) -> float | None:
    percent = _PERCENT.match(written)
    if percent:
        if target_bpm is None:
            return None  # a percentage of nothing
        return target_bpm * float(percent.group(1)) / 100

    absolute = _BPM.match(written)
    if absolute is None:
        return None
    divisor = 1.0 if absolute.group(2) is None else float(absolute.group(2))
    if divisor == 0:
        return None  # "123/0" is nonsense, not a division by zero
    return float(absolute.group(1)) * divisor


def _resolve_ratio(bpm: float | None, target_bpm: float | None) -> float | None:
    if bpm is None or not target_bpm:
        return None
    # Practised faster than target is capped rather than stretching the
    # interval: past the goal, more speed is not more retention.
    return min(bpm / target_bpm, 1.0)


def _trim(value: float) -> str:
    """One decimal place at most, and no trailing `.0`."""
    return f"{round(value, 1):g}"
