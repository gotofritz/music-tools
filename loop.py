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
selected repetitions, bars, beats or marked spans with silence.

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
# the word in brackets is the colour of the block, its text is on the
# lines that follow, up to a blank line or the next timestamp
TEXTBLOCK_PATTERN = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}\.\d+) Textblock \((.*?)\):"
)
TIMESTAMPED = re.compile(r"^\d{1,2}:\d{2}:\d{2}\.\d+ ")

# a pattern is a run of [bar or beat] and {textblock} addresses
TOKEN_PATTERN = re.compile(r"\[([^\[\]]*)\]|\{([^{}]*)\}")

# the marker types Transcribe! uses to open a new bar; anything containing
# "beat" (plain "beat", but also "t beat") subdivides the bar it is in
BAR_TYPES = {"section", "measure"}

BAR_INDEX = re.compile(r"^(\d+)$")
BEAT_INDEX = re.compile(r"^(\d+)\.(\d+)$")

MODES = ("sequence", "bars", "beats", "markers")

EPSILON = 1e-6


@dataclass
class Beat:
    """One beat, in seconds from the start of the audio."""

    label: str
    start: float
    end: float = 0.0
    raw: float = 0.0  # timestamp as written in the marker file


@dataclass
class Bar:
    """One bar of the snippet. Its own marker is also its first beat."""

    name: str
    start: float
    end: float = 0.0
    beats: list[Beat] = field(default_factory=list)


@dataclass
class TextBlock:
    """A free floating label. It has a start but no end of its own."""

    name: str
    start: float
    raw: float = 0.0


def resolve(root: Path, path: str) -> Path:
    """Prepend root to path, unless path is already absolute."""
    return root / Path(path).expanduser()


def parse_timestamp(timestamp: str) -> float:
    """Convert a 0:00:01.396236 marker timestamp to seconds."""
    time = datetime.strptime(timestamp, "%H:%M:%S.%f")
    return time.hour * 3600 + time.minute * 60 + time.second + time.microsecond / 1e6


def parse_markers(path: Path) -> list[tuple[float, str, str]]:
    """Read a Transcribe! export into (seconds, kind, label) tuples.

    Kind is the marker type as written, or "textblock", in which case the
    label is the text of the block rather than its colour.
    """
    entries: list[tuple[float, str, str]] = []
    pending: list[str] = []
    pending_at = 0.0

    def flush() -> None:
        if pending:
            entries.append((pending_at, "textblock", " ".join(pending).strip()))
        pending.clear()

    for line in path.read_text().splitlines():
        stripped = line.strip()

        if match := MARKER_PATTERN.match(stripped):
            flush()
            timestamp, kind, label = match.groups()
            entries.append((parse_timestamp(timestamp), kind.lower(), label.strip()))
            continue

        if match := TEXTBLOCK_PATTERN.match(stripped):
            flush()
            pending_at = parse_timestamp(match.group(1))
            continue

        # a blank line, or anything timestamped, closes the block
        if not stripped or TIMESTAMPED.match(stripped):
            flush()
            continue

        pending.append(stripped)

    flush()
    return entries


class Score:
    """The bars, beats and text blocks of one snippet, in playing order."""

    def __init__(self, bars: list[Bar], textblocks: list[TextBlock], duration: float):
        self.bars = bars
        self.textblocks = textblocks
        self.duration = duration  # of the score, which may stop short of the audio
        self.end_marker: str | None = None

        # bars win over beats, earlier wins over later
        self.by_label: dict[str, tuple[float, float]] = {}
        for bar in bars:
            self.by_label.setdefault(bar.name.lower(), (bar.start, bar.end))
        for bar in bars:
            for beat in bar.beats:
                if beat.label:
                    self.by_label.setdefault(beat.label.lower(), (beat.start, beat.end))

        self.by_block = {block.name.lower(): block for block in textblocks}
        self.boundaries = sorted(
            {beat.start for bar in bars for beat in bar.beats} | {duration}
        )

    @classmethod
    def build(
        cls, entries: list[tuple[float, str, str]], duration: float
    ) -> "Score":
        """Turn marker entries into a score, first marker at the top of the audio.

        Transcribe! writes the timestamps of the original track, so the first
        marker lands some way in. That lead is an artefact of the export:
        every timestamp is shifted back by it, which puts the first bar at
        the start of the snippet.
        """
        if not entries:
            raise click.ClickException("No markers found in the marker file.")

        offset = entries[0][0]
        bars: list[Bar] = []
        textblocks: list[TextBlock] = []
        end = duration

        for timestamp, kind, label in entries:
            start = timestamp - offset

            if label.lower() == "end":
                end = start
                break

            if kind == "textblock":
                if label:
                    textblocks.append(TextBlock(label, start, timestamp))
                continue

            if "beat" in kind:
                if bars:
                    bars[-1].beats.append(Beat(label, start, raw=timestamp))
                continue

            if kind not in BAR_TYPES:
                continue

            # a bar opens on its own first beat
            bars.append(
                Bar(
                    name=label or str(len(bars) + 1),
                    start=start,
                    beats=[Beat(label, start, raw=timestamp)],
                )
            )

        if not bars:
            raise click.ClickException(
                "No section or measure markers found in the marker file."
            )

        # A bar marker with no beats under it closes the bar before it rather
        # than opening one of its own: the passage was marked up by dropping a
        # marker at each barline, including the one the passage ends on. That
        # last one is the end of the audio, not a bar to play.
        end_marker = None
        if len(bars) > 1 and len(bars[-1].beats) == 1:
            end_marker = bars.pop()
            end = min(end, end_marker.start)

        if bars[-1].start >= duration:
            raise click.ClickException(
                f"Markers run past the end of the snippet: bar {bars[-1].name} starts "
                f"at {bars[-1].start:.2f} s but the snippet is only {duration:.2f} s "
                "long. Do the markers belong to this snippet?"
            )

        end = min(end, duration)
        for i, bar in enumerate(bars):
            bar.end = bars[i + 1].start if i + 1 < len(bars) else end
            for j, beat in enumerate(bar.beats):
                beat.end = bar.beats[j + 1].start if j + 1 < len(bar.beats) else bar.end

        score = cls(bars, textblocks, end)
        score.end_marker = end_marker.name if end_marker else None
        return score

    def bar_slices(self) -> list[tuple[float, float]]:
        """Start and end of every bar."""
        return [(bar.start, bar.end) for bar in self.bars]

    def beat_slices(self) -> list[tuple[float, float]]:
        """Start and end of every beat, across all bars."""
        return [(beat.start, beat.end) for bar in self.bars for beat in bar.beats]

    def next_boundary(self, after: float) -> float:
        """The first bar or beat line strictly after a point in time."""
        for boundary in self.boundaries:
            if boundary > after + EPSILON:
                return boundary
        return self.duration

    def address(self, text: str) -> tuple[float, float] | None:
        """Resolve [4], [D51], [1.4] or [b2] to a start and an end."""
        key = text.strip().lower()

        if key in self.by_label:
            return self.by_label[key]

        if match := BAR_INDEX.match(key):
            index = int(match.group(1))
            if 1 <= index <= len(self.bars):
                bar = self.bars[index - 1]
                return bar.start, bar.end
            return None

        if match := BEAT_INDEX.match(key):
            bar_index, beat_index = (int(group) for group in match.groups())
            if 1 <= bar_index <= len(self.bars):
                beats = self.bars[bar_index - 1].beats
                if 1 <= beat_index <= len(beats):
                    beat = beats[beat_index - 1]
                    return beat.start, beat.end
        return None

    def block(self, text: str) -> tuple[float, float] | None:
        """Resolve {JOHN} or {JOHN-3} to a start and an end.

        A block on its own runs to the next bar or beat. With a trailing
        address it runs to the start of whatever that names.
        """
        key = text.strip().lower()

        if key in self.by_block:
            start = self.by_block[key].start
            return start, self.next_boundary(start)

        if "-" in key:
            name, _, until = key.rpartition("-")
            if (block := self.by_block.get(name.strip())) and (
                target := self.address(until)
            ):
                return block.start, target[0]
        return None

    def span(self, token: str, is_block: bool) -> tuple[float, float, bool]:
        """Resolve one token, honouring a trailing x as "play this silently".

        The literal text is tried first, so a bar genuinely labelled "D51x"
        wins over a silent "D51".
        """
        lookup = self.block if is_block else self.address

        if found := lookup(token):
            return found[0], found[1], False

        if token.strip().lower().endswith("x"):
            if found := lookup(token.strip()[:-1]):
                return found[0], found[1], True

        brackets = "{%s}" if is_block else "[%s]"
        raise click.ClickException(
            f"{brackets % token}: no such "
            + ("text block" if is_block else "bar or beat")
            + "."
        )

    def parse_pattern(self, pattern: str, name: str) -> list[tuple[float, float, bool]]:
        """Turn "[1][1][1]{JOHN-3}" into a list of spans to play."""
        spans = []
        position = 0

        for match in TOKEN_PATTERN.finditer(pattern):
            if gap := pattern[position:match.start()].strip():
                raise click.ClickException(
                    f"{name}: {gap!r} is outside any [] or {{}}."
                )
            position = match.end()

            square, curly = match.groups()
            token = square if square is not None else curly
            if not token.strip():
                raise click.ClickException(f"{name}: empty address in the pattern.")

            start, end, is_silent = self.span(token, is_block=square is None)
            if end <= start + EPSILON:
                raise click.ClickException(
                    f"{name}: {match.group(0)} ends at {end:.3f}s, which is not "
                    f"after its start at {start:.3f}s."
                )
            spans.append((start, end, is_silent))

        if gap := pattern[position:].strip():
            raise click.ClickException(f"{name}: {gap!r} is outside any [] or {{}}.")

        if not spans:
            raise click.ClickException(f"{name}: markers may not be empty.")

        return spans


def report(score: Score) -> None:
    """Print what was found, warning about bars with an odd number of beats."""
    click.echo(
        f"Bars: {len(score.bars)} ({' '.join(bar.name for bar in score.bars)})"
    )
    if score.end_marker:
        click.echo(f"{score.end_marker} closes the last bar and is not played.")
    if score.textblocks:
        click.echo(
            f"Text blocks: {' '.join(block.name for block in score.textblocks)}"
        )

    counts = Counter(len(bar.beats) for bar in score.bars)
    expected, _ = counts.most_common(1)[0]

    for bar in score.bars:
        if len(bar.beats) == expected:
            continue

        click.echo(f"!  {bar.name} has {len(bar.beats)} beats, expected {expected}")
        click.echo(
            "   beats at " + " ".join(f"{beat.raw:.3f}" for beat in bar.beats)
        )

        raw = [beat.raw for beat in bar.beats]
        gaps = [(b - a, b) for a, b in zip(raw, raw[1:])]
        if gaps and len(bar.beats) > expected:
            gap, beat = min(gaps)
            click.echo(f"   ({beat:.3f} is {gap:.2f}s after the previous beat)")


def read_pattern(section: dict, name: str) -> tuple[str, str, str]:
    """Pick the one of sequence/bars/beats/markers a section uses."""
    modes = [mode for mode in MODES if mode in section]

    if not modes:
        raise click.ClickException(f"{name}: needs one of {', '.join(MODES)}.")
    if len(modes) > 1:
        raise click.ClickException(
            f"{name}: {' and '.join(modes)} cannot be combined, pick one."
        )

    mode = modes[0]
    written = str(section[mode]).strip()
    pattern = "".join(written.split())  # spaces are only there to group

    if not pattern:
        raise click.ClickException(f"{name}: {mode} may not be empty.")

    if mode != "markers":
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

A section plays a pattern, "repeat" times. Four kinds of pattern exist,
and a section uses exactly one of them.

Three of them are a grid, one character per unit of audio, where 1 plays
the unit and x replaces it with silence of the same length:

    sequence:   a unit is the whole snippet
    bars:       a unit is one bar   (needs "marker_file")
    beats:      a unit is one beat  (needs "marker_file")

The fourth, "markers", is a free run of addresses, which may be in any
order and may repeat:

    [4]         the 4th bar
    [4x]        the 4th bar, silent
    [D51]       the bar or beat labelled D51
    [1.4]       the 4th beat of the 1st bar
    [b2]        the beat labelled b2
    {JOHN}      the text block JOHN, up to the next bar or beat
    {JOHN-3}    the text block JOHN, up to the start of bar 3
    {JOHN-3.2}  ... up to the 2nd beat of bar 3
    {JOHN-b2}   ... up to whatever is labelled b2
    {JOHN-3x}   ... silent

A trailing x means silence, but a label always wins: if a bar really is
called "D51x" then [D51x] plays it.

An optional top level "root" is prepended to "snippet", "marker_file"
and "output", so that only the file names have to be typed. Paths that
are already absolute are used as they are.

An optional top level "marker_file" points at a marker export from
Transcribe!. Section and measure markers open a bar, beat markers
subdivide it, text blocks are named by their text, and the first marker
is taken to be the start of the snippet. Spaces in a pattern are
ignored, so units can be grouped for readability.

Example:

root: ~/Documents/MuseScore4/Scores/TUNES/I/I want you Back - Jacksons 5
marker_file: I Want You Back - loop 1.txt

snippet: I Want You Back - loop 1.wav
output: I Want You Back - practice 1.wav

sections:
  - name: Whole thing
    repeat: 2
    bars: "1111"

  - name: Lose the end of A4
    repeat: 1
    beats: "1111 1111 1111 11xx"

  - name: Drill bar 1, then run into bar 3
    repeat: 3
    markers: "[1][1][1] {JOHN-3}"

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

    marker_key = "marker_file" if "marker_file" in cfg else "markers"
    snippet_path = resolve(root, cfg["snippet"])
    output_path = resolve(root, cfg["output"])
    marker_path = resolve(root, cfg[marker_key]) if marker_key in cfg else None
    sections = cfg["sections"]

    if not snippet_path.is_file():
        raise click.ClickException(f"Snippet not found: {snippet_path}")
    if marker_path and not marker_path.is_file():
        raise click.ClickException(f"Marker file not found: {marker_path}")

    snippet = AudioSegment.from_file(snippet_path)
    duration = len(snippet) / 1000

    output = AudioSegment.empty()

    total_units = 0
    total_sections = len(sections)

    if str(root) != ".":
        click.echo(f"Root: {root}")
    click.echo(f"Loaded snippet: {snippet_path}")
    click.echo(f"Snippet length: {duration:.2f} s")

    score = None
    if marker_path:
        if marker_key == "markers":
            click.echo('Note: top level "markers" is now called "marker_file".')
        click.echo(f"Loaded markers: {marker_path}")
        score = Score.build(parse_markers(marker_path), duration)
        report(score)

    click.echo()

    for i, section in enumerate(sections, start=1):

        name = section.get("name", f"Section {i}")
        repeat = int(section["repeat"])
        mode, pattern, written = read_pattern(section, name)

        if mode == "sequence":
            spans = [(0.0, duration, character == "x") for character in pattern]
        else:
            if not score:
                raise click.ClickException(
                    f'{name}: {mode} needs a top level "marker_file".'
                )
            if mode == "markers":
                spans = score.parse_pattern(pattern, name)
            else:
                slices = score.bar_slices() if mode == "bars" else score.beat_slices()
                if len(pattern) != len(slices):
                    raise click.ClickException(
                        f"{name}: {mode} has {len(pattern)} characters but the "
                        f"markers define {len(slices)} {mode}."
                    )
                spans = [
                    (start, end, character == "x")
                    for character, (start, end) in zip(pattern, slices)
                ]

        click.echo(f"[{i}/{total_sections}] {name}")
        click.echo(f"    {repeat} × {written} ({mode})")

        for _ in range(repeat):
            for start, end, is_silent in spans:
                unit = snippet[int(start * 1000):int(end * 1000)]
                output += AudioSegment.silent(
                    duration=len(unit), frame_rate=snippet.frame_rate
                ) if is_silent else unit

        total_units += repeat * (len(spans) if mode != "sequence" else len(pattern))

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
