# music-tools

Bass practice tooling for one player on one machine.

The tool under active development is **`loop`**. Give it a few seconds of
audio, a marker file exported from Transcribe!, and a short YAML file saying
what you want, and it builds a rhythm-training track: the same passage over and
over, with chosen bars, beats or spans replaced by silence of exactly the same
length. The pulse never moves; where the recording stops, you keep playing.

There is also **`rearrange`**, an older generator driven by a nested step DSL.
It works, it is not being developed, and folding it into `loop` is a job for
later.

**If you are here to practise rather than to write code, read the
[user guide](docs/user-guide.md).** It covers marking up a tune, writing the
settings file, every kind of pattern, drills, and what the error messages mean.

Everything below is for developers.

---

## Developer guide

### Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/),
[Task](https://taskfile.dev/), and `ffmpeg` on `PATH` (pydub shells out to it
for anything that is not a `.wav`).

```bash
uv sync --all-groups
source .venv/bin/activate
```

### Running it

```bash
uv run loop practice.yml            # build the practice file
uv run loop --expand practice.yml   # print what a drill stands for, and stop
uv run loop --help                  # the full pattern grammar
uv run rearrange --help
```

`uv run loop --help` is the reference for the config format; the
[user guide](docs/user-guide.md) is the same material written for a player.

### Workflow

```bash
task qa       # lint, types, tests — run this before opening a PR
task test     # uv run pytest
task lint     # ruff check + ruff format --check
task types    # ty check
```

CI runs `task qa` on every push to `main` and every pull request
(`.github/workflows/qa.yml`).

### Layout

```
music_tools/loop.py     the loop tool: model, parsing, rendering, CLI
music_tools/main.py     rearrange, plus config.py, generator.py, markers.py
tests/                  conftest.py, hand-written marker fixtures, three suites
docs/initial-context.md architecture, invariants and constraints
docs/user-guide.md      for the player
docs/plans/             the active plan, one document per phase
docs/raw/               the spreadsheet being replaced, and its Apps Script
```

`docs/initial-context.md` explains how `loop` is put together and which
behaviours are load-bearing. Read it before changing anything, and update it in
the same PR as any change to the architecture, the boundaries or the core
patterns.

### Testing

TDD throughout — failing test, watch it fail, minimal green, refactor
(`.claude/skills/tdd.md`). The one exception is the Phase 1 suite, which is
**characterisation**: it pins behaviour that already existed so later refactors
break loudly.

Marker fixtures are hand-written text in `tests/fixtures/`, small enough to read
in a diff. There are no binary fixtures: audio in tests comes from
`AudioSegment.silent(duration=…)`.

Nothing macOS-only may run in CI. `main` ends by launching Transcribe! on the
output, so no test may call it until that is behind a flag (Phase 4).

### Conventions

- Small, atomic commits; imperative present tense; subject ≤ 72 characters.
- Branches are `feature/<name>` or `fix/<name>`.
- Ruff is pinned to the `E`/`F`/`I` rules at line length 88, and `ty` is scoped
  away from the `rearrange` modules. Both are documented in `pyproject.toml`
  and are clean-ups of their own rather than silent suppressions.
- `AGENTS.md` is the full set of rules, and `CLAUDE.md` points at it.

### Where this is going

`docs/plans/00-practice-app.md` replaces the practice spreadsheet in `docs/raw/`
with a local app, and grows the loop tooling into it. Phase 1 — a test suite, CI
and an importable `loop.py` — is done. Phase 2 adds the domain, a SQLite
database and an importer for the spreadsheet's history; Phases 3 to 6 put a
local FastAPI/HTMX app over it, attach loops to the exercise that is due, play
them in the browser, and replace Transcribe! for marking up new tunes.
