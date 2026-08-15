"""Characterisation tests for pattern resolution.

The D51 score is four two-second bars of four beats, JOHN at 2.5s, and the
beats b1 and b2 at 0.5s and 1.0s. Every span below is written against it.
"""

import click
import pytest

from music_tools.loop import read_pattern


def spans(score, pattern):
    """Resolve a pattern to (start, end, silent) triples, rounded for reading."""
    return [
        (pytest.approx(start), pytest.approx(end), silent)
        for start, end, silent in score.parse_pattern(pattern, "test")
    ]


def fails(score, pattern):
    with pytest.raises(click.ClickException) as error:
        score.parse_pattern(pattern, "test")
    return error.value.message


# --- addressing ------------------------------------------------------------


def test_bar_numbers_tile_the_snippet(d51):
    assert spans(d51, "[1][2][3][4x]") == [
        (0.0, 2.0, False),
        (2.0, 4.0, False),
        (4.0, 6.0, False),
        (6.0, 8.0, True),
    ]


def test_bar_labels_address_the_same_bars(d51):
    assert spans(d51, "[D51][D52][D53][D54x]") == spans(d51, "[1][2][3][4x]")


def test_beats_are_addressed_as_bar_dot_beat(d51):
    assert spans(d51, "[1.1][1.2][1.3][1.4x][2]") == [
        (0.0, 0.5, False),
        (0.5, 1.0, False),
        (1.0, 1.5, False),
        (1.5, 2.0, True),
        (2.0, 8.0, False),
    ]


def test_a_labelled_beat_is_addressed_by_its_label(d51):
    assert spans(d51, "[b1][b2]") == [(0.5, 1.0, False), (1.0, 8.0, False)]


def test_a_text_block_alone_runs_to_the_end(d51):
    assert spans(d51, "[JOHN]") == [(2.5, 8.0, False)]


# --- ranges ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("[1-3]", (0.0, 4.0, False)),
        ("[1.4-3]", (1.5, 4.0, False)),
        ("[JOHN-3.2]", (2.5, 4.5, False)),
        ("[JOHN-D53]", (2.5, 4.0, False)),
        ("[1.1-JOHN]", (0.0, 2.5, False)),
        ("[1-3x]", (0.0, 4.0, True)),
        ("[4-END]", (6.0, 8.0, False)),
    ],
)
def test_a_range_ends_where_its_end_begins(d51, pattern, expected):
    assert spans(d51, pattern) == [
        (pytest.approx(expected[0]), pytest.approx(expected[1]), expected[2])
    ]


def test_explicit_ends_allow_repeats(d51):
    assert spans(d51, "[1-2][1-2][1-2]") == [(0.0, 2.0, False)] * 3


def test_explicit_ends_allow_an_out_of_order_run(d51):
    assert spans(d51, "[3-4][1-2]") == [(4.0, 6.0, False), (0.0, 2.0, False)]


# --- the neighbour rule ----------------------------------------------------


def test_one_bare_span_is_the_whole_snippet(d51):
    assert spans(d51, "[1]") == [(0.0, 8.0, False)]


def test_a_bare_span_is_closed_by_the_next_one(d51):
    assert spans(d51, "[1][3]") == [(0.0, 4.0, False), (4.0, 8.0, False)]


def test_a_bare_span_covers_its_range_only_because_of_what_follows(d51):
    first, _ = d51.parse_pattern("[1][2]", "test")

    assert first == d51.parse_pattern("[1-2]", "test")[0]
    # the pattern as a whole still runs on to the end
    assert spans(d51, "[1][2]")[-1] == (pytest.approx(2.0), pytest.approx(8.0), False)


# --- the end of a two-way marked passage -----------------------------------


def test_the_closing_bar_marker_names_the_end(build_score):
    twoway = build_score("twoway")

    assert spans(twoway, "[92-93]") == [(4.0, 6.0, False)]
    assert spans(twoway, "[92]") == spans(twoway, "[92-93]")
    assert spans(twoway, "[92-END]") == spans(twoway, "[92-93]")


def test_naming_the_end_marker_works_anywhere_in_a_pattern(build_score):
    twoway = build_score("twoway")

    assert spans(twoway, "[92-93][90-91]") == [
        (4.0, 6.0, False),
        (0.0, 2.0, False),
    ]


# --- a label always wins over a trailing x ---------------------------------


def test_a_bar_really_called_d51x_is_played_not_silenced(build_score):
    score = build_score("d51x")

    assert spans(score, "[D51x]") == [(2.0, 8.0, False)]
    assert spans(score, "[D51][D51x]") == [
        (0.0, 2.0, False),
        (2.0, 8.0, False),
    ]


def test_a_trailing_x_still_silences_a_bar_with_no_such_label(build_score):
    assert spans(build_score("d51"), "[D51x]") == [(0.0, 8.0, True)]


# --- errors ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "offender"),
    [
        ("[nope]", "nope"),
        ("[JOHN-nope]", "nope"),
        ("[9]", "9"),
        ("[1.9]", "1.9"),
    ],
)
def test_an_unresolvable_address_names_itself(d51, pattern, offender):
    message = fails(d51, pattern)

    assert "no such bar, beat or text block" in message
    assert message.rstrip().endswith(offender)


def test_an_empty_address_is_rejected(d51):
    assert "empty address" in fails(d51, "[]")


def test_a_backwards_range_says_so(d51):
    message = fails(d51, "[JOHN-b2]")

    assert "[JOHN-b2]" in message
    assert "is not after its start" in message


def test_a_span_with_nowhere_to_run_names_the_span_that_blocks_it(d51):
    message = fails(d51, "[1][1]")

    assert "[1]" in message
    assert "has nowhere to run" in message


def test_an_out_of_order_run_without_ends_is_rejected(d51):
    assert "has nowhere to run" in fails(d51, "[3][1]")


def test_a_span_starting_at_the_end_has_nothing_left_to_play(build_score):
    message = fails(build_score("twoway"), "[93]")

    assert "already the end of the snippet" in message


def test_curly_brackets_point_at_square_ones(d51):
    message = fails(d51, "{JOHN}")

    assert "curly brackets" in message
    assert "[JOHN-3]" in message


def test_text_outside_a_span_is_rejected(d51):
    message = fails(d51, "[1]junk[2]")

    assert "'junk' is outside any []" in message


def test_a_pattern_with_no_spans_at_all_is_rejected(d51):
    assert "may not be empty" in fails(d51, "   ")


# --- read_pattern ----------------------------------------------------------


def test_read_pattern_picks_the_one_mode_a_section_uses():
    assert read_pattern({"bars": "11x1"}, "test") == ("bars", "11x1", "11x1")


def test_read_pattern_strips_the_spaces_that_only_group():
    mode, pattern, written = read_pattern({"beats": "1111 11xx"}, "test")

    assert (mode, pattern) == ("beats", "111111xx")
    assert written == "1111 11xx"


def test_read_pattern_rejects_a_section_with_no_pattern():
    with pytest.raises(click.ClickException) as error:
        read_pattern({"repeat": 2}, "test")

    assert "needs one of sequence, bars, beats, markers" in error.value.message


def test_read_pattern_rejects_two_patterns_at_once():
    with pytest.raises(click.ClickException) as error:
        read_pattern({"bars": "1111", "beats": "1111"}, "test")

    assert "bars and beats cannot be combined" in error.value.message


def test_read_pattern_rejects_an_empty_pattern():
    with pytest.raises(click.ClickException) as error:
        read_pattern({"bars": "   "}, "test")

    assert "bars may not be empty" in error.value.message


def test_read_pattern_names_invalid_characters_in_a_grid():
    with pytest.raises(click.ClickException) as error:
        read_pattern({"bars": "11o2"}, "test")

    assert "invalid characters: 2, o" in error.value.message


def test_read_pattern_leaves_a_markers_pattern_alone():
    mode, pattern, _ = read_pattern({"markers": "[1-2] [JOHN]"}, "test")

    assert (mode, pattern) == ("markers", "[1-2][JOHN]")
