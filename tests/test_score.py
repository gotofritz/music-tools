"""Characterisation tests for marker parsing and the score built from it.

The behaviour already exists; these pin it so that a later refactor which
changes it says so. See docs/plans/01-foundations.md, "Honest caveat".
"""

import click
import pytest

from music_tools.loop import Bar, Beat, Score, modal_beats, parse_markers, report


def bar_named(score, name):
    return next(bar for bar in score.bars if bar.name == name)


def test_d51_reads_as_four_bars_of_four_beats(build_score):
    score = build_score("d51")

    assert [bar.name for bar in score.bars] == ["D51", "D52", "D53", "D54"]
    assert [len(bar.beats) for bar in score.bars] == [4, 4, 4, 4]


def test_a_bars_own_marker_is_also_its_first_beat(build_score):
    score = build_score("d51")

    first = score.bars[0]
    assert first.beats[0].start == first.start


def test_beats_labelled_in_their_own_right_keep_their_labels(build_score):
    score = build_score("d51")

    assert [beat.label for beat in score.bars[0].beats] == ["D51", "b1", "b2", ""]
    assert score.address("b1") == pytest.approx(0.5)
    assert score.address("b2") == pytest.approx(1.0)


def test_a_text_block_is_named_by_its_text(build_score):
    score = build_score("d51")

    assert [block.name for block in score.textblocks] == ["JOHN"]
    assert score.address("JOHN") == pytest.approx(2.5)


def test_the_first_marker_is_shifted_to_the_top_of_the_snippet(build_score):
    score = build_score("d51")

    assert score.bars[0].start == 0.0
    assert score.bars[0].beats[0].raw == pytest.approx(12.0)


def test_the_last_bar_ends_at_the_snippet_duration(build_score):
    score = build_score("d51")

    assert score.bars[-1].end == pytest.approx(8.0)
    assert score.duration == pytest.approx(8.0)


def test_bars_tile_the_snippet_with_no_gaps_or_overlaps(build_score):
    score = build_score("d51")

    slices = score.bar_slices()
    assert slices[0][0] == 0.0
    assert slices[-1][1] == pytest.approx(score.duration)
    for (_, end), (start, _) in zip(slices, slices[1:]):
        assert end == pytest.approx(start)


def test_beats_tile_the_snippet_too(build_score):
    score = build_score("d51")

    slices = score.beat_slices()
    assert len(slices) == 16
    assert slices[0][0] == 0.0
    assert slices[-1][1] == pytest.approx(score.duration)
    for (_, end), (start, _) in zip(slices, slices[1:]):
        assert end == pytest.approx(start)


def test_a_bar_marker_with_no_beats_closes_the_score(build_score):
    """twoway.txt was marked up by dropping a marker on every barline.

    The final one is where the passage ends, not a bar to play.
    """
    score = build_score("twoway")

    assert [bar.name for bar in score.bars] == ["90", "91", "92"]
    assert score.end_marker == "93"
    # the score stops at 93 even though the audio runs on for another second
    assert score.duration == pytest.approx(6.0)
    assert score.address("93") == pytest.approx(6.0)
    assert score.address("END") == pytest.approx(6.0)


def test_a_marker_labelled_end_truncates_the_score(build_score):
    """Undocumented, and the reason nothing can shadow the reserved END."""
    score = build_score("endmarker")

    assert [bar.name for bar in score.bars] == ["E1", "E2"]
    assert score.duration == pytest.approx(4.0)
    assert score.address("E3") is None


def test_jackson5_has_five_beats_in_a3(build_score):
    score = build_score("jackson5")

    assert [bar.name for bar in score.bars] == ["A1", "A2", "A3", "A4"]
    assert [len(bar.beats) for bar in score.bars] == [4, 4, 5, 4]


def test_auto_markers_count_as_beats(write_markers):
    """Transcribe! writes "auto" for beats it worked out rather than tapped."""
    path = write_markers("""
0:00:01.000000 Marker (section): "A1"
0:00:01.500000 Marker (auto): ""
0:00:02.000000 Marker (beat): ""
0:00:02.500000 Marker (auto): ""
0:00:03.000000 Marker (section): "A2"
0:00:03.500000 Marker (beat): ""
0:00:04.000000 Marker (auto): ""
0:00:04.500000 Marker (beat): ""
""")
    score = Score.build(parse_markers(path), 4.0)

    assert [len(bar.beats) for bar in score.bars] == [4, 4]
    assert score.ignored == {}


def test_a_kind_that_is_neither_bar_nor_beat_is_counted_and_reported(
    write_markers, capsys
):
    path = write_markers("""
0:00:01.000000 Marker (section): "A1"
0:00:01.500000 Marker (beat): ""
0:00:02.000000 Marker (cue): ""
0:00:02.500000 Marker (beat): ""
0:00:03.000000 Marker (section): "A2"
0:00:03.500000 Marker (beat): ""
0:00:04.000000 Marker (beat): ""
0:00:04.500000 Marker (beat): ""
""")
    score = Score.build(parse_markers(path), 4.0)
    assert score.ignored == {"cue": 1}

    report(score)
    printed = capsys.readouterr().out
    assert "1 × cue" in printed
    assert "not a bar or a beat" in printed


def test_a_short_first_bar_is_a_pickup_numbered_from_zero(build_score):
    score = build_score("pickup")

    assert score.pickup is True
    assert score.numbered_from == 0
    assert score.address("0") == pytest.approx(0.0)
    assert score.address("1") == pytest.approx(1.0)
    assert score.address("1") == bar_named(score, "A1").start


def test_a_loop_with_square_edges_keeps_one_based_numbering(build_score):
    score = build_score("d51")

    assert score.pickup is False
    assert score.numbered_from == 1
    assert score.address("0") is None
    assert score.address("1") == bar_named(score, "D51").start


def test_the_odd_beat_warning_covers_interior_bars_only(build_score, capsys):
    """A snippet cut from a recording is expected to be partial at its edges."""
    score = build_score("jackson5")
    report(score)
    interior = capsys.readouterr().out
    assert "A3 has 5 beats, expected 4" in interior

    score = build_score("pickup")
    report(score)
    edges = capsys.readouterr().out
    assert "expected" not in edges
    assert "PU is a 2-beat pickup" in edges


def test_a_short_last_bar_does_not_warn(write_markers, capsys):
    path = write_markers("""
0:00:01.000000 Marker (section): "A1"
0:00:01.500000 Marker (beat): ""
0:00:02.000000 Marker (beat): ""
0:00:02.500000 Marker (beat): ""
0:00:03.000000 Marker (section): "A2"
0:00:03.500000 Marker (beat): ""
0:00:04.000000 Marker (beat): ""
0:00:04.500000 Marker (beat): ""
0:00:05.000000 Marker (section): "A3"
0:00:05.500000 Marker (beat): ""
""")
    report(Score.build(parse_markers(path), 5.0))

    assert "expected" not in capsys.readouterr().out


def test_modal_beats_breaks_a_tie_towards_the_longer_count():
    """2+4+4+2 is two full bars between two partial ones, not the other way."""
    bars = [
        Bar(name=str(n), start=0.0, beats=[Beat("", 0.0)] * count)
        for n, count in enumerate([2, 4, 4, 2])
    ]

    assert modal_beats(bars) == 4


def test_modal_beats_on_a_one_plus_four_file_blames_the_short_bar():
    bars = [
        Bar(name=str(n), start=0.0, beats=[Beat("", 0.0)] * count)
        for n, count in enumerate([1, 4])
    ]

    assert modal_beats(bars) == 4


def test_markers_running_past_the_snippet_raise(build_score):
    with pytest.raises(click.ClickException) as error:
        build_score("d51", duration=3.0)

    assert "belong to this snippet" in error.value.message


def test_an_empty_marker_file_raises(write_markers):
    with pytest.raises(click.ClickException) as error:
        Score.build(parse_markers(write_markers("\n")), 4.0)

    assert "No markers found" in error.value.message


def test_a_file_with_no_bar_markers_raises(write_markers):
    path = write_markers("""
0:00:01.000000 Marker (beat): ""
0:00:01.500000 Marker (beat): ""
""")

    with pytest.raises(click.ClickException) as error:
        Score.build(parse_markers(path), 4.0)

    assert "No section or measure markers" in error.value.message


def test_beats_before_the_first_bar_marker_open_a_pickup(write_markers):
    """A snippet cut mid-bar has its upbeat marked as beats, with no barline."""
    path = write_markers("""
0:00:10.500000 Marker (beat): ""
0:00:11.000000 Marker (measure): "A1"
0:00:11.500000 Marker (beat): ""
0:00:12.000000 Marker (beat): ""
0:00:12.500000 Marker (beat): ""
0:00:13.000000 Marker (measure): "A2"
0:00:13.500000 Marker (beat): ""
0:00:14.000000 Marker (beat): ""
0:00:14.500000 Marker (beat): ""
""")
    score = Score.build(parse_markers(path), 5.0)

    assert [len(bar.beats) for bar in score.bars] == [1, 4, 4]
    assert score.pickup is True
    assert score.numbered_from == 0
    assert score.address("0") == pytest.approx(0.0)
    assert score.address("1") == bar_named(score, "A1").start
    assert score.bars[0].end == pytest.approx(0.5)


def test_an_unnamed_bar_after_a_loose_pickup_is_numbered_from_one(write_markers):
    """The implicit pickup is [0], so the bar after it is still [1]."""
    path = write_markers("""
0:00:10.500000 Marker (beat): ""
0:00:11.000000 Marker (measure): ""
0:00:11.500000 Marker (beat): ""
0:00:12.000000 Marker (beat): ""
0:00:12.500000 Marker (beat): ""
0:00:13.000000 Marker (measure): ""
0:00:13.500000 Marker (beat): ""
0:00:14.000000 Marker (beat): ""
0:00:14.500000 Marker (beat): ""
""")
    score = Score.build(parse_markers(path), 5.0)

    assert [bar.name for bar in score.bars] == ["0", "1", "2"]


def test_a_marker_file_of_beats_alone_is_still_an_error(write_markers):
    path = write_markers("""
0:00:10.500000 Marker (beat): ""
0:00:11.000000 Marker (beat): ""
""")
    with pytest.raises(click.ClickException, match="No section or measure"):
        Score.build(parse_markers(path), 5.0)
