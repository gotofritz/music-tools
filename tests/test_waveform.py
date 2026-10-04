"""Peaks, from `docs/plans/05-playback.md` step 4: a waveform as min/max pairs."""

from array import array
from pathlib import Path

import pytest
from pydub import AudioSegment

from music_tools.domain import render, waveform


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


def wav(path: Path, samples: list[int], *, channels: int = 1) -> Path:
    """A wav holding exactly these 16-bit samples, interleaved if stereo."""
    AudioSegment(
        data=array("h", samples).tobytes(),
        sample_width=2,
        frame_rate=8000,
        channels=channels,
    ).export(path, format="wav")
    return path


def test_each_bucket_is_the_min_and_max_of_its_samples(tmp_path, cache):
    path = wav(tmp_path / "a.wav", [0, 16384, -16384, 8192, -8192, 0, 32767, 0])

    result = waveform.peaks(path, buckets=2, cache=cache)

    assert len(result) == 2
    assert result[0] == pytest.approx((-0.5, 0.5))
    assert result[1] == pytest.approx((-0.25, 32767 / 32768))


def test_silence_is_flat(tmp_path, cache):
    path = wav(tmp_path / "quiet.wav", [0] * 100)

    assert waveform.peaks(path, buckets=4, cache=cache) == [(0.0, 0.0)] * 4


def test_stereo_gives_the_same_shape_as_mono(tmp_path, cache):
    mono = wav(tmp_path / "mono.wav", [1000, -1000] * 50)
    stereo = wav(tmp_path / "stereo.wav", [1000, 1000, -1000, -1000] * 50, channels=2)

    assert len(waveform.peaks(mono, buckets=10, cache=cache)) == len(
        waveform.peaks(stereo, buckets=10, cache=cache)
    )


def test_a_clip_shorter_than_the_bucket_count_still_returns_every_bucket(
    tmp_path, cache
):
    path = wav(tmp_path / "tiny.wav", [100, -100, 200])

    result = waveform.peaks(path, buckets=8, cache=cache)

    assert len(result) == 8
    assert max(high for _, high in result) == pytest.approx(200 / 32768)


def test_peaks_are_cached_beside_the_renders(tmp_path, cache, monkeypatch):
    path = wav(tmp_path / "a.wav", [0, 1000, -1000, 0] * 10)
    first = waveform.peaks(path, buckets=4, cache=cache)
    monkeypatch.setattr(
        waveform.AudioSegment, "from_file", lambda *a, **k: pytest.fail("decoded")
    )

    second = waveform.peaks(path, buckets=4, cache=cache)

    assert second == first
    assert len(list(cache.glob("*.json"))) == 1


def test_a_different_bucket_count_is_a_different_cache_entry(tmp_path, cache):
    path = wav(tmp_path / "a.wav", [0, 1000, -1000, 0] * 10)

    waveform.peaks(path, buckets=4, cache=cache)
    waveform.peaks(path, buckets=8, cache=cache)

    assert len(list(cache.glob("*.json"))) == 2


def test_a_file_that_cannot_be_decoded_is_a_render_error(tmp_path, cache):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio")

    with pytest.raises(render.RenderError, match="junk.mp3"):
        waveform.peaks(junk, buckets=4, cache=cache)
