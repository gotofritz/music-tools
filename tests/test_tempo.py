"""The speed column is a small language; this is its grammar.

Step 2 of docs/plans/02-domain.md, specified in 00-practice-app.md, "Tempo".
Pure, total, never raises: the column has years of free text in it.
"""

import pytest

from music_tools.domain.tempo import Tempo, format_tempo, parse_tempo, write_ratio


@pytest.mark.parametrize(
    "written,target,bpm,ratio",
    [
        ("123", None, 123.0, None),
        ("123/1", None, 123.0, None),
        ("123/2", None, 246.0, None),
        ("123/0.5", None, 61.5, None),
        ("66%", 133.0, 87.78, 0.66),
        ("66/1", 66.0, 66.0, 1.0),
        ("88", 133.0, 88.0, 0.6617),
        ("120", 100.0, 120.0, 1.0),  # capped: past the goal is not more speed
        ("66%", None, None, None),  # a percentage of nothing
        ("fast", 133.0, None, None),
        ("", 133.0, None, None),
    ],
)
def test_the_grammar(written, target, bpm, ratio):
    tempo = parse_tempo(written, target_bpm=target)

    assert tempo.written == written
    assert tempo.target_bpm == target
    if bpm is None:
        assert tempo.bpm is None
    else:
        assert tempo.bpm == pytest.approx(bpm, abs=0.01)
    if ratio is None:
        assert tempo.ratio is None
    else:
        assert tempo.ratio == pytest.approx(ratio, abs=0.0001)


@pytest.mark.parametrize("written", ["  80 % ", "\t66/1\n", "medium-ish", ""])
def test_written_survives_byte_for_byte(written):
    assert parse_tempo(written, target_bpm=100.0).written == written


def test_spaces_do_not_stop_a_percentage_parsing():
    tempo = parse_tempo("  80 % ", target_bpm=100.0)

    assert tempo.bpm == pytest.approx(80.0)
    assert tempo.ratio == pytest.approx(0.8)


def test_zero_percent_is_a_ratio_of_zero_not_an_unknown():
    tempo = parse_tempo("0%", target_bpm=133.0)

    assert tempo.bpm == 0.0
    assert tempo.ratio == 0.0


@pytest.mark.parametrize("written", ["123/0", "-4", "123/-2", "12/3/4", "%"])
def test_nonsense_parses_to_unknown_rather_than_raising(written):
    tempo = parse_tempo(written, target_bpm=133.0)

    assert tempo.bpm is None
    assert tempo.ratio is None


def test_a_target_of_zero_leaves_the_ratio_unknown():
    tempo = parse_tempo("100", target_bpm=0.0)

    assert tempo.bpm == 100.0
    assert tempo.ratio is None


def test_the_two_dialects_agree_against_the_same_target():
    percent = parse_tempo("66%", target_bpm=133.0)
    absolute = parse_tempo("87.78", target_bpm=133.0)

    assert percent.ratio == pytest.approx(absolute.ratio, abs=0.0001)


def test_tempo_is_frozen():
    with pytest.raises(Exception):
        parse_tempo("100").bpm = 200.0  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    "written,target,shown",
    [
        ("66%", 133.0, "87.8 BPM (66%)"),
        ("88", 133.0, "88 BPM"),
        ("66/1", None, "66 BPM (66/1)"),
        ("fast", 133.0, "fast"),
        ("", None, ""),
    ],
)
def test_display_shows_the_pair_because_the_notation_carries_intent(
    written, target, shown
):
    assert format_tempo(parse_tempo(written, target_bpm=target)) == shown


def test_a_tempo_can_be_built_without_parsing():
    assert Tempo(written="66%", bpm=88.0, target_bpm=133.0, ratio=0.66).ratio == 0.66


# --- writing a ratio back (the speed slider, Phase 5a step 6) ----------------


@pytest.mark.parametrize(
    ("written", "target", "ratio", "expected"),
    [
        ("66%", 133, 0.8, "80%"),  # a percentage stays a percentage
        ("66%", 133, 0.755, "76%"),
        ("88", 133, 0.8, "106.4"),  # a bare BPM stays a BPM, never "80%"
        ("123", 120, 0.5, "60"),
        ("88/1", 133, 0.8, "106.4/1"),
        ("60/2", 120, 0.5, "30/2"),  # the divisor is the exercise's own
        ("60/0.5", 120, 0.5, "120/0.5"),
        ("", 133, 0.9, "90%"),  # nothing written: Transcribe!'s dialect
        ("slow-ish", 133, 0.9, "90%"),  # free text is replaced, not parsed
    ],
)
def test_a_ratio_is_written_in_the_dialect_the_exercise_already_uses(
    written, target, ratio, expected
):
    assert write_ratio(written, ratio=ratio, target_bpm=target) == expected


def test_what_is_written_reads_back_as_the_ratio_it_was_written_from():
    for written in ("66%", "88", "60/2", ""):
        out = write_ratio(written, ratio=0.75, target_bpm=120)

        assert parse_tempo(out, target_bpm=120).ratio == pytest.approx(0.75, abs=0.01)


def test_there_is_no_ratio_to_write_without_a_target():
    with pytest.raises(ValueError, match="target"):
        write_ratio("66%", ratio=0.8, target_bpm=None)


@pytest.mark.parametrize("ratio", [0, -0.5, 1.01])
def test_a_ratio_outside_zero_to_one_is_refused(ratio):
    with pytest.raises(ValueError, match="ratio"):
        write_ratio("66%", ratio=ratio, target_bpm=133)
