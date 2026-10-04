"""Waveform peaks: what the player draws, computed once and cached.

A waveform is a few thousand min/max pairs, bucketed over the length of the
file, so the cost of drawing does not grow with the length of the tune and
the browser never decodes a file just to paint it. The reduction is plain
Python over pydub's raw samples: a 2000-bucket pass over a snippet does not
earn numpy.
"""

import json
from pathlib import Path

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from music_tools.domain import render

Peak = tuple[float, float]


def peaks(path: Path, /, *, buckets: int, cache: Path) -> list[Peak]:
    """`buckets` (min, max) pairs in -1..1 over the whole file.

    Mono and stereo give the same shape: a bucket spans a range of frames and
    takes the extremes of every channel in it. A bucket with no frames in it
    (a clip shorter than the bucket count) is flat.
    """

    def produce(source: Path, out: Path) -> None:
        out.write_text(json.dumps(_reduce(source, buckets=buckets)))

    cached = render.render_or_hit(
        path,
        cache=cache,
        suffix=".json",
        produce=produce,
        op="peaks",
        buckets=buckets,
    )
    return [(low, high) for low, high in json.loads(cached.read_text())]


def _reduce(path: Path, *, buckets: int) -> list[Peak]:
    try:
        audio = AudioSegment.from_file(path)
    except CouldntDecodeError:
        raise render.RenderError(f"{path}: could not be decoded") from None

    samples = audio.get_array_of_samples()
    channels = audio.channels
    frames = len(samples) // channels
    scale = float(1 << (8 * audio.sample_width - 1))

    result: list[Peak] = []
    for bucket in range(buckets):
        start = bucket * frames // buckets * channels
        end = (bucket + 1) * frames // buckets * channels
        window = samples[start:end]
        if len(window) == 0:
            result.append((0.0, 0.0))
        else:
            result.append((min(window) / scale, max(window) / scale))
    return result
