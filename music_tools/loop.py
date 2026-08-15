"""
Generate a rhythm-training loop by repeating an audio snippet and replacing
selected repetitions, bars, beats or marked spans with silence.

Example:

    uv run loop trainer.yml
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

MARKER_PATTERN = re.compile(r'^(\d{1,2}:\d{2}:\d{2}\.\d+) Marker \((.*?)\): "(.*?)"')
# the word in brackets is the colour of the block, its text is on the
# lines that follow, up to a blank line or the next timestamp
TEXTBLOCK_PATTERN = re.compile(r"^(\d{1,2}:\d{2}:\d{2}\.\d+) Textblock \((.*?)\):")
TIMESTAMPED = re.compile(r"^\d{1,2}:\d{2}:\d{2}\.\d+ ")

# the one reserved name, so that a span can always reach the end of the score
SCORE_END = "end"

# a pattern is a run of [address] or [address-address] spans. Curly brackets
# are deliberately not part of the syntax, so that they stay free for
# templating later on
TOKEN_PATTERN = re.compile(r"\[([^\[\]]*)\]")

# the marker types Transcribe! uses to open a new bar
BAR_TYPES = {"section", "measure"}

# and the ones that subdivide the bar they are in. "auto" is what Transcribe!
# writes for beats it worked out itself rather than ones tapped in by hand,
# and anything containing "beat" covers plain "beat" as well as "t beat"
BEAT_TYPES = {"beat", "auto"}

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


def modal_beats(bars: "list[Bar]") -> int:
    """The beats-per-bar to judge the other bars by.

    A tie goes to the longer count, because the bars that differ are the
    ones cut short: a loop of 2+4+4+2 is two full bars between two partial
    ones, not two odd bars between two right ones.
    """
    counts = Counter(len(bar.beats) for bar in bars)
    return max(counts, key=lambda beats: (counts[beats], beats))


def first_wins(pairs) -> dict:
    """Build a dict in which the earliest of any repeated key survives."""
    names: dict = {}
    for key, value in pairs:
        names.setdefault(key, value)
    return names


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

    def __init__(
        self,
        bars: list[Bar],
        textblocks: list[TextBlock],
        duration: float,
        end_marker: str | None = None,
        ignored: "Counter[str] | None" = None,
    ):
        self.bars = bars
        self.textblocks = textblocks
        self.duration = duration  # of the score, which may stop short of the audio
        self.end_marker = end_marker
        self.ignored = ignored if ignored is not None else Counter()

        # A snippet cut from a recording usually starts on an upbeat, giving a
        # short first bar. That is an anacrusis, not a bar of its own, so it is
        # numbered 0 the way MuseScore numbers a pickup measure, and [1] stays
        # the first full bar. Its length is judged against the bars after it,
        # since the last bar is just as likely to be partial
        self.pickup = len(bars) > 1 and len(bars[0].beats) < modal_beats(bars[1:])
        self.numbered_from = 0 if self.pickup else 1

        self.beats = [beat for bar in bars for beat in bar.beats]

        # every name is one point in time. The end marker is the weakest, then
        # text blocks, then beats, then bars, and within a kind the earliest
        # wins. So a bar called "3" is bar 3, not the third bar
        named = {
            **({end_marker.lower(): duration} if end_marker else {}),
            **first_wins((block.name.lower(), block.start) for block in textblocks),
            **first_wins(
                (beat.label.lower(), beat.start) for beat in self.beats if beat.label
            ),
            **first_wins((bar.name.lower(), bar.start) for bar in bars),
        }

        # END is reserved, so that a span can reach the end of any score. No
        # marker can shadow it: one labelled "end" is consumed by build, which
        # truncates the score there, and so names this very point anyway
        self.by_name: dict[str, float] = {**named, SCORE_END: duration}

    @classmethod
    def build(cls, entries: list[tuple[float, str, str]], duration: float) -> "Score":
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
        ignored: Counter[str] = Counter()
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

            if kind in BEAT_TYPES or "beat" in kind:
                if bars:
                    bars[-1].beats.append(Beat(label, start, raw=timestamp))
                continue

            if kind not in BAR_TYPES:
                ignored[kind] += 1
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

        return cls(
            bars, textblocks, end, end_marker.name if end_marker else None, ignored
        )

    def bar_slices(self) -> list[tuple[float, float]]:
        """Start and end of every bar."""
        return [(bar.start, bar.end) for bar in self.bars]

    def beat_slices(self) -> list[tuple[float, float]]:
        """Start and end of every beat, across all bars."""
        return [(beat.start, beat.end) for bar in self.bars for beat in bar.beats]

    def address(self, text: str) -> float | None:
        """Resolve 4, D51, 1.4, b2 or JOHN to one point in the score."""
        key = text.strip().lower()

        if key in self.by_name:
            return self.by_name[key]

        if match := BAR_INDEX.match(key):
            index = int(match.group(1)) - self.numbered_from
            if 0 <= index < len(self.bars):
                return self.bars[index].start
            return None

        if match := BEAT_INDEX.match(key):
            bar_index = int(match.group(1)) - self.numbered_from
            beat_index = int(match.group(2)) - 1
            if 0 <= bar_index < len(self.bars):
                beats = self.bars[bar_index].beats
                if 0 <= beat_index < len(beats):
                    return beats[beat_index].start
        return None

    def resolve(self, text: str) -> tuple[float, float | None] | None:
        """Resolve FROM or FROM-TO to a start, and an end if one is given.

        An end is exclusive: it is the start of whatever it names, so
        [1-3] stops where bar 3 begins. A span with no end of its own is
        left open here, for parse_pattern to close against its neighbour.
        """
        if (start := self.address(text)) is not None:
            return start, None

        if "-" in text:
            before, _, after = text.strip().rpartition("-")
            start, end = self.address(before), self.address(after)
            if start is not None and end is not None:
                return start, end
        return None

    def span(self, token: str) -> tuple[float, float | None, bool]:
        """Resolve one token, honouring a trailing x as "play this silently".

        The literal text is tried first, so a bar genuinely labelled "D51x"
        wins over a silent "D51".
        """
        if found := self.resolve(token):
            return found[0], found[1], False

        if token.strip().lower().endswith("x"):
            if found := self.resolve(token.strip()[:-1]):
                return found[0], found[1], True

        raise click.ClickException(
            f"[{token}]: no such bar, beat or text block: {self.missing(token)}"
        )

    def missing(self, token: str) -> str:
        """Name the parts of a token that do not resolve, for the error."""
        candidate = token.strip()
        if candidate.lower().endswith("x") and self.address(candidate) is None:
            candidate = candidate[:-1]

        names = [candidate]
        if "-" in candidate:
            before, _, after = candidate.rpartition("-")
            names = [before, after]

        return ", ".join(name.strip() for name in names if self.address(name) is None)

    def parse_pattern(self, pattern: str, name: str) -> list[tuple[float, float, bool]]:
        """Turn "[1.1][UP1][UP2]" into a list of spans to play.

        Two passes, because a span with no end of its own is closed by
        wherever the next one starts, and the last one by the end of the
        snippet.
        """
        opened = []
        position = 0

        def outside(text: str) -> None:
            if "{" in text or "}" in text:
                raise click.ClickException(
                    f"{name}: {text!r} uses curly brackets; spans are written "
                    "in square ones, as [JOHN-3]."
                )
            raise click.ClickException(f"{name}: {text!r} is outside any [].")

        for match in TOKEN_PATTERN.finditer(pattern):
            if gap := pattern[position : match.start()].strip():
                outside(gap)
            position = match.end()

            token = match.group(1)
            if not token.strip():
                raise click.ClickException(f"{name}: empty address in the pattern.")

            opened.append((*self.span(token), match.group(0)))

        if gap := pattern[position:].strip():
            outside(gap)

        if not opened:
            raise click.ClickException(f"{name}: markers may not be empty.")

        spans = []
        for index, (start, end, is_silent, shown) in enumerate(opened):
            given = end is not None
            after = opened[index + 1] if index + 1 < len(opened) else None
            if not given:
                end = after[0] if after else self.duration

            if end <= start + EPSILON:
                raise click.ClickException(
                    f"{name}: {self.backwards(shown, start, end, given, after)}"
                )
            spans.append((start, end, is_silent))

        return spans

    def backwards(self, shown, start, end, given, after) -> str:
        """Explain a span that does not move forwards.

        Which of the three it is matters, because the fix differs: correct
        the end, reorder the pattern, or drop the span.
        """
        if given:
            return (
                f"{shown} ends at {end:.3f}s, which is not after its start "
                f"at {start:.3f}s."
            )
        if after:
            return (
                f"{shown} starts at {start:.3f}s but the next span {after[3]} "
                f"starts at {end:.3f}s, so {shown} has nowhere to run. Put the "
                f"spans in time order, or give {shown} an end of its own."
            )
        return (
            f"{shown} starts at {start:.3f}s, which is already the end of the "
            "snippet, so there is nothing left to play."
        )


def report(score: Score) -> None:
    """Print what was found, warning about bars with an odd number of beats."""
    click.echo(f"Bars: {len(score.bars)} ({' '.join(bar.name for bar in score.bars)})")
    if score.end_marker:
        click.echo(
            f"{score.end_marker} closes the last bar. It is not played, but a "
            f"span may end on it, as [{score.bars[-1].name}-{score.end_marker}]."
        )
    if score.textblocks:
        click.echo(f"Text blocks: {' '.join(block.name for block in score.textblocks)}")
    if score.ignored:
        kinds = ", ".join(
            f"{count} × {kind}" for kind, count in sorted(score.ignored.items())
        )
        click.echo(
            f"!  Ignored {kinds}: not a bar or a beat. If those are beats, the "
            "bar lengths below will be wrong."
        )

    if score.pickup:
        click.echo(
            f"{score.bars[0].name} is a {len(score.bars[0].beats)}-beat pickup, "
            f"so it is [0] and the first full bar is [1] ({score.bars[1].name})."
        )

    expected = modal_beats(score.bars)

    # A snippet cut from a recording is expected to be partial at its edges,
    # where a short bar means the cut fell mid-phrase rather than that the
    # markers are wrong. Only a short bar in the middle is worth a warning
    for bar in score.bars[1:-1]:
        if len(bar.beats) == expected:
            continue

        click.echo(f"!  {bar.name} has {len(bar.beats)} beats, expected {expected}")
        click.echo("   beats at " + " ".join(f"{beat.raw:.3f}" for beat in bar.beats))

        raw = [beat.raw for beat in bar.beats]
        gaps = [(b - a, b) for a, b in zip(raw, raw[1:])]
        if gaps and len(bar.beats) > expected:
            gap, beat = min(gaps)
            click.echo(f"   ({beat:.3f} is {gap:.2f}s after the previous beat)")


def describe(score: Score) -> list[str]:
    """The marker file written out as the addresses a pattern can use.

    Every failure so far has come down to a mismatch between what the
    markers say and what the pattern assumed, so the useful thing to show
    is not the file but the score it was read as.
    """
    lines = []
    for index, bar in enumerate(score.bars):
        number = index + score.numbered_from
        note = "   (pickup)" if score.pickup and index == 0 else ""
        lines.append(
            f"    [{number}] {bar.name}   {bar.start:.3f} - {bar.end:.3f}{note}"
        )
        # a bar's opening beat carries the bar's own label, which is already
        # on the line above, so only a beat labelled in its own right is shown
        lines.append(
            "        "
            + "  ".join(
                f"[{number}.{n}] {beat.start:.3f}"
                + (f" ={beat.label}" if beat.label and n > 1 else "")
                for n, beat in enumerate(bar.beats, 1)
            )
        )
        lines.extend(
            f"        [{block.name}] {block.start:.3f}"
            for block in score.textblocks
            if bar.start <= block.start < bar.end
        )

    closing = f"[{score.end_marker}] " if score.end_marker else ""
    lines.append(f"    {closing}[END]   {score.duration:.3f}")
    return lines


def diagnose(marker_path: "Path | None", score: "Score | None", section) -> None:
    """After a failure, show the instruction that failed and the markers."""
    if section is not None:
        click.echo("\nThe section that failed, as written:")
        for line in yaml.safe_dump(section, sort_keys=False).strip().splitlines():
            click.echo(f"    {line}")

    if score is not None:
        click.echo(f"\nMarkers: {marker_path}, as read:")
        for line in describe(score):
            click.echo(line)


def step_each(count: int, keep: int) -> list[frozenset]:
    """One region at a time."""
    return [frozenset([i]) for i in range(keep, count)]


def step_widen(count: int, keep: int) -> list[frozenset]:
    """A window that slides along, widens by one, and slides again."""
    return [
        frozenset(range(start, start + width))
        for width in range(1, count - keep + 1)
        for start in range(keep, count - width + 1)
    ]


def step_head(count: int, keep: int) -> list[frozenset]:
    """A growing head, so the phrase starts later and later."""
    return [frozenset(range(keep, keep + w)) for w in range(1, count - keep + 1)]


def step_tail(count: int, keep: int) -> list[frozenset]:
    """A growing tail, so the phrase is cut shorter and shorter."""
    return [frozenset(range(count - w, count)) for w in range(1, count - keep + 1)]


def step_build(count: int, keep: int) -> list[frozenset]:
    """A shrinking tail, so the phrase grows a region at a time."""
    return list(reversed(step_tail(count, keep)))


def step_solo(count: int, keep: int) -> list[frozenset]:
    """Each region in turn as the only one still sounding.

    This one ignores keep: holding a region back is the opposite of what
    it is for.
    """
    return [frozenset(i for i in range(count) if i != alone) for alone in range(count)]


DRILL_STEPS = {
    "each": step_each,
    "widen": step_widen,
    "head": step_head,
    "tail": step_tail,
    "build": step_build,
    "solo": step_solo,
}


def drill_sets(count: int, keep: int, steps: list[str], name: str) -> list[frozenset]:
    """Which regions to silence, in order, running the steps back to back.

    Steps overlap by design -- widen ends where solo begins, each is the
    first pass of widen -- so a set already reached is not repeated.
    """
    silenced = []
    for step in steps:
        if step not in DRILL_STEPS:
            raise click.ClickException(
                f"{name}: no such drill step {step!r}. "
                f"Pick from {', '.join(sorted(DRILL_STEPS))}."
            )
        silenced.extend(DRILL_STEPS[step](count, keep))

    seen, unique = set(), []
    for quiet in silenced:
        if quiet and quiet not in seen:
            seen.add(quiet)
            unique.append(quiet)
    return unique


def close_spans(tokens: list[str]) -> list[str]:
    """Give every bare region an end of its own, so the run can come round.

    A bare span is closed by whatever follows it, which stops working the
    moment the regions repeat: the last region would be closed by the
    first and run backwards. Naming the end that was implied anyway lets
    a region mean the same thing wherever it lands in the cycle.
    """
    closed = []
    for i, token in enumerate(tokens):
        if "-" in token:  # already ends somewhere of its own
            closed.append(token)
            continue
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        closed.append(
            f"{token}-{SCORE_END.upper()}"
            if following is None
            else f"{token}-{following.split('-')[0].strip()}"
        )
    return closed


def expand_drill(section: dict, name: str) -> list[dict]:
    """Turn one drill into the plain sections it stands for.

    Textual, and deliberately so: it needs no score, so --expand works on
    a config whose audio is not to hand, and what it prints can be pasted
    back in place of the drill and hand-edited from there.
    """
    tokens = [
        match.group(1).strip() for match in TOKEN_PATTERN.finditer(section["drill"])
    ]
    if len(tokens) < 2:
        raise click.ClickException(
            f"{name}: a drill needs at least two regions, as "
            '"[START][M1.1][M2.1][M3.1-END]".'
        )

    # a cycle longer than one pass keeps the phrase turning while a hole
    # moves through it, so the silence is heard in time rather than as a gap
    cycle = int(section.get("cycle", 1))
    if cycle < 1:
        raise click.ClickException(
            f"{name}: cycle is {cycle}, but a drill needs at least one pass."
        )
    if cycle > 1:
        tokens = close_spans(tokens) * cycle

    keep = int(section.get("keep", 1))
    if not 0 <= keep < len(tokens):
        raise click.ClickException(
            f"{name}: keep is {keep}, but there are only {len(tokens)} regions "
            "and at least one has to be left to silence."
        )

    repeat = int(section.get("repeat", 1))
    reference = int(section.get("reference", 1))
    plain = "".join(f"[{token}]" for token in tokens)

    wanted = section.get("steps", ["widen", "solo"])
    if isinstance(wanted, str):
        wanted = [wanted]

    sections = []
    steps = drill_sets(len(tokens), keep, wanted, name)
    for step, quiet in enumerate(steps, start=1):
        if reference:
            sections.append(
                {
                    "name": f"{name} {step}/{len(steps)}: all",
                    "repeat": reference,
                    "markers": plain,
                }
            )
        without = " ".join(
            f"{tokens[i]}#{i + 1}" if cycle > 1 else tokens[i] for i in sorted(quiet)
        )
        sections.append(
            {
                "name": f"{name} {step}/{len(steps)}: without {without}",
                "repeat": repeat,
                "markers": "".join(
                    f"[{token}x]" if i in quiet else f"[{token}]"
                    for i, token in enumerate(tokens)
                ),
            }
        )
    return sections


def expand_sections(sections: list) -> list:
    """Replace every drill with the sections it stands for."""
    expanded = []
    for i, section in enumerate(sections, start=1):
        if isinstance(section, dict) and "drill" in section:
            expanded.extend(expand_drill(section, section.get("name", f"Section {i}")))
        else:
            expanded.append(section)
    return expanded


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

The fourth, "markers", is a run of spans in square brackets. A span says
where it starts, and any of these will do:

    [4]         the 4th bar             [D51]  the bar or beat labelled D51
    [1.4]       bar 1, beat 4           [b2]   the beat labelled b2
    [JOHN]      the text block JOHN

After a dash it may also say where it ends, mixing the forms freely:

    [1-3]       from bar 1 up to the start of bar 3
    [1.4-3]     from the 4th beat of bar 1 up to bar 3
    [JOHN-3.2]  from JOHN up to the 2nd beat of bar 3
    [1.1-JOHN]  from the top of the snippet up to JOHN
    [1-3x]      bars 1 and 2, silent

An end is exclusive: it is the start of whatever it names, so [1-3]
stops where bar 3 begins.

A snippet cut from a recording usually starts on an upbeat. Where the
first bar is shorter than the ones after it, it is taken for a pickup
and numbered 0, the way MuseScore numbers a pickup measure, so [1] is
still the first full bar and [0-1] is the pickup on its own. The markers
must cover that upbeat: the score is lined up on the first marker, so
audio before it cannot be reached and shifts everything if included.

Given no end, a span runs to wherever the next span in the pattern
starts, or to the end of the snippet if nothing follows it. That is what
lets a pattern chop a snippet into consecutive pieces:

    [1.1][UP1][UP2]   the top up to UP1, UP1 up to UP2, UP2 to the end

Because a bare span ends where the next one starts, repeating or
reordering needs explicit ends: [1][1] is two empty spans, while
[1-2][1-2] is bar 1 played twice.

END is reserved and always means the end of the snippet, so a span can
reach the end without being written last: [4-END] is the 4th bar in
full, wherever it appears in the pattern.

Two things in a marker file name that same point, so all three agree.
A marker labelled "end" stops the score there, and everything after it
is ignored. And markers exported by dropping one on every barline finish
with a bar marker that has no beats under it, which closes the passage
rather than opening a bar: it is never played, but given bars 92 and 93,
[92-93] and [92-END] are the same span.

A trailing x means silence, but a label always wins: if a bar really is
called "D51x" then [D51x] plays it.

A section may instead hold a "drill", which is a markers pattern that
stands for a whole run of sections silencing its regions in turn:

  - name: heaven
    drill: "[START][M1.1][M2.1][M3.1-END]"
    steps: [widen, solo]   # which drills to run, in order
    reference: 1           # repeats of the plain pattern, before each step
    repeat: 3              # repeats of each silenced pattern
    keep: 1                # leading regions the window leaves alone
    cycle: 1               # how many passes of the regions make one pattern

Taking [A][B][C][D] with keep 1, the steps are:

    each    one region at a time, so Bx, then Cx, then Dx
    head    a growing head: Bx, then BxCx, then BxCxDx
    tail    a growing tail: Dx, then CxDx, then BxCxDx
    build   a shrinking tail, so the phrase grows back a region at a time
    widen   a window that slides, widens by one, and slides again
    solo    each region in turn as the only one still sounding

Steps run back to back in the order given, and a silencing already
reached is not repeated -- "each" is "widen" at its first width, and
"widen" ends where "solo" begins. keep holds the leading regions while a
window moves through the rest; "solo" ignores it, since holding a region
back is the opposite of what it is for. With keep 0 a window can reach
every region, so [tail] ends on total silence, to be played to nothing.

A cycle above one lays the regions down that many times over and drills
the whole run, so the phrase keeps turning while a hole moves through
it. With cycle 2, [1][2][3][4] and step "each" gives

    [1][2x][3][4] [1][2][3][4]
    [1][2][3x][4] [1][2][3][4]
    ...
    [1][2][3][4] [1][2][3][4x]

which is heard in time rather than as a gap. A bare region is closed by
whatever follows it, so cycling first gives every region an end of its
own -- otherwise the last would be closed by the first and run
backwards. Regions repeat, so a step is named by its place in the cycle.

Run with --expand to print the sections a drill stands for and stop;
paste them back in its place to hand-edit from there.

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
    markers: "[1-2][1-2][1-2] [JOHN-3]"

Usage:

    uv run loop trainer.yml
""",
)
@click.argument(
    "config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--expand",
    is_flag=True,
    help="Print the sections a drill stands for, and stop. Paste them back "
    "in its place to hand-edit from there.",
)
def main(config: Path, expand: bool):

    with config.open() as f:
        cfg = yaml.safe_load(f)

    cfg["sections"] = expand_sections(cfg["sections"])

    if expand:
        click.echo(yaml.safe_dump({"sections": cfg["sections"]}, sort_keys=False))
        return

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
        try:
            score = Score.build(parse_markers(marker_path), duration)
        except click.ClickException:
            # no score to render it as, so the file itself is all there is
            click.echo(f"\nMarkers: {marker_path}, as written:")
            for line in marker_path.read_text().splitlines():
                click.echo(f"    {line}")
            raise
        report(score)

    click.echo()

    section = None
    try:
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
                    slices = (
                        score.bar_slices() if mode == "bars" else score.beat_slices()
                    )
                    if len(pattern) != len(slices):
                        shape = (
                            " ".join(bar.name for bar in score.bars)
                            if mode == "bars"
                            else "+".join(str(len(bar.beats)) for bar in score.bars)
                        )
                        raise click.ClickException(
                            f"{name}: {mode} has {len(pattern)} characters but the "
                            f"markers define {len(slices)} {mode} ({shape})."
                        )
                    spans = [
                        (start, end, character == "x")
                        for character, (start, end) in zip(pattern, slices)
                    ]

            click.echo(f"[{i}/{total_sections}] {name}")
            click.echo(f"    {repeat} × {written} ({mode})")

            for _ in range(repeat):
                for start, end, is_silent in spans:
                    unit = snippet[int(start * 1000) : int(end * 1000)]
                    output += (
                        AudioSegment.silent(
                            duration=len(unit), frame_rate=snippet.frame_rate
                        )
                        if is_silent
                        else unit
                    )

            total_units += repeat * (len(spans) if mode != "sequence" else len(pattern))
    except click.ClickException:
        diagnose(marker_path, score, section)
        raise

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.export(output_path)

    click.echo()
    click.echo("Done.")
    click.echo(f"Output : {output_path}")
    click.echo(f"Units  : {total_units}")
    click.echo(f"Length : {len(output) / 1000:.1f} seconds")

    subprocess.run(
        [
            "/Applications/Transcribe!.app/Contents/MacOS/Transcribe!",
            output_path,
        ]
    )


if __name__ == "__main__":
    main()
