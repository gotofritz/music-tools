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
selected repetitions with silence.

Example:

    uv run loop.py trainer.yml
"""

from pathlib import Path

import click
import yaml
from pydub import AudioSegment
import subprocess


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="""
Generate a rhythm training audio file from a YAML configuration.

The input audio file is treated as one indivisible unit ("snippet").
The program never attempts beat detection or tempo estimation.

Each character in a sequence represents one repetition of the snippet:

    1   play the snippet
    x   silence of exactly the same duration

Sections allow progressively harder exercises.

Example:

sections:
  - name: Warm-up
    repeat: 8
    sequence: "1111"

  - name: Lose the first
    repeat: 8
    sequence: "x111"

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

    snippet_path = Path(cfg["snippet"])
    output_path = Path(cfg["output"])
    sections = cfg["sections"]

    snippet = AudioSegment.from_file(snippet_path)
    silence = AudioSegment.silent(duration=len(snippet))

    output = AudioSegment.empty()

    total_units = 0
    total_sections = len(sections)

    click.echo(f"Loaded snippet: {snippet_path}")
    click.echo(f"Snippet length: {len(snippet)/1000:.2f} s")
    click.echo()

    for i, section in enumerate(sections, start=1):

        name = section.get("name", f"Section {i}")
        repeat = int(section["repeat"])
        sequence = str(section["sequence"]).strip()

        if not sequence:
            raise click.ClickException(
                f"{name}: sequence may not be empty."
            )

        invalid = set(sequence) - {"1", "x"}
        if invalid:
            raise click.ClickException(
                f"{name}: invalid characters: {', '.join(sorted(invalid))}"
            )

        click.echo(f"[{i}/{total_sections}] {name}")
        click.echo(f"    {repeat} × {sequence}")

        for _ in range(repeat):
            for c in sequence:
                output += snippet if c == "1" else silence

        total_units += repeat * len(sequence)

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
