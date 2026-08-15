# Phase 1 — Foundations

**Phase 1 of `docs/plans/00-practice-app.md`.** Read that first for the domain
and the decisions.

## Goal

The repo can run a test suite, and `loop.py` can be imported. Nothing in this
phase changes behaviour: it exists so the phases that follow can be written
test-first, and so a refactor that breaks `loop.py` says so.

**Done when** `task qa` is green, `uv run loop config.yml` behaves exactly as
`uv run loop.py config.yml` did, and the marker/pattern behaviour is pinned by
tests.

## Honest caveat

Steps 4–6 are **characterisation** tests. The behaviour already exists;
they are red only because there is no suite yet. That is not TDD, it is a safety
net being installed before surgery, and calling it anything else would be
dishonest. Every later phase in this plan is properly red-first.

## Shape

```
Taskfile.yml
.github/workflows/qa.yml
pyproject.toml                 # dev deps, entry point, tool config
music_tools/loop.py            # moved from ./loop.py
tests/
    conftest.py                # shared fixtures
    fixtures/
        d51.txt                # 4 bars D51-D54, labelled beats, one text block
        d51x.txt               # a bar genuinely called "D51x"
        jackson5.txt           # A1-A4, five beats in A3
        twoway.txt             # ends on a bare bar marker "93"
        pickup.txt             # short first bar
        endmarker.txt          # a marker labelled "end" mid-file
    test_score.py
    test_patterns.py
```

## Steps

### Step 1 — `task qa` exists and fails

**Red.** `task qa` — no `Taskfile.yml`, no pytest. AGENTS.md already tells
agents to use `task` for workflow discovery and it has never existed.

**Green.** `Taskfile.yml` with:

| Target | Runs |
| --- | --- |
| `task test` | `uv run pytest` |
| `task lint` | `uv run ruff check . && uv run ruff format --check .` |
| `task types` | `uv run ty check` |
| `task qa` | all three |

Dev dependencies into a `[dependency-groups] dev` block — `pytest`, `ruff`,
`ty`. `[tool.pytest.ini_options]` with `testpaths = ["tests"]`. Ruff configured
to match what is already written rather than reformatting the repo in this
phase: check `ruff format --diff .` first and set `line-length` to whatever
leaves `loop.py` untouched.

An empty `tests/test_smoke.py` asserting `True` proves the wiring. `task qa`
green, on a repo where nothing has been tested yet.

### Step 2 — CI

**Red.** No `.github/` at all, though AGENTS.md says "CI via GitHub Actions" and
"all checks must pass before merge".

**Green.** `.github/workflows/qa.yml`: checkout, `astral-sh/setup-uv`, install
`task` (`arduino/setup-task` — a bare runner does not have it), then
`uv sync --all-groups` and `task qa`. Install `ffmpeg` too — `pydub`
needs it for mp3, and a later phase generates audio in tests.

Nothing macOS-only may run in CI: the Transcribe! launch is behind a flag from
`04-loop-editor.md` step 2, and until then no test may call `main`.

### Step 3 — `loop.py` becomes importable

`loop.py` is a PEP 723 single-file script with an inline dependency block, so
`from music_tools.loop import Score` cannot work.

**Red.** `tests/test_score.py` opens with

```python
from music_tools.loop import Score, parse_markers
```

→ `ModuleNotFoundError: No module named 'music_tools.loop'`.

**Green.** `git mv loop.py music_tools/loop.py`; delete the `# /// script` block
(`click`, `pyyaml` and `pydub` are already project dependencies); add
`loop = "music_tools.loop:main"` to `[project.scripts]` beside the existing
`rearrange`; update the docstring and the `--help` epilogue from
`uv run loop.py trainer.yml` to `uv run loop trainer.yml`.

Imports move to the top of the file if any are not already there, per the
project's code standards.

### Step 4 — Marker parsing pinned

Fixtures are text — a marker export is lines like

```
0:00:12.191723 Marker (section): "A"
0:00:12.541406 Marker (beat): ""
```

so they are written by hand, small, and readable in a diff. No binary fixtures
anywhere in this plan: audio comes from `AudioSegment.silent(duration=…)` in a
`conftest.py` fixture.

**Red.** `tests/test_score.py`, one test per behaviour:

- `parse_markers` on `d51.txt` yields four bars `D51`–`D54` of four beats each,
  beats `b1`/`b2` labelled in the first bar, one text block `JOHN`.
- `twoway.txt` ends on a bare bar marker `93` with no beats under it: it closes
  the last bar instead of opening one, lands in `score.end_marker`, and is
  addressable as the end of the score but never played.
- `endmarker.txt` — a marker labelled `end` truncates the score there and
  everything after it is dropped. Undocumented behaviour that predates the
  pattern grammar, and the reason nothing can shadow the reserved `END`.
- `jackson5.txt` yields `A1`–`A4`, with five beats in `A3`.
- `Marker (auto)` counts as a beat, not something to skip: Transcribe! writes it
  for beats it worked out itself, and a file mixing `auto` and `beat` markers
  must give every bar the same beat count.
- A kind that is neither bar nor beat is counted into `score.ignored` and
  reported, rather than dropped in silence.
- `Score.build` shifts the first marker to `0.0`; the last bar ends at the
  snippet duration. That anchoring is why audio before the first marker cannot
  be addressed — a loop starting on an upbeat must mark that upbeat.
- `pickup.txt`: a first bar shorter than the bars after it sets `score.pickup`,
  numbering starts at `[0]`, and `[1]` is the first full bar. A loop with square
  edges keeps 1-based numbering and has no `[0]`.
- The odd-beat-count warning covers interior bars only — a snippet cut from a
  recording is expected to be partial at both edges. A short bar in the middle
  warns; a short first or last bar does not.
- `modal_beats` breaks a tie toward the longer count, so a `2+4+4+2` loop reads
  as two full bars between two partial ones. Breaking it the other way blames
  the two correct interior bars, which is what `Counter.most_common` does on its
  own — the same trap that made the warning name the wrong bar on a `1+4` file.
- Bars tile the snippet with no gaps or overlaps, and so do beats.
- Markers running past the snippet raise, with the "belong to this snippet"
  message.

**Green.** Nothing, if step 3 was clean. A failure here is a botched move.

### Step 5 — Pattern resolution pinned

**Red.** `tests/test_patterns.py`, parametrised over every span form against the
D51 score: `[1][2][3][4x]` tiling the snippet bar by bar; `[D51]…` matching it
by label; `[1.1][1.2][1.3][1.4x][2]`; `[b1][b2]`; `[JOHN]` alone running to the
end; the ranges `[1-3]`, `[1.4-3]`, `[JOHN-3.2]`, `[JOHN-D53]`, `[1.1-JOHN]`,
`[1-3x]`; repeats and out-of-order runs written with explicit ends.

The neighbour rule specifically: `[1]` alone is the whole snippet, `[1][3]` is
bars 1–2 then 3 to the end, and in `[1][2]` the first span covers exactly what
`[1-2]` covers, only because 2 follows — the pattern as a whole still runs on
to the end.

On `twoway.txt`: `[92-93]` naming the end marker as an end, equal to a bare
`[92]` but usable anywhere in a pattern, and equal again to `[92-END]`.

Errors, each asserting the message names the offending token: `[nope]`,
`[JOHN-nope]`, `[]`, `[9]`, `[1.9]`, the backwards span `[JOHN-b2]`, the empty
`[1][1]`, `[3][1]`, `[93]`, `{JOHN}` pointing at square brackets, and
`[1]junk[2]`.

And on `d51x.txt`, a bar genuinely labelled `D51x`: `[D51x]` plays it rather
than silencing `D51`.

The grid modes, as far as they reach without calling `main`: `read_pattern`
accepts exactly one of sequence/bars/beats/markers, names invalid characters,
rejects an empty pattern, and strips the spaces that only group; `bar_slices`
and `beat_slices` tile the snippet. The bars/beats length-mismatch error is
inline in `main` and cannot be pinned here — `04`'s step 2 extracts that code,
and its test asserts the error then, shape hint included.

**Green.** Nothing again — these should pass on arrival.

### Step 6 — The drill expansion pinned

`expand_drill` generates whole runs of sections from one line, and `04` puts a
UI in front of it. It needs pinning before anything depends on its output.

**Red.** `tests/test_drills.py`, textual only — no score, no audio:

- Each step name over `[A][B][C][D]` with `keep: 1`, asserting the exact list
  from the CLI help: `each` → `Bx`, `Cx`, `Dx`; `head` → growing; `tail` →
  growing from the end; `build`; `widen`; `solo`.
- Steps compose in the order given and never repeat a silencing already reached
  — `[widen, solo]`, the default, does not emit `widen`'s last set twice.
- `keep: 0` lets a window reach every region, so `tail` ends on total silence.
- `cycle: 2` lays the regions down twice and drills the whole run; a bare region
  is closed by whatever follows it, so cycling gives every region an explicit
  end and the last does not run backwards into the first.
- `reference` inserts the plain pattern before each step.
- An unknown step name raises, naming the valid ones.

**Green.** Nothing.

## Verification

1. `uv run loop "~/…/Jacksons 5/practice.loop.yml"` writes the file it wrote
   before the move, byte for byte.
2. `task qa` green locally and in CI.

## Out of scope

No behaviour changes at all — `root:` defaulting, the `build_output` extraction
and `PatternError` all belong to `04-loop-editor.md`, where something depends on
them. Nothing here touches `rearrange`, `markers.py`, or the standalone scripts.
