"""The render cache: derived audio, keyed by what it was derived from.

Extractions, speed renders, pitch renders and Phase 7's outputs are pure
functions of (file, parameters). So a cached file is named by a hash of both,
lives under the app data directory, and may be deleted at any time — the next
request regenerates it. Nothing in the database points at it, which is what
makes eviction safe.

This module owns the cache and nothing about ffmpeg: the work is a `produce`
callable passed in, so the cache is tested without it.
"""

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

from pydub.utils import mediainfo

from music_tools.db.connection import default_db_path

#: A render is written here and renamed into place, so a reader never sees half
#: a file and a failed render leaves nothing that looks like a hit.
_PARTIAL = ".partial"  # in the name, before the suffix ffmpeg reads


class RenderError(RuntimeError):
    """ffmpeg could not make the render; the message names the file."""


def cache_dir() -> Path:
    """Beside the database, which is already inside the default media roots."""
    return default_db_path().parent / "cache"


def cache_key(source: Path, /, **params: object) -> str:
    """A hash of the file's content and the parameters of the render.

    Content rather than path or mtime: moving or touching a file does not
    invalidate its renders, and editing it does. Parameters are sorted so the
    order they are written in does not matter.
    """
    with source.open("rb") as handle:
        content = hashlib.file_digest(handle, "sha256").hexdigest()
    wanted = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(f"{content}\n{wanted}".encode()).hexdigest()


def render_or_hit(
    source: Path,
    /,
    *,
    cache: Path,
    suffix: str,
    produce: Callable[[Path, Path], None],
    **params: object,
) -> Path:
    """The cached render of `source` under `params`, made first if it is missing.

    `produce(source, out)` writes the render to `out`. A hit refreshes the
    file's mtime, which is what eviction reads as "recently used".
    """
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{cache_key(source, **params)}{suffix}"
    if target.is_file():
        os.utime(target)
        return target

    partial = cache / f"{target.stem}.{uuid.uuid4().hex}{_PARTIAL}{suffix}"
    try:
        produce(source, partial)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def evict(cache: Path, *, max_bytes: int) -> list[Path]:
    """Delete the least recently used files until the cache fits in `max_bytes`.

    Returns what was removed. Only files are touched, and only ones in the
    cache directory; the database is not consulted because it holds no
    reference to any of them.
    """
    if not cache.is_dir():
        return []
    files = sorted(
        (path for path in cache.iterdir() if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    total = sum(path.stat().st_size for path in files)
    removed: list[Path] = []
    for path in files:
        if total <= max_bytes:
            break
        total -= path.stat().st_size
        path.unlink()
        removed.append(path)
    return removed


def run_ffmpeg(*args: str | Path) -> None:
    """Run ffmpeg quietly, turning a failure into a `RenderError`.

    The message is ffmpeg's last line of complaint, which is the one that says
    what was wrong with the file.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *map(str, args)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as failed:
        lines = failed.stderr.strip().splitlines()
        raise RenderError(lines[-1] if lines else "ffmpeg failed") from None
    except FileNotFoundError:
        raise RenderError("ffmpeg is not installed") from None


def extract_audio(source: Path, /, *, cache: Path) -> Path:
    """The audio track of a video, as a cached wav. The picture is dropped.

    Audio only, even when the file is a video: the sound is the practice
    material. The same call serves an audio file unchanged in meaning, so
    callers need not ask what they were handed.
    """

    def produce(source: Path, out: Path) -> None:
        try:
            run_ffmpeg("-i", source, "-vn", out)
        except RenderError as failed:
            raise RenderError(f"{source}: {failed}") from None

    return render_or_hit(
        source, cache=cache, suffix=".wav", produce=produce, op="extract"
    )


#: A shift beyond an octave either way is not a practice aid, and the fallback
#: filter chain (`atempo` is only defined for 0.5-2) is only good that far.
MAX_SEMITONES = 12


@lru_cache(maxsize=1)
def has_rubberband() -> bool:
    """Whether this ffmpeg was built with the `rubberband` filter."""
    listing = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    )
    return " rubberband " in listing.stdout


def shift_pitch(source: Path, /, *, semitones: int, cache: Path) -> Path:
    """`source` transposed by `semitones` at the same speed, as a cached render."""
    return render_audio(source, semitones=semitones, cache=cache)


#: The speed slider's range, as a fraction of the target. Slower than half is
#: not playing along any more, and faster than the target is not a ratio the
#: schedule can read (`tempo.py` caps it at 1.0).
MIN_SPEED = 0.5
MAX_SPEED = 1.0

#: The rate a member of a set is played at. Decoded audio is the browser's
#: budget — float32, held whole — and mono at half the CD rate brings eight
#: four-minute stems from around 680 MB to under 200 MB.
SET_RATE = 22050

#: The speeds that get used, rendered when the media is attached so the common
#: moves of the slider are cache hits rather than a wait. Full speed is the
#: file itself.
LADDER = (0.6, 0.7, 0.8, 0.9)


def render_audio(
    source: Path,
    /,
    *,
    speed: float = 1.0,
    semitones: int = 0,
    mono: bool = False,
    cache: Path,
) -> Path:
    """`source` at `speed` and transposed by `semitones`, as one cached render.

    Speed is a render rather than `playbackRate` because Web Audio has no
    `preservesPitch` (docs/plans/05-playback.md, 5b): slower here means longer
    at the same pitch. Speed and pitch are one ffmpeg pass, so a set member
    goes through one job whatever is asked of it. `mono` is how a member of a
    set is played: downmixed first, which halves the stretch's work, and
    resampled to `SET_RATE`, which halves what the browser fetches and holds.

    Speed is rounded to the slider's step, so 0.8 and 0.8000001 are one entry.
    Full speed, no shift and stereo is the file itself: nothing rendered.
    """
    speed = round(speed, 2)
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ValueError(f"a speed runs from {MIN_SPEED} to {MAX_SPEED}, not {speed}")
    if not -MAX_SEMITONES <= semitones <= MAX_SEMITONES:
        raise ValueError(f"pitch shifts are limited to ±{MAX_SEMITONES} semitones")
    if speed == 1.0 and semitones == 0 and not mono:
        return source
    factor = 2 ** (semitones / 12)

    def produce(source: Path, out: Path) -> None:
        chain = ["aformat=channel_layouts=mono"] if mono else []
        if speed == 1.0 and semitones == 0:
            pass
        elif has_rubberband():
            chain.append(f"rubberband=tempo={speed}:pitch={factor}")
        else:
            # `asetrate` moves pitch and speed together and `atempo` takes the
            # unwanted half back out: lower quality, same result.
            if semitones:
                rate = int(mediainfo(str(source))["sample_rate"])
                chain += [f"asetrate={rate * factor}", f"aresample={rate}"]
            chain += atempo_chain(speed / factor)
        if mono:
            chain.append(f"aresample={SET_RATE}")
        try:
            run_ffmpeg("-i", source, "-vn", "-af", ",".join(chain), out)
        except RenderError as failed:
            raise RenderError(f"{source}: {failed}") from None

    return render_or_hit(
        source,
        cache=cache,
        suffix=".wav",
        produce=produce,
        op="render",
        speed=speed,
        semitones=semitones,
        mono=mono,
        rate=SET_RATE if mono else None,
        engine="rubberband" if has_rubberband() else "atempo",
    )


def atempo_chain(ratio: float) -> list[str]:
    """`atempo` filters whose product is `ratio`, each inside 0.5–2.

    Older ffmpeg builds only accept that range in one instance, and a
    semitone shift on top of a slow speed goes below it.
    """
    chain: list[str] = []
    while ratio < 0.5:
        chain.append("atempo=0.5")
        ratio /= 0.5
    while ratio > 2.0:
        chain.append("atempo=2.0")
        ratio /= 2.0
    chain.append(f"atempo={ratio:g}")
    return chain


def speed_ladder(ratio: float | None) -> tuple[float, ...]:
    """What to render on attach: `LADDER`, plus the exercise's own speed.

    The exercise's own speed is where the slider will sit when the card is
    drawn, so it is the render most likely to be wanted first.
    """
    speeds = set(LADDER)
    if ratio is not None and MIN_SPEED <= round(ratio, 2) < MAX_SPEED:
        speeds.add(round(ratio, 2))
    return tuple(sorted(speeds))


def prerender(
    sources: Iterable[Path], /, *, speeds: Iterable[float], mono: bool, cache: Path
) -> None:
    """Render every source at every speed, ahead of being asked.

    Run in the background after an attach. A file that will not render is
    skipped: the player asks for it again and gets the message then. Mono at
    full speed comes along for a set, since that is what it plays first.
    """
    wanted = tuple(speeds) + ((1.0,) if mono else ())
    for source in sources:
        for speed in wanted:
            try:
                playable_audio(source, speed=speed, mono=mono, cache=cache)
            except RenderError:
                break


#: What ffmpeg is handed that carries a picture the app never shows.
VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi")


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def playable_audio(
    source: Path,
    /,
    *,
    speed: float = 1.0,
    semitones: int = 0,
    mono: bool = False,
    cache: Path,
) -> Path:
    """What the player should be given for `source`: audio, at this speed and pitch.

    A plain audio file at full speed and no shift is the file itself — no
    render, no cache entry. A video goes through extraction first, and the
    render is applied to whatever that returns.
    """
    audio = extract_audio(source, cache=cache) if is_video(source) else source
    return render_audio(audio, speed=speed, semitones=semitones, mono=mono, cache=cache)


def duration_seconds(path: Path, /) -> float:
    """The length of a file, read from its header rather than by decoding it."""
    try:
        return float(mediainfo(str(path))["duration"])
    except (KeyError, ValueError):
        raise RenderError(f"{path}: length cannot be read") from None
