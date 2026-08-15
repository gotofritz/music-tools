# Initial context

Architecture, boundaries and constraints. Read this before changing anything;
update it in the same PR as any change to the architecture, the boundaries or
the core patterns (`AGENTS.md`).

Written at the end of Phase 1 of `docs/plans/00-practice-app.md`, and describing
the repo as it stands now, not as that plan leaves it.

## What this repo is

A single musician's bass practice tooling, for one person on one machine. Two
things live here, and the plan in `docs/plans/` is about making them one thing:

- **`loop`** — the tool under active development. It takes a snippet of audio,
  a marker file exported from Transcribe!, and a YAML config, and builds a
  rhythm-training file in which chosen bars, beats or marked spans are replaced
  by silence of the same length.
- **`rearrange`** — an older, larger generator driven by a nested step DSL. It
  works and it is not being developed. Unifying it with `loop` is wanted
  eventually and is explicitly out of scope for the current plan.

There is also a spreadsheet, not in this repo, which tracks what to practise
next by spaced repetition. `docs/raw/` holds a sample of it and the Apps Script
behind it. Replacing it with a local app is what the plan is for.

## Layout

```
music_tools/
    loop.py              the loop tool: model, parsing, rendering, CLI
    main.py              rearrange: the CLI and the step interpreter
    config.py            rearrange: pydantic config models
    generator.py         rearrange: output assembly
    markers.py           rearrange: its own marker reader
    configs/             rearrange: worked example configs
tests/
    conftest.py          shared fixtures
    fixtures/*.txt       hand-written marker exports
    test_score.py        marker parsing and score construction
    test_patterns.py     pattern resolution and read_pattern
    test_drills.py       drill expansion
docs/
    initial-context.md   this file
    user-guide.md        for the player, not the programmer
    plans/               the active plan, one document per phase
    raw/                 the spreadsheet being replaced, and its scripts
triads.py                standalone practice generators, unrelated to the above
intervals.py
generate_exercise.py
config/, tunes/          hand-kept example inputs and shell wrappers
```

## How `loop` is put together

One module, four stages, each a plain function or method:

```
marker .txt  ──parse_markers──▶  [(seconds, kind, label)]
                                       │
                                  Score.build
                                       ▼
                                     Score  ──parse_pattern──▶ [(start, end, silent)]
                                       ▲                              │
                             YAML config ──read_pattern──┘             ▼
                                                              pydub renders and exports
```

- **`parse_markers`** is text in, tuples out. It knows about Transcribe!'s two
  line shapes — `Marker (kind): "label"` and a `Textblock (colour):` followed by
  its lines — and nothing else.
- **`Score.build`** turns those tuples into `Bar`s holding `Beat`s. It is where
  every timing decision lives, and the invariants below are its doing.
- **`Score`** is the whole addressing surface: `address` resolves one name,
  `resolve` a `FROM-TO` pair, `span` a token including its trailing `x`, and
  `parse_pattern` a whole pattern. Everything downstream works in seconds.
- **`main`** is a click command that reads the config, expands drills, builds
  the score, resolves each section to spans, and concatenates audio with pydub.

`expand_drill` sits to one side: it rewrites one drill section into the many
plain sections it stands for, purely textually. It needs no score and no audio,
which is what makes `--expand` work on a config whose snippet is not to hand.

### Invariants

These are load-bearing, and the tests in `tests/` exist to make breaking them
loud:

- **The score is anchored on its first marker.** Every timestamp is shifted back
  by it, so bar one starts at 0.0. Audio before the first marker cannot be
  addressed.
- **Ends are exclusive.** `[1-3]` stops where bar 3 begins.
- **A bare span is closed by its neighbour**, or by the end of the snippet if
  nothing follows it. Repeating or reordering therefore needs explicit ends.
- **`END` is reserved** and always names the end of the score. A marker labelled
  `end` truncates the score there — and so names the same point anyway.
- **A trailing bar marker with no beats under it closes the score** rather than
  opening a bar. It lands in `score.end_marker`, is addressable, and is never
  played.
- **A short first bar is a pickup**, numbered 0 the way MuseScore numbers one,
  so `[1]` stays the first full bar. `modal_beats` breaks a tie toward the
  longer count, so a 2+4+4+2 loop reads as two full bars between two partial
  ones.
- **A literal label always beats the trailing-`x` reading.** A bar called
  `D51x` is played by `[D51x]`, not silenced.
- **Bars and beats tile the snippet** with no gaps and no overlaps.

### Error handling

Everything user-facing raises `click.ClickException`, and every message names
the token that caused it. On failure `main` calls `diagnose`, which prints the
section as written and the score as read, because nearly every failure is a
mismatch between what the markers say and what the pattern assumed. Extracting a
`PatternError` from `ClickException` belongs to Phase 4, where a web layer needs
to catch these without depending on click.

## Constraints

- **Python 3.12+, `uv` for everything.** Dependencies are `click`, `pydantic`,
  `pydub` and `pyyaml`; dev dependencies are `pytest`, `ruff` and `ty`.
- **`ffmpeg` must be on `PATH`** for anything that is not a `.wav`; pydub shells
  out to it. CI installs it.
- **One machine, one user, local files.** Audio and marker files are referenced
  by path and never copied.
- **No Node, and no JavaScript framework.** Recorded in the plan as assumption
  A1 and worth keeping until something forces it.
- **One macOS-only line**: `main` ends by launching Transcribe! on the output.
  Nothing in CI may call `main` until Phase 4 puts that behind a flag.
- **`ruff` is pinned to the `E`/`F`/`I` rules** at line length 88, which is what
  the existing code was written against; ruff 0.16's wider defaults flag ~30
  pre-existing things across the repo. `ty` is scoped away from the `rearrange`
  modules for the same reason. Both exclusions are documented in
  `pyproject.toml` and are clean-ups of their own, not silent suppressions.

## Testing

`task qa` runs lint, types and tests. The suite is characterisation-first: the
tests added in Phase 1 pin behaviour that already existed, so that the refactors
in later phases break loudly. From Phase 2 on the plan is properly red-first
(`.claude/skills/tdd.md`).

Fixtures are hand-written marker text, small enough to read in a diff. There are
no binary fixtures anywhere: audio in tests comes from
`AudioSegment.silent(duration=…)`.

## Where this is going

`docs/plans/00-practice-app.md` is the map. Phase 1 (this test suite, CI, and an
importable `loop.py`) is done. Phase 2 adds a SQLite-backed domain — modules,
exercises, a tempo grammar, five spaced-repetition algorithms and a day log —
plus an importer for the spreadsheet's history. Phases 3 to 6 put a local
FastAPI/HTMX app over it, attach loops to the exercise that is due, play them in
the browser, and finally replace Transcribe! for marking up new tunes.

Out of scope throughout: `rearrange` and its step DSL, the standalone
`triads.py` / `intervals.py` / `generate_exercise.py` generators, merging
`Score` with `markers.MarkerFile`, and anything multi-user or remote.
