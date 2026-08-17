"""Write a coverage badge SVG from the current `.coverage` file.

Its own script rather than a dependency: `coverage-badge` imports
`pkg_resources`, which setuptools 81 removed, so it dies on a current runner.
Drawing a two-tone rounded rectangle is less code than pinning a dead import,
and the svg is generated here rather than fetched, which is the same rule the
vendored `htmx.min.js` follows.

Usage: python scripts/coverage_badge.py badge/coverage.svg
"""

import subprocess
import sys
from pathlib import Path

# Wide enough for the glyphs at 11px in the stack below; a couple of pixels of
# slack is invisible, a couple short clips the text.
CHAR_WIDTH = 6.5
PADDING = 10.0
LABEL = "coverage"

COLOURS = (
    (90, "#4c1"),  # brightgreen
    (80, "#97ca00"),  # green
    (70, "#a4a61d"),  # yellowgreen
    (60, "#dfb317"),  # yellow
    (0, "#e05d44"),  # red
)


def total() -> int:
    """The percentage `coverage` reports, as a whole number."""
    reported = subprocess.run(
        ["coverage", "report", "--format=total"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(reported.stdout.strip())


def colour_for(percent: int) -> str:
    for floor, colour in COLOURS:
        if percent >= floor:
            return colour
    return COLOURS[-1][1]  # pragma: no cover - the 0 floor always matches


def badge(percent: int) -> str:
    value = f"{percent}%"
    colour = colour_for(percent)
    left = round(len(LABEL) * CHAR_WIDTH + PADDING)
    right = round(len(value) * CHAR_WIDTH + PADDING)
    width = left + right
    # The narrow rect over the join squares off the rounded corner the value
    # side would otherwise show against the label side.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20"
     role="img" aria-label="{LABEL}: {value}">
  <title>{LABEL}: {value}</title>
  <rect width="{width}" height="20" rx="3" fill="#555"/>
  <rect x="{left}" width="{right}" height="20" rx="3" fill="{colour}"/>
  <rect x="{left}" width="4" height="20" fill="{colour}"/>
  <g fill="#fff" text-anchor="middle" font-size="11"
     font-family="DejaVu Sans,Verdana,Geneva,sans-serif">
    <text x="{left // 2}" y="14">{LABEL}</text>
    <text x="{left + right // 2}" y="14">{value}</text>
  </g>
</svg>
"""


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "badge/coverage.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    percent = total()
    out.write_text(badge(percent))
    print(f"{percent}% -> {out}")


if __name__ == "__main__":
    main()
