import copy
import datetime
import re
from dataclasses import dataclass
from itertools import cycle, zip_longest
from pathlib import Path
from typing import Literal, Optional

import click
from pydub import AudioSegment


@dataclass
class Marker:
    timestamp: float  # in seconds
    marker_type: str
    value: str


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
    pattern = r'(\d{1,2}:\d{2}:\d{2}\.\d+) Marker \((.*?)\): "(.*?)"'

    with open(file_path, "r") as f:
        for line in f:
            match = re.match(pattern, line.strip())
            if match:
                timestamp_str, marker_type, value = match.groups()
                if marker_type == "beat":
                    continue
                timestamp = parse_timestamp(timestamp_str)
                markers.append(Marker(timestamp, marker_type.lower(), value.lower()))

    return markers


type Sections = dict[str, list[list[Bar]]]


def organize_sections(
    markers: list[Marker],
    boundaries: list[Boundary] = [
        Boundary(8, "A"),
        Boundary(8, "A"),
        Boundary(8, "B"),
        Boundary(8, "A"),
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

        current_run.append(Bar(last_section_end, marker.timestamp, bar_number))

        last_section_end = marker.timestamp
        current_boundary.length -= 1
        bar_number += 1

        if current_boundary.length == 0 or marker.value == "end":
            sections[current_boundary.name].append(current_run)
            current_boundary = None

        if marker.value == "end":
            break

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
        flipped[section_name] = zip_longest(*section_bars)
    return flipped


def flatten(windows: dict[str, list[list[BarsWindow]]], repeats: int = 1) -> list[Bar]:
    """Add repeats to the windows of bars."""
    bars: dict[str, list[Bar]] = {}
    for section_name, section_windows in windows.items():
        bars[section_name] = []
        for run in section_windows:
            for window in run:
                bars[section_name].extend([bar for bar in (window.bars * repeats)])
    return bars


def create_output(audio: AudioSegment, bars: list[Bar]) -> AudioSegment:
    """Create output audio by concatenating segments with repeats."""
    output = AudioSegment.empty()

    for bar in bars:
        # Convert times to milliseconds for pydub
        start_ms = int(bar.start_time * 1000)
        end_ms = int(bar.end_time * 1000)

        # Extract and repeat segment
        output += audio[start_ms:end_ms]

    return output


@click.command()
@click.argument("audio_file", type=click.Path(exists=True))
@click.option("--marker-file", type=click.Path(exists=True), required=True)
@click.option("--measures", default=2, help="Number of measures per segment")
@click.option("--repeats", default=4, help="Number of times to repeat each segment")
@click.option(
    "--flip/--no-flip",
    default=True,
    help="Whether to go through all 1st bars, then all seconds, etc",
)
def main(audio_file: str, marker_file: str, measures: int, repeats: int, flip: bool):
    """Split and rearrange audio file based on markers."""
    # Load audio file
    audio = AudioSegment.from_file(audio_file)

    # Get marker file path (same name as audio file but with .txt extension)
    marker_file = Path(marker_file)
    if not marker_file.exists():
        click.echo(f"Error: Marker file {marker_file} not found", err=True)
        return

    # Parse markers and organize sections
    global markers
    markers = parse_markers(marker_file)
    sections = organize_sections(markers)
    windows = windowize_bars(sections, size=measures, period=measures)

    if flip:
        windows = flip_windows(windows)

    flattened = flatten(windows, repeats)

    # Create output files
    for section_name, bars in flattened.items():
        output = create_output(audio, bars)
        output_file = Path(audio_file).with_stem(
            f"{Path(audio_file).stem}_{section_name}_output"
        )
        output.export(output_file, format=output_file.suffix[1:])
        click.echo(f"Created {output_file}")


if __name__ == "__main__":
    main()
