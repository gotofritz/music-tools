from music_tools.loop import Score, parse_markers


def test_loop_is_importable():
    assert Score is not None
    assert parse_markers is not None
