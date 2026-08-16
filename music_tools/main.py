import copy
import datetime
import re
from dataclasses import dataclass
from itertools import cycle, zip_longest
from pathlib import Path
from typing import Literal, Optional

import click
from pydub import AudioSegment

from music_tools.config import Config
from music_tools.generator import generate_output
from music_tools.markers import MarkerFile


@dataclass
class Marker:
    timestamp: float  # in seconds
    marker_type: str
    value: str
    repeats: int = 1


@dataclass
class Section:
    name: str  # e.g., "A1.1"
    start_time: float
    measures: list[float]  # start times of measures within the section


@dataclass
class Bar:
    start_time: float
    end_time: float
    bar_number: int
    repeats: int = 1
    source: int = 0


@dataclass
class BarsWindow:
    starts_section: bool
    section: str
    bars: list[Bar]


@dataclass
class Boundary:
    length: int
    name: Literal["A", "B", "C", "D"]


def parse_timestamp(timestamp_str: str) -> float:
    """Convert timestamp string to seconds."""
    time = datetime.datetime.strptime(timestamp_str, "%H:%M:%S.%f")
    return (
        time.hour * 3600 + time.minute * 60 + time.second + time.microsecond / 1000000
    )


def parse_markers(file_path: Path) -> list[Marker]:
    """Parse the marker file and return a list of Marker objects."""
    markers = []
    marker_pattern = r'^(\d{1,2}:\d{2}:\d{2}\.\d+) Marker \((.*?)\): "(.*?)"'
    textblock_pattern = r"^\d{1,2}:\d{2}:\d{2}\.\d+ Textblock \((.*?)\):"
    text_patterns = r"x(\d+)"
    repeats_buffer = 1
    text_buffer = ""
    with open(file_path, "r") as f:
        for line in f:
            match = re.match(marker_pattern, line.strip())
            if match:
                timestamp_str, marker_type, value = match.groups()
                if marker_type == "beat":
                    continue
                if text_buffer:
                    match = re.match(text_patterns, text_buffer)
                    (repeats,) = match.groups()
                    repeats_buffer = int(repeats)
                    text_buffer = ""
                timestamp = parse_timestamp(timestamp_str)
                markers.append(
                    Marker(
                        timestamp, marker_type.lower(), value.lower(), repeats_buffer
                    )
                )
            else:
                match = re.match(textblock_pattern, line.strip())
                if match:
                    text_buffer = ""
                else:
                    text_buffer += line.strip()

    return markers


type Sections = dict[str, list[list[Bar]]]


def organize_sections_with_boundaries(
    markers: list[Marker],
    boundaries: Optional[list[Boundary]] = [
        Boundary(128, "A"),
        # Boundary(8, "A"),
        # Boundary(8, "B"),
        # Boundary(8, "A"),
    ],
) -> dict[str, list[list[Bar]]]:
    """Organize markers into sections with their measures."""
    if not markers:
        return {}

    sections: Sections = {}

    last_section_end: float = markers.pop(0).timestamp
    current_boundary: Optional[Boundary] = None
    boundary_cycle = cycle(boundaries)
    current_run = []

    for marker in markers:
        if current_boundary is None:
            current_boundary = copy.deepcopy(next(boundary_cycle))
            if current_boundary.name not in sections:
                sections[current_boundary.name] = []
            bar_number = 0
            current_run = []

        current_run.append(
            Bar(last_section_end, marker.timestamp, bar_number, marker.repeats)
        )

        last_section_end = marker.timestamp
        current_boundary.length -= 1
        bar_number += 1

        if current_boundary.length == 0 or marker.value == "end":
            sections[current_boundary.name].append(current_run)
            current_boundary = None

        if marker.value == "end":
            break

    return sections


def organize_sections_with_repeats(markers: list[Marker]) -> dict[str, list[list[Bar]]]:
    """Organize markers into sections with their measures."""
    if not markers:
        return {}

    sections: Sections = {}
    boundary_name = "A"
    sections[boundary_name] = []

    last_section_end: float = markers.pop(0).timestamp
    current_run = []
    bar_number = 0

    for marker in markers:
        current_run.append(
            Bar(last_section_end, marker.timestamp, bar_number, marker.repeats)
        )

        last_section_end = marker.timestamp
        bar_number += 1

        if marker.value == "end":
            break

    sections[boundary_name].append(current_run)

    return sections


def windowize_bars(
    sections: Sections, size: int = 4, period: int = 1
) -> dict[str, list[list[BarsWindow]]]:
    """Create windows of bars for each section."""
    windows: dict[str, list[list[BarsWindow]]] = {}

    for section_name, bar_runs in sections.items():
        section_windows = []
        for bar_run in bar_runs:
            for i in range(0, len(bar_run) - size + 1, period):
                window_bars = bar_run[i : i + size]
                if i == 0:
                    starts_section = True
                    new_run = []
                new_run.append(BarsWindow(starts_section, section_name, window_bars))
            section_windows.append(new_run)
        windows[section_name] = section_windows

    return windows


def flip_windows(
    windows: dict[str, list[list[BarsWindow]]],
) -> dict[str, list[list[BarsWindow]]]:
    """Flip the order of bars in each section."""
    flipped = {}
    for section_name, section_bars in windows.items():
        flipped[section_name] = list(zip_longest(*section_bars))
    return flipped


def flatten(
    windows: dict[str, list[list[BarsWindow]]], repeats: int = 1, granular: bool = True
) -> dict[str, list[Bar]]:
    """Add repeats to the windows of bars."""

    bars: dict[str, list[Bar]] = {}

    for section_name, section_windows in windows.items():
        for i, run in enumerate(section_windows):
            if granular:
                key = f"{section_name}-{i}"
            else:
                key = section_name
            bars[key] = [] if key not in bars else bars[key]

            for window in run:
                bars[key].extend(
                    [
                        copy.deepcopy(bar)
                        for bar in (window.bars * window.bars[0].repeats)
                    ]
                )
    return bars


def create_output(
    *,
    audio: AudioSegment,
    bars: list[Bar],
    audio_silent: Optional[AudioSegment] = None,
    measures: int = 2,
    repeats: int = 8,
) -> AudioSegment:
    """Create output audio by concatenating segments with repeats."""
    output = AudioSegment.empty()

    ALWAYS_AUDIO = 3

    if not bars:
        return output

    audios = [audio]

    if audio_silent:
        audios.append(audio_silent)
        for i in range(len(bars)):
            if ((i // measures) % repeats) < ALWAYS_AUDIO:
                continue
            bars[i].source = (i // measures) % 2

    start_ms = int(bars[0].start_time * 1000)
    end_ms = int(bars[0].end_time * 1000)
    output += audios[0][start_ms:end_ms] - 34

    for bar in bars:
        # Convert times to milliseconds for pydub
        start_ms = int(bar.start_time * 1000)
        end_ms = int(bar.end_time * 1000)

        aud = audios[bar.source]

        # Extract and repeat segment
        output += aud[start_ms:end_ms]

    return output


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "-c", type=click.Path(exists=True))
def main(
    config: str,
):
    """Split and rearrange audio file based on markers."""
    job_config = Config.load(Path(config))
    markers = MarkerFile.load(job_config.source.markers)

    for file_obj in job_config.outputs.files:
        generate_output(
            file_obj=file_obj,
            markers_file=markers,
            vars=job_config.outputs.vars,
            sources=job_config.source,
        )
    exit()


if __name__ == "__main__":
    main()
