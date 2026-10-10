"""The render cache, from `docs/plans/05-playback.md` step 1.

Renders are pure functions of (file, parameters), so the cache is keyed by a
hash of both and every file in it is disposable.
"""

import os
import subprocess
from pathlib import Path

import pytest

from music_tools.domain import render


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "tune.wav"
    path.write_bytes(b"one")
    return path


class Producer:
    """A stand-in for ffmpeg that counts how often it was asked to work."""

    def __init__(self, payload: bytes = b"rendered") -> None:
        self.calls = 0
        self.payload = payload

    def __call__(self, source: Path, out: Path) -> None:
        self.calls += 1
        out.write_bytes(self.payload)


def test_the_key_is_stable_for_the_same_content_and_parameters(source):
    first = render.cache_key(source, op="speed", ratio=0.8)
    second = render.cache_key(source, op="speed", ratio=0.8)

    assert first == second


def test_the_key_does_not_depend_on_where_the_file_is(source, tmp_path):
    copy = tmp_path / "elsewhere.wav"
    copy.write_bytes(source.read_bytes())

    assert render.cache_key(source, op="speed") == render.cache_key(copy, op="speed")


def test_the_key_changes_with_the_content(source):
    before = render.cache_key(source, op="speed")
    source.write_bytes(b"two")

    assert render.cache_key(source, op="speed") != before


def test_the_key_changes_with_any_parameter(source):
    keys = {
        render.cache_key(source, op="speed", ratio=0.8),
        render.cache_key(source, op="speed", ratio=0.9),
        render.cache_key(source, op="pitch", ratio=0.8),
    }

    assert len(keys) == 3


def test_the_order_parameters_are_written_in_does_not_matter(source):
    assert render.cache_key(source, op="x", a=1, b=2) == render.cache_key(
        source, b=2, a=1, op="x"
    )


def test_a_miss_renders_into_the_cache_and_a_hit_does_not(source, cache):
    produce = Producer()

    first = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="speed", ratio=0.8
    )
    second = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="speed", ratio=0.8
    )

    assert first == second
    assert first.parent == cache
    assert first.suffix == ".wav"
    assert first.read_bytes() == b"rendered"
    assert produce.calls == 1


def test_a_file_deleted_underneath_is_rendered_again(source, cache):
    produce = Producer()
    cached = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="speed"
    )
    cached.unlink()

    again = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="speed"
    )

    assert again == cached
    assert again.read_bytes() == b"rendered"
    assert produce.calls == 2


def test_a_render_that_fails_leaves_nothing_behind_to_be_mistaken_for_one(
    source, cache
):
    def broken(source: Path, out: Path) -> None:
        out.write_bytes(b"half")
        raise RuntimeError("ffmpeg fell over")

    with pytest.raises(RuntimeError):
        render.render_or_hit(
            source, cache=cache, suffix=".wav", produce=broken, op="speed"
        )

    assert list(cache.iterdir()) == []
    produce = Producer()
    render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="speed"
    )
    assert produce.calls == 1


def test_eviction_drops_the_least_recently_used_until_it_fits(cache):
    cache.mkdir()
    for age, name in enumerate(("old.wav", "middle.wav", "new.wav")):
        path = cache / name
        path.write_bytes(b"x" * 10)
        os.utime(path, (1_000 + age, 1_000 + age))

    removed = render.evict(cache, max_bytes=20)

    assert [path.name for path in removed] == ["old.wav"]
    assert sorted(path.name for path in cache.iterdir()) == ["middle.wav", "new.wav"]


def test_eviction_of_a_cache_that_is_not_there_is_nothing(cache):
    assert render.evict(cache, max_bytes=0) == []


def test_a_hit_counts_as_use_so_eviction_spares_it(source, cache):
    produce = Producer()
    kept = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="a"
    )
    other = render.render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="b"
    )
    os.utime(kept, (1_000, 1_000))
    os.utime(other, (2_000, 2_000))

    render.render_or_hit(source, cache=cache, suffix=".wav", produce=produce, op="a")
    render.evict(cache, max_bytes=len(b"rendered"))

    assert kept.exists()
    assert not other.exists()


def test_the_cache_lives_beside_the_database(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSIC_TOOLS_DB", str(tmp_path / "data" / "practice.db"))

    assert render.cache_dir() == tmp_path / "data" / "cache"


# --- extraction (step 3) ----------------------------------------------------


@pytest.fixture
def video(tmp_path) -> Path:
    """A one-second mp4 with a sine track, made by the same ffmpeg under test."""
    path = tmp_path / "lesson.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def test_a_video_is_extracted_to_cached_audio_with_no_picture(video, cache):
    from pydub.utils import mediainfo

    audio = render.extract_audio(video, cache=cache)

    assert audio.parent == cache
    assert audio.suffix == ".wav"
    info = mediainfo(str(audio))
    assert info["codec_type"] == "audio"
    assert abs(float(info["duration"]) - 1.0) < 0.1


def test_extracting_twice_runs_ffmpeg_once(video, cache, monkeypatch):
    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args) or real_run(*args, **kwargs),
    )

    first = render.extract_audio(video, cache=cache)
    second = render.extract_audio(video, cache=cache)

    assert first == second
    assert len(calls) == 1


def test_a_file_ffmpeg_cannot_read_is_a_render_error(tmp_path, cache):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")

    with pytest.raises(render.RenderError, match="junk.mp4"):
        render.extract_audio(junk, cache=cache)

    assert list(cache.iterdir()) == []


# --- pitch (step 7) ---------------------------------------------------------


def sine(path: Path, *, seconds: float = 1.0) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ar", "44100", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def dominant_hz(path: Path) -> float:
    """The loudest frequency, by zero crossings: enough to tell a semitone."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(path).set_channels(1)
    samples = audio.get_array_of_samples()
    crossings = sum(
        1 for a, b in zip(samples, samples[1:]) if a < 0 <= b
    )  # rising edges
    return crossings / audio.duration_seconds


def test_zero_semitones_is_the_file_itself_so_nothing_is_rendered(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    assert render.shift_pitch(path, semitones=0, cache=cache) == path
    assert not cache.exists()


def test_an_octave_up_doubles_the_frequency_and_keeps_the_length(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    shifted = render.shift_pitch(path, semitones=12, cache=cache)

    assert shifted.parent == cache
    assert dominant_hz(shifted) == pytest.approx(880, rel=0.03)
    from pydub import AudioSegment

    assert AudioSegment.from_file(shifted).duration_seconds == pytest.approx(
        1.0, abs=0.05
    )


def test_down_a_fifth_is_a_ratio_of_two_thirds(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    shifted = render.shift_pitch(path, semitones=-7, cache=cache)

    assert dominant_hz(shifted) == pytest.approx(440 * 2 ** (-7 / 12), rel=0.03)


def test_the_fallback_without_rubberband_keeps_pitch_and_length_too(
    tmp_path, cache, monkeypatch
):
    monkeypatch.setattr(render, "has_rubberband", lambda: False)
    path = sine(tmp_path / "a.wav")

    shifted = render.shift_pitch(path, semitones=12, cache=cache)

    from pydub import AudioSegment

    assert dominant_hz(shifted) == pytest.approx(880, rel=0.03)
    assert AudioSegment.from_file(shifted).duration_seconds == pytest.approx(
        1.0, abs=0.05
    )


def test_a_shift_is_cached_per_amount(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    up = render.shift_pitch(path, semitones=2, cache=cache)
    down = render.shift_pitch(path, semitones=-2, cache=cache)

    assert up != down
    assert render.shift_pitch(path, semitones=2, cache=cache) == up


# --- speed as a render (step 8) ---------------------------------------------


def length_of(path: Path) -> float:
    from pydub import AudioSegment

    return AudioSegment.from_file(path).duration_seconds


def test_full_speed_at_no_shift_is_the_file_itself(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    assert render.render_audio(path, speed=1.0, cache=cache) == path
    assert not cache.exists()


def test_a_slower_render_is_longer_and_keeps_its_pitch(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    slow = render.render_audio(path, speed=0.5, cache=cache)

    assert slow.parent == cache
    assert length_of(slow) == pytest.approx(2.0, abs=0.05)
    assert dominant_hz(slow) == pytest.approx(440, rel=0.03)


def test_speed_and_pitch_are_one_render(tmp_path, cache):
    path = sine(tmp_path / "a.wav")

    both = render.render_audio(path, speed=0.8, semitones=12, cache=cache)

    assert length_of(both) == pytest.approx(1.25, abs=0.05)
    assert dominant_hz(both) == pytest.approx(880, rel=0.03)
    assert len(list(cache.iterdir())) == 1


@pytest.mark.parametrize("semitones", [0, 12, -12])
def test_the_fallback_slows_down_without_rubberband_too(
    tmp_path, cache, monkeypatch, semitones
):
    monkeypatch.setattr(render, "has_rubberband", lambda: False)
    path = sine(tmp_path / "a.wav")

    slow = render.render_audio(path, speed=0.5, semitones=semitones, cache=cache)

    # chained `atempo` loses a few milliseconds at the tail of each stage
    assert length_of(slow) == pytest.approx(2.0, rel=0.05)
    assert dominant_hz(slow) == pytest.approx(440 * 2 ** (semitones / 12), rel=0.03)


def test_atempo_is_chained_to_stay_inside_its_range():
    assert render.atempo_chain(0.8) == ["atempo=0.8"]
    assert render.atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert render.atempo_chain(3.0) == ["atempo=2.0", "atempo=1.5"]


def test_a_set_member_is_rendered_mono(tmp_path, cache):
    from pydub import AudioSegment

    path = tmp_path / "stereo.wav"
    AudioSegment.silent(duration=500).set_channels(2).export(path, format="wav")

    mono = render.render_audio(path, mono=True, cache=cache)

    assert mono.parent == cache
    assert AudioSegment.from_file(mono).channels == 1
    assert AudioSegment.from_file(mono).frame_rate == render.SET_RATE
    assert render.render_audio(path, cache=cache) == path  # stereo is untouched


def test_speeds_are_cached_to_the_slider_step(tmp_path, cache):
    path = sine(tmp_path / "a.wav", seconds=0.2)

    first = render.render_audio(path, speed=0.8, cache=cache)

    assert render.render_audio(path, speed=0.8000001, cache=cache) == first
    assert render.render_audio(path, speed=0.81, cache=cache) != first


@pytest.mark.parametrize("speed", [0.49, 1.01])
def test_a_speed_off_the_slider_is_refused(tmp_path, cache, speed):
    path = sine(tmp_path / "a.wav", seconds=0.2)

    with pytest.raises(ValueError, match="speed"):
        render.render_audio(path, speed=speed, cache=cache)


def test_the_ladder_is_the_common_speeds_plus_the_exercises_own():
    assert render.speed_ladder(None) == (0.6, 0.7, 0.8, 0.9)
    assert render.speed_ladder(0.75) == (0.6, 0.7, 0.75, 0.8, 0.9)
    assert render.speed_ladder(0.8) == (0.6, 0.7, 0.8, 0.9)
    assert render.speed_ladder(1.0) == (0.6, 0.7, 0.8, 0.9)


def test_prerendering_fills_the_cache_so_the_slider_hits_it(
    tmp_path, cache, monkeypatch
):
    path = sine(tmp_path / "a.wav", seconds=0.2)
    render.prerender([path], speeds=(0.6, 0.8), mono=True, cache=cache)
    made = set(cache.iterdir())

    calls = []
    monkeypatch.setattr(render, "run_ffmpeg", lambda *args: calls.append(args))
    assert render.playable_audio(path, speed=0.8, mono=True, cache=cache) in made
    assert render.playable_audio(path, speed=0.6, mono=True, cache=cache) in made
    assert calls == []
    assert len(made) == 3  # both speeds, and mono at full speed


def test_prerendering_skips_a_file_it_cannot_read(tmp_path, cache):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    good = sine(tmp_path / "a.wav", seconds=0.2)

    render.prerender([junk, good], speeds=(0.8,), mono=False, cache=cache)

    assert len(list(cache.glob("*.wav"))) == 1
