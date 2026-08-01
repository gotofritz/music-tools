#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "click>=8.1",
#   "PyYAML>=6.0",
#   "pydub>=0.25",
# ]
# ///

"""
Generate a rhythm-training loop by repeating an audio snippet and replacing
selected repetitions, bars or beats with silence.

Example:

    uv run loop.py trainer.yml
"""

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import click
import yaml
from pydub import AudioSegment

MARKER_PATTERN = re.compile(
    r'^(\d{1,2}:\d{2}:\d{2}\.\d+) Marker \((.*?)\): "(.*?)"'
)

# the marker types Transcribe! uses to open a new bar; anything containing
# "beat" (plain "beat", but also "t beat") subdivides the bar it is in
BAR_TYPES = {"section", "measure"}

MODES = ("sequence", "bars", "beats")


@dataclass
class Bar:
    """One bar of the snippet, in seconds from the start of the audio."""

    name: str
    start: float
    end: float = 0.0
    beats: list[float] = field(default_factory=list)
    raw_beats: list[float] = field(default_factory=list)  # as in the marker file


def resolve(root: Path, path: str) -> Path:
    """Prepend root to path, unless path is already absolute."""
    return root / Path(path).expanduser()


def parse_timestamp(timestamp: str) -> float:
    """Convert a 0:00:01.396236 marker timestamp to seconds."""
    time = datetime.strptime(timestamp, "%H:%M:%S.%f")
    return time.hour * 3600 + time.minute * 60 + time.second + time.microsecond / 1e6


def parse_markers(path: Path) -> list[tuple[float, str, str]]:
    """Read a Transcribe! marker export into (seconds, type, label) tuples."""
    markers = []
    for line in path.read_text().splitlines():
        match = MARKER_PATTERN.match(line.strip())
        if not match:
            continue
        timestamp, marker_type, label = match.groups()
        markers.append((parse_timestamp(timestamp), marker_type.lower(), label))
    return markers


def build_bars(markers: list[tuple[float, str, str]], duration: float) -> list[Bar]:
    """Turn markers into bars, treating the first marker as the start of the audio.

    Transcribe! writes the timestamps of the original track, so the first
    marker lands a fraction of a second in. That lead is an artefact of the
    export: every marker is shifted back by it, which puts the first bar at
    the top of the snippet.
    """
    if not markers:
        raise click.ClickException("No markers found in the marker file.")

    offset = markers[0][0]
    bars: list[Bar] = []
    end = duration

    for timestamp, marker_type, label in markers:
        start = timestamp - offset

        if label.strip().lower() == "end":
            end = start
            break

        if "beat" in marker_type:
            if bars:
                bars[-1].beats.append(start)
                bars[-1].raw_beats.append(timestamp)
            continue

        if marker_type not in BAR_TYPES:
            continue

        # a bar opens on its own first beat
        bars.append(
            Bar(
                name=label or str(len(bars) + 1),
                start=start,
                beats=[start],
                raw_beats=[timestamp],
            )
        )

    if not bars:
        raise click.ClickException(
            "No section or measure markers found in the marker file."
        )

    if bars[-1].start >= duration:
        raise click.ClickException(
            f"Markers run past the end of the snippet: bar {bars[-1].name} starts at "
            f"{bars[-1].start:.2f} s but the snippet is only {duration:.2f} s long. "
            "Do the markers belong to this snippet?"
        )

    for i, bar in enumerate(bars):
        bar.end = bars[i + 1].start if i + 1 < len(bars) else min(end, duration)

    return bars


def report_bars(bars: list[Bar]) -> None:
    """Print what was found, warning about bars with an odd number of beats."""
    click.echo(f"Bars: {len(bars)} ({' '.join(bar.name for bar in bars)})")

    counts = Counter(len(bar.beats) for bar in bars)
    expected, _ = counts.most_common(1)[0]

    for bar in bars:
        if len(bar.beats) == expected:
            continue

        click.echo(
            f"!  {bar.name} has {len(bar.beats)} beats, expected {expected}"
        )
        click.echo(
            "   beats at " + " ".join(f"{beat:.3f}" for beat in bar.raw_beats)
        )

        gaps = [
            (b - a, b) for a, b in zip(bar.raw_beats, bar.raw_beats[1:])
        ]
        if gaps and len(bar.beats) > expected:
            gap, beat = min(gaps)
            click.echo(
                f"   ({beat:.3f} is {gap:.2f}s after the previous beat)"
            )


def bar_slices(bars: list[Bar]) -> list[tuple[float, float]]:
    """Start and end of every bar."""
    return [(bar.start, bar.end) for bar in bars]


def beat_slices(bars: list[Bar]) -> list[tuple[float, float]]:
    """Start and end of every beat, across all bars."""
    slices = []
    for bar in bars:
        for i, beat in enumerate(bar.beats):
            end = bar.beats[i + 1] if i + 1 < len(bar.beats) else bar.end
            slices.append((beat, end))
    return slices


def read_pattern(section: dict, name: str) -> tuple[str, str, str]:
    """Pick the one of sequence/bars/beats a section uses, and validate it."""
    modes = [mode for mode in MODES if mode in section]

    if not modes:
        raise click.ClickException(
            f"{name}: needs one of {', '.join(MODES)}."
        )
    if len(modes) > 1:
        raise click.ClickException(
            f"{name}: {' and '.join(modes)} cannot be combined, pick one."
        )

    mode = modes[0]
    written = str(section[mode]).strip()
    pattern = "".join(written.split())  # spaces are only there to group

    if not pattern:
        raise click.ClickException(f"{name}: {mode} may not be empty.")

    invalid = set(pattern) - {"1", "x"}
    if invalid:
        raise click.ClickException(
            f"{name}: invalid characters: {', '.join(sorted(invalid))}"
        )

    return mode, pattern, written


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="""
Generate a rhythm training audio file from a YAML configuration.

Each character in a pattern is one unit of audio:

    1   play the unit
    x   silence of exactly the same duration

A section picks how long a unit is:

    sequence:   the whole snippet
    bars:       one bar   (needs "markers")
    beats:      one beat  (needs "markers")

Sections allow progressively harder exercises.

An optional top level "root" is prepended to "snippet", "markers" and
"output", so that only the file names have to be typed. Paths that are
already absolute are used as they are.

An optional top level "markers" points at a marker file exported from
Transcribe!. Section and measure markers open a bar, beat markers
subdivide it, and the first marker is taken to be the start of the
snippet. Spaces in a pattern are ignored, so beats can be grouped a bar
at a time.

Example:

root: ~/Documents/MuseScore4/Scores/TUNES/I/I want you Back - Jacksons 5
markers: I Want You Back - loop 1.txt

snippet: I Want You Back - loop 1.wav
output: I Want You Back - practice 1.wav

sections:
  - name: Whole thing
    repeat: 2
    bars: "1111"

  - name: Lose the end of A4
    repeat: 1
    beats: "1111 1111 1111 11xx"

  - name: Lose A4
    repeat: 1
    bars: "111x"

  - name: Lose everything but the first
    repeat: 8
    sequence: "1xxxxxxx"

Usage:

    uv run loop.py trainer.yml
""",
)
@click.argument(
    "config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def main(config: Path):

    with config.open() as f:
        cfg = yaml.safe_load(f)

    root = Path(cfg.get("root", "")).expanduser()

    snippet_path = resolve(root, cfg["snippet"])
    output_path = resolve(root, cfg["output"])
    markers_path = resolve(root, cfg["markers"]) if "markers" in cfg else None
    sections = cfg["sections"]

    if not snippet_path.is_file():
        raise click.ClickException(f"Snippet not found: {snippet_path}")
    if markers_path and not markers_path.is_file():
        raise click.ClickException(f"Marker file not found: {markers_path}")

    snippet = AudioSegment.from_file(snippet_path)
    duration = len(snippet) / 1000

    output = AudioSegment.empty()

    total_units = 0
    total_sections = len(sections)

    if str(root) != ".":
        click.echo(f"Root: {root}")
    click.echo(f"Loaded snippet: {snippet_path}")
    click.echo(f"Snippet length: {duration:.2f} s")

    bars: list[Bar] = []
    if markers_path:
        click.echo(f"Loaded markers: {markers_path}")
        bars = build_bars(parse_markers(markers_path), duration)
        report_bars(bars)

    click.echo()

    for i, section in enumerate(sections, start=1):

        name = section.get("name", f"Section {i}")
        repeat = int(section["repeat"])
        mode, pattern, written = read_pattern(section, name)

        if mode == "sequence":
            slices = [(0.0, duration)] * len(pattern)
        else:
            if not bars:
                raise click.ClickException(
                    f"{name}: {mode} needs a top level \"markers\" file."
                )
            slices = bar_slices(bars) if mode == "bars" else beat_slices(bars)
            if len(pattern) != len(slices):
                raise click.ClickException(
                    f"{name}: {mode} has {len(pattern)} characters but the "
                    f"markers define {len(slices)} {mode}."
                )

        click.echo(f"[{i}/{total_sections}] {name}")
        click.echo(f"    {repeat} × {written} ({mode})")

        for _ in range(repeat):
            for character, (start, end) in zip(pattern, slices):
                unit = snippet[int(start * 1000):int(end * 1000)]
                output += unit if character == "1" else AudioSegment.silent(
                    duration=len(unit), frame_rate=snippet.frame_rate
                )

        total_units += repeat * (len(pattern) if mode == "sequence" else 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.export(output_path)

    click.echo()
    click.echo("Done.")
    click.echo(f"Output : {output_path}")
    click.echo(f"Units  : {total_units}")
    click.echo(f"Length : {len(output)/1000:.1f} seconds")

    subprocess.run([
        "/Applications/Transcribe!.app/Contents/MacOS/Transcribe!",
        output_path,
    ])


if __name__ == "__main__":
    main()
