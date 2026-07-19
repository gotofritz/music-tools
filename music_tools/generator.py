import logging
from typing import Any

import click
from pydub import AudioSegment

from music_tools.config import OutputFile, Source
from music_tools.markers import MarkerFile

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)
# Set specific logging levels for third-party libraries
logging.getLogger("pydub").setLevel(logging.WARNING)


def replace_with_var(
    *,
    maybe_str: str,
    vars: dict[str, Any],
    default: Any = None,
) -> str:
    if isinstance(maybe_str, str) and maybe_str.startswith("$"):
        return vars.get(maybe_str[1:], default)
    return maybe_str


def generate_output(
    *,
    file_obj: OutputFile,
    sources: Source,
    markers_file: MarkerFile,
    vars: dict[str, Any] = {},
) -> None:
    """Generate sounds files"""

    # load audio files
    source_audio = {k: AudioSegment.from_file(v) for k, v in sources.audio.items()}

    output_audio = AudioSegment.empty()
    needs_intro = True

    click.echo(
        f"file [NEW FILE]: {sources.with_root(file_obj.destination)} ----------------------------"
    )

    for step in file_obj.steps:
        # extract raw material
        if trigger_node := step.get("trigger"):
            if each_node := trigger_node.get("each"):
                if section_node := each_node.get("section"):
                    if matching_node := section_node.get("matching"):
                        if each_sub_node := section_node.get("each"):
                            if measure_node := each_sub_node.get("measure"):
                                if isinstance(measure_node, dict):
                                    first_start = measure_node.get("first_start", 0)
                                    last_start = measure_node.get("last_start", None)
                                    window = measure_node.get("window", 1)
                                    window = int(
                                        replace_with_var(
                                            maybe_str=window,
                                            vars=vars,
                                            default=1,
                                        )
                                    )
                                else:
                                    first_start = 0
                                    last_start = None
                                    window = 1
        # extract instructions
        output_node = step.get("output", [])
        output_instructions = []
        for output_instruction in output_node:
            if copy_node := output_instruction.get("copy"):
                if copy_node["repeats"]:
                    copy_node["repeats"] = replace_with_var(
                        maybe_str=copy_node["repeats"],
                        vars=vars,
                    )
                    output_instructions.append(copy_node)

        # apply instructions to raw material and generate output
        sections = markers_file.get_sections_matching(matching_node)
        for section in sections:
            logger.debug(f"Section: {section.name}")
            start_end_pairs = markers_file.get_timestamps_for_section(
                section=section,
                first_start=first_start,
                last_start=last_start,
                window=window,
            )

            if not start_end_pairs:
                logger.debug(f"{section.name} didn't generate any bars")
                continue

            # prepending a quiet copy of the first bar as a count-in
            if needs_intro:
                from_intro = (
                    max(
                        [
                            start_end_pairs[0][0],
                            start_end_pairs[0][1] - 4,
                        ]
                    )
                    * 1000
                )
                to_intro = start_end_pairs[0][1] * 1000
                logger.debug(f"Adding intro from : {from_intro}:{to_intro}")
                output_audio += (
                    source_audio["silent" if "silent" in source_audio else "bass"][
                        from_intro:to_intro
                    ]
                    - 35  # that's dBs, to make intro barely audible
                )
                needs_intro = False

            for measure in start_end_pairs:
                for output_instruction in output_instructions:
                    for _ in range(output_instruction["repeats"]):
                        output_audio += source_audio[output_instruction["source"]][
                            int(measure[0] * 1000) : int(measure[1] * 1000)
                        ]
                    logger.debug(
                        f"Adding {output_instruction['repeats']} times: {output_instruction['source']} from: {measure[0]}:{measure[1]}"
                    )

                logger.debug(f"measure: {measure}")

    logger.info(f"generating: {sources.with_root(file_obj.destination)}")
    output_audio.export(
        sources.with_root(file_obj.destination), format=file_obj.destination.suffix[1:]
    )
