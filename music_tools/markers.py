import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


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


@dataclass
class Measure:
    section_index: int
    absolute_index: int
    end_time: float
    start_time: float
    label: str = "--"
    section: Optional[str] = None


def parse_timestamp(timestamp_str: str) -> float:
    """Convert timestamp string to seconds."""
    time = datetime.strptime(timestamp_str, "%H:%M:%S.%f")
    as_float = (
        time.hour * 3600 + time.minute * 60 + time.second + time.microsecond / 1000000
    )
    return as_float


class MarkerFile:
    """Manages loading and parsing of marker files."""

    sections: list[Any] = []
    measures: list[Any] = []
    _raw_markers: list[Marker] = []

    def __init__(
        self,
        sections: list[Section] = [],
        measures: list[Measure] = [],
        _raw_markers: list[Marker] = [],
    ):
        self.sections = sections
        self.measures = measures
        self._raw_markers = _raw_markers

    def get_sections_matching(self, matching: str) -> list[Section]:
        """Get sections matching a specific regex."""
        regex = re.compile(matching, re.IGNORECASE)
        return [section for section in self.sections if re.match(regex, section.name)]

    def get_timestamps_for_section(
        self,
        *,
        section: Section,
        first_start: int = 0,
        last_start: Optional[int] = sys.maxsize,
        window: int = 1,
    ) -> list[tuple[float, float]]:
        """Get measures for a specific section."""

        if last_start is None:
            last_start = sys.maxsize
        timestamps: list[tuple[float, float]] = []

        for i, measure in enumerate(self.measures):
            if (
                measure.section != section.name
                or measure.section_index < first_start
                or measure.section_index > last_start
            ):
                continue

            start_time = measure.start_time
            if i == len(self.measures) - 1:
                end_time = measure.end_time
                for j in range(window):
                    timestamps.append((start_time, end_time))
            elif i + window >= len(self.measures):
                end_time = self.measures[-1].end_time
                timestamps.append((start_time, end_time))
                for j in range(window - len(self.measures) + i):
                    timestamps.append(
                        (self.measures[-1].start_time, self.measures[-1].end_time)
                    )
            else:
                end_time = self.measures[i + window - 1].end_time
                timestamps.append((start_time, end_time))

        return timestamps

    @classmethod
    def load(cls, file_path: Path) -> "MarkerFile":
        """Load the marker file and parse it."""
        marker_pattern = r'^(\d{1,2}:\d{2}:\d{2}\.\d+) Marker \((.*?)\): "(.*?)"'
        textblock_pattern = r"^\d{1,2}:\d{2}:\d{2}\.\d+ Textblock \((.*?)\):"
        text_patterns = r"x(\d+)"
        repeats_buffer = 1
        text_buffer = ""
        current_section = None
        section_index = 0
        absolute_index = 0

        _raw_markers: list[Marker] = []
        sections: list[Section] = []
        measures: list[Measure] = []

        final_start_time = 0.0

        with open(file_path, "r") as f:
            for line in f:
                line = line.strip(" \n")
                if not line:
                    continue

                _raw_markers.append(line)

                match = re.match(marker_pattern, line)
                if match:
                    timestamp_str, marker_type, value = match.groups()
                    marker_type = marker_type.lower()
                    value = value.lower()

                    if value.lower() == "end":
                        final_start_time = parse_timestamp(timestamp_str)
                        break

                    # for now we ignore beats
                    if marker_type == "beat":
                        continue

                    # handles textblock markers; this is legacy and
                    # for now ignored
                    if text_buffer:
                        match = re.match(text_patterns, text_buffer)
                        try:
                            (repeats,) = match.groups()
                            repeats_buffer = int(repeats)
                        except Exception:
                            logger.warning(
                                f"Failed to parse repeats from {text_buffer}"
                            )
                            continue
                        text_buffer = ""
                        continue

                    assert marker_type in ["section", "measure"]

                    timestamp = parse_timestamp(timestamp_str)
                    _raw_markers.append(
                        Marker(timestamp, marker_type, value, repeats_buffer)
                    )

                    if marker_type == "section":
                        current_section = value
                        section = Section(
                            name=value.lower(),
                            start_time=timestamp,
                        )
                        sections.append(section)
                        section_index = 1

                    measure = Measure(
                        label=value,
                        start_time=timestamp,
                        end_time=timestamp,
                        section_index=section_index,
                        absolute_index=absolute_index,
                        section=current_section,
                    )
                    measures.append(measure)

                    section_index += 1
                    absolute_index += 1

                else:
                    # we are in a textblock, which can be multiline and freeform
                    match = re.match(textblock_pattern, line)
                    if match:
                        text_buffer = ""
                    else:
                        text_buffer += " " + line

        for i in range(len(measures) - 1, -1, -1):
            measures[i].end_time = final_start_time
            final_start_time = measures[i].start_time

        return cls(sections=sections, measures=measures, _raw_markers=_raw_markers)
