"""The speed column is a small language; this is its grammar.

Step 2 of docs/plans/02-domain.md, specified in 00-practice-app.md, "Tempo".
Pure, total, never raises: the column has years of free text in it.
"""

import pytest

from music_tools.domain.tempo import Tempo, format_tempo, parse_tempo


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
