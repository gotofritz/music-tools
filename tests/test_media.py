"""Media attached to an exercise: rows in, files left where they are.

`docs/plans/04-exercise-media.md`. The storage half is two tables; the
decisions — which kind carries which column, what a path is allowed to be, and
what makes several files one thing to play — live in `domain/media.py`, the way
`domain/catalogue.py` holds the decisions about the catalogue.
"""

from datetime import datetime
from pathlib import Path

import pytest

from music_tools.db import repository as repo
from music_tools.domain import media

NOW = datetime(2026, 8, 17, 21, 5)


@pytest.fixture
def songs(db):
    return repo.create_module(db, name="SONGS", log_group="REPERTOIRE")


@pytest.fixture
def le_freak(db, songs):
    return repo.create_exercise(db, module_id=songs.id, name="le freak")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A scores directory of our own, named the way a real one would be."""
    root = tmp_path / "TUNES"
    root.mkdir()
    monkeypatch.setenv("MUSIC_TOOLS_MEDIA_ROOTS", str(root))
    return root


@pytest.fixture
def audio_file(roots):
    def write(name: str, *, seconds: float = 4.0) -> Path:
        from pydub import AudioSegment

        path = roots / name
        path.parent.mkdir(parents=True, exist_ok=True)
        AudioSegment.silent(duration=int(seconds * 1000)).export(path, format="wav")
        return path

    return write


# --- the roots guard --------------------------------------------------------


def test_the_configured_roots_come_from_the_environment(roots):
    assert media.media_roots() == (roots,)


def test_a_path_inside_the_roots_resolves_to_itself(audio_file):
    path = audio_file("S/Stomp/loop.wav")

    assert media.resolve_within_roots(str(path)) == path


def test_a_path_outside_the_roots_is_refused(roots, tmp_path):
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"")

    with pytest.raises(media.OutsideRoots):
        media.resolve_within_roots(str(outside))


def test_climbing_out_of_a_root_is_refused(roots):
    with pytest.raises(media.OutsideRoots):
        media.resolve_within_roots(str(roots / ".." / "etc" / "passwd"))


def test_a_relative_path_is_refused_rather_than_guessed_at(roots):
    with pytest.raises(media.OutsideRoots):
        media.resolve_within_roots("loop.wav")


# --- attaching one thing at a time ------------------------------------------


def test_an_audio_file_is_attached_by_path_and_gets_a_group_of_its_own(
    db, le_freak, audio_file
):
    path = audio_file("S/Stomp/loop.wav")

    source = media.attach(
        db, exercise_id=le_freak.id, kind="file", path=str(path), now=NOW
    )

    assert source.kind == "file"
    assert source.path == str(path)
    assert source.group_id is not None  # a set of one, so there is one shape
    assert source.gain == 1.0 and source.pan == 0.0 and source.muted is False
    assert Path(source.path).exists()  # referenced, never copied


def test_a_file_outside_the_roots_is_not_attached(db, le_freak, roots, tmp_path):
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"")

    with pytest.raises(media.OutsideRoots):
        media.attach(
            db, exercise_id=le_freak.id, kind="file", path=str(outside), now=NOW
        )

    assert media.exercise_media(db, exercise_id=le_freak.id) == []


def test_a_file_that_is_not_there_is_refused(db, le_freak, roots):
    with pytest.raises(media.MissingFile):
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(roots / "nothing.wav"),
            now=NOW,
        )


def test_a_youtube_url_is_attached_as_a_url_and_has_no_group(db, le_freak):
    source = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="youtube",
        url="https://www.youtube.com/watch?v=abc123",
        now=NOW,
    )

    assert source.url == "https://www.youtube.com/watch?v=abc123"
    assert source.group_id is None  # an embed cannot be sample-locked to anything


def test_a_musescore_file_is_attached_by_path_without_a_group(db, le_freak, audio_file):
    path = audio_file("S/Stomp/stomp.mscz")

    source = media.attach(
        db, exercise_id=le_freak.id, kind="musescore", path=str(path), now=NOW
    )

    assert source.kind == "musescore"
    assert source.group_id is None


def test_text_is_attached_as_text(db, le_freak):
    source = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="text",
        body="Bb minor pentatonic, two octaves",
        label="fingering",
        now=NOW,
    )

    assert source.body == "Bb minor pentatonic, two octaves"
    assert source.label == "fingering"
    assert source.group_id is None


def test_a_kind_nobody_knows_is_refused(db, le_freak):
    with pytest.raises(media.BadMedia):
        media.attach(db, exercise_id=le_freak.id, kind="hologram", body="x", now=NOW)


@pytest.mark.parametrize(
    "kind,fields",
    [
        ("file", {"url": "https://example.com/x.wav"}),
        ("youtube", {"path": "/tmp/x.wav"}),
        ("text", {}),
        ("musescore", {"body": "notes"}),
    ],
)
def test_a_kind_without_what_it_needs_is_refused(db, le_freak, roots, kind, fields):
    with pytest.raises(media.BadMedia):
        media.attach(db, exercise_id=le_freak.id, kind=kind, now=NOW, **fields)


def test_media_cannot_be_attached_to_an_exercise_that_is_not_there(db, roots):
    with pytest.raises(media.NotFound):
        media.attach(db, exercise_id=404, kind="text", body="nothing", now=NOW)


# --- what the page reads ----------------------------------------------------


def test_attachments_come_back_in_the_order_they_were_added(db, le_freak, audio_file):
    media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("loop.wav")),
        now=NOW,
    )
    media.attach(
        db, exercise_id=le_freak.id, kind="youtube", url="https://youtu.be/abc", now=NOW
    )
    media.attach(db, exercise_id=le_freak.id, kind="text", body="notes", now=NOW)

    cards = media.exercise_media(db, exercise_id=le_freak.id)

    assert [card.kind for card in cards] == ["file", "youtube", "text"]
    assert [card.is_set for card in cards] == [False, False, False]


def test_a_file_card_carries_its_group_and_its_one_track(db, le_freak, audio_file):
    source = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("loop.wav")),
        now=NOW,
    )

    card = media.exercise_media(db, exercise_id=le_freak.id)[0]

    assert card.group is not None
    assert [track.id for track in card.sources] == [source.id]


# --- removing and reordering ------------------------------------------------


def test_detaching_a_source_leaves_the_file_alone(db, le_freak, audio_file):
    path = audio_file("loop.wav")
    source = media.attach(
        db, exercise_id=le_freak.id, kind="file", path=str(path), now=NOW
    )

    media.detach(db, source_id=source.id)

    assert media.exercise_media(db, exercise_id=le_freak.id) == []
    assert path.exists()


def test_detaching_the_last_track_takes_the_empty_group_with_it(
    db, le_freak, audio_file
):
    source = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("loop.wav")),
        now=NOW,
    )

    media.detach(db, source_id=source.id)

    assert repo.media_groups_for_exercise(db, exercise_id=le_freak.id) == []


def test_detaching_something_that_is_not_there_is_an_error(db):
    with pytest.raises(media.UnknownMedia):
        media.detach(db, source_id=404)


def test_a_card_can_be_moved_up_and_down_the_exercise(db, le_freak, audio_file):
    first = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("loop.wav")),
        now=NOW,
    )
    media.attach(
        db, exercise_id=le_freak.id, kind="youtube", url="https://youtu.be/abc", now=NOW
    )

    media.move(db, source_id=first.id, direction="down")

    assert [
        card.kind for card in media.exercise_media(db, exercise_id=le_freak.id)
    ] == [
        "youtube",
        "file",
    ]

    media.move(db, source_id=first.id, direction="up")

    assert [
        card.kind for card in media.exercise_media(db, exercise_id=le_freak.id)
    ] == [
        "file",
        "youtube",
    ]


def test_moving_the_end_of_the_list_further_is_a_no_op(db, le_freak, audio_file):
    only = media.attach(db, exercise_id=le_freak.id, kind="text", body="x", now=NOW)

    media.move(db, source_id=only.id, direction="up")

    assert [
        card.kind for card in media.exercise_media(db, exercise_id=le_freak.id)
    ] == ["text"]


def test_a_direction_nobody_knows_is_refused(db, le_freak):
    only = media.attach(db, exercise_id=le_freak.id, kind="text", body="x", now=NOW)

    with pytest.raises(ValueError):
        media.move(db, source_id=only.id, direction="sideways")


# --- media goes when the exercise goes --------------------------------------


def test_deleting_an_exercise_takes_its_media_with_it(db, le_freak, audio_file):
    source = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("loop.wav")),
        now=NOW,
    )

    repo.delete_exercise(db, le_freak.id)

    assert repo.get_media_source(db, source.id) is None
    assert repo.media_groups_for_exercise(db, exercise_id=le_freak.id) == []


# --- track sets: several files that are one thing to play -------------------


def test_a_second_file_added_to_a_group_makes_a_track_set(db, le_freak, audio_file):
    bass = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        label="bass",
        now=NOW,
    )
    assert bass.group_id is not None

    drums = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("drums.wav")),
        label="drums",
        group_id=bass.group_id,
        now=NOW,
    )

    cards = media.exercise_media(db, exercise_id=le_freak.id)
    assert len(cards) == 1  # one player, not two cards in a row
    assert cards[0].is_set
    assert [track.label for track in cards[0].sources] == ["bass", "drums"]
    assert drums.position == 1  # order down the mixer strip


def test_a_set_is_at_most_eight_members(db, le_freak, audio_file):
    first = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("track0.wav")),
        now=NOW,
    )
    for number in range(1, 8):
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(audio_file(f"track{number}.wav")),
            group_id=first.group_id,
            now=NOW,
        )

    with pytest.raises(media.SetTooBig):
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(audio_file("track8.wav")),
            group_id=first.group_id,
            now=NOW,
        )

    card = media.exercise_media(db, exercise_id=le_freak.id)[0]
    assert len(card.sources) == 8


def test_a_member_that_disagrees_on_length_is_named_and_refused(
    db, le_freak, audio_file
):
    first = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav", seconds=4.0)),
        now=NOW,
    )
    odd = audio_file("half.wav", seconds=2.0)

    with pytest.raises(media.MembersDisagree) as refused:
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(odd),
            group_id=first.group_id,
            now=NOW,
        )

    assert "half.wav" in str(refused.value)
    assert len(media.exercise_media(db, exercise_id=le_freak.id)[0].sources) == 1


def test_a_member_within_the_tolerance_is_allowed(db, le_freak, audio_file):
    first = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav", seconds=4.0)),
        now=NOW,
    )

    media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("drums.wav", seconds=4.1)),
        group_id=first.group_id,
        now=NOW,
    )

    assert len(media.exercise_media(db, exercise_id=le_freak.id)[0].sources) == 2


def test_a_file_whose_length_cannot_be_read_is_not_added_to_a_set(
    db, le_freak, audio_file, roots
):
    first = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        now=NOW,
    )
    nonsense = roots / "notes.txt"
    nonsense.write_text("this is not audio")

    with pytest.raises(media.UnreadableAudio):
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(nonsense),
            group_id=first.group_id,
            now=NOW,
        )


def test_a_group_that_is_not_there_cannot_be_added_to(db, le_freak, audio_file):
    with pytest.raises(media.UnknownMedia):
        media.attach(
            db,
            exercise_id=le_freak.id,
            kind="file",
            path=str(audio_file("bass.wav")),
            group_id=404,
            now=NOW,
        )


def test_a_track_can_be_named_and_mixed(db, le_freak, audio_file):
    track = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        now=NOW,
    )

    updated = media.describe(
        db, source_id=track.id, label="bass DI", gain=0.5, pan=-0.4, muted=True
    )

    assert (updated.label, updated.gain, updated.pan, updated.muted) == (
        "bass DI",
        0.5,
        -0.4,
        True,
    )


def test_the_mix_stays_inside_what_a_mixer_can_mean(db, le_freak, audio_file):
    track = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        now=NOW,
    )

    with pytest.raises(media.BadMedia):
        media.describe(db, source_id=track.id, pan=2.0)
    with pytest.raises(media.BadMedia):
        media.describe(db, source_id=track.id, gain=-1.0)


def test_a_set_can_be_labelled_as_a_whole(db, le_freak, audio_file):
    track = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        now=NOW,
    )

    media.label_set(db, group_id=track.group_id or 0, label="stems")

    assert media.exercise_media(db, exercise_id=le_freak.id)[0].label == "stems"


def test_detaching_one_member_leaves_the_set_behind(db, le_freak, audio_file):
    bass = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("bass.wav")),
        now=NOW,
    )
    drums = media.attach(
        db,
        exercise_id=le_freak.id,
        kind="file",
        path=str(audio_file("drums.wav")),
        group_id=bass.group_id,
        now=NOW,
    )

    media.detach(db, source_id=drums.id)

    card = media.exercise_media(db, exercise_id=le_freak.id)[0]
    assert [track.id for track in card.sources] == [bass.id]
    assert not card.is_set
