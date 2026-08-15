# music-tools

Bass practice tooling for one player on one machine.

**`practice`** is the practice tracker: modules of exercises, spaced
repetition, and a running day log. It replaces a Google Sheets app (a sample of
it, and its Apps Script, are in `docs/raw/`), reproduces its schedule, and
imports its history.

```bash
uv run practice next                 # what is due, most overdue first
uv run practice done "le freak"      # schedule it, and log the time
uv run practice start                # back after a break: drop the gap
uv run practice log                  # today's block, with subtotals
```

**`loop`** is the audio half. Give it a few seconds of
audio, a marker file exported from Transcribe!, and a short YAML file saying
what you want, and it builds a rhythm-training track: the same passage over and
over, with chosen bars, beats or spans replaced by silence of exactly the same
length. The pulse never moves; where the recording stops, you keep playing.

The two are heading towards being one thing: the exercise that is due *is* the
tune the loop is built from. `docs/plans/00-practice-app.md` is the map.

There is also **`rearrange`**, an older generator driven by a nested step DSL.
It works, it is not being developed, and folding it into `loop` is a job for
later.

**If you are here to practise rather than to write code, read the
[user guide](docs/user-guide.md).** It covers a practice session end to end,
the speed notation and the schedule, then marking up a tune, writing the
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
uv run practice --help              # the tracker: start, next, done, log, import
uv run loop practice.yml            # build the practice file
uv run loop --expand practice.yml   # print what a drill stands for, and stop
uv run loop --help                  # the full pattern grammar
uv run rearrange --help
```

The practice database lives at `~/.local/share/music-tools/practice.db`.
`MUSIC_TOOLS_DB` moves it, and `--db` overrides both — which is how the tests
run against a temporary file. Migrations are numbered `.sql` files applied on
every open, gated by `PRAGMA user_version`.

`uv run loop --help` is the reference for the config format; the
[user guide](docs/user-guide.md) is the same material written for a player.

### Workflow

```bash
task qa       # lint, types, tests — run this before opening a PR
task test     # uv run pytest
task lint     # ruff check + ruff format --check
task types    # ty check
task db:dump  # back the practice database up to backups/practice.sql
```

CI runs `task qa` on every push to `main` and every pull request
(`.github/workflows/qa.yml`).

### Layout

```
music_tools/cli.py      practice: the click group, and the only clock and rng
music_tools/db/         connection, migrations, repository (SQL in, models out)
music_tools/domain/     tempo, scheduling, session, models — pure where it can be
music_tools/importer/   the one-off spreadsheet importer
music_tools/loop.py     the loop tool: model, parsing, rendering, CLI
music_tools/main.py     rearrange, plus config.py, generator.py, markers.py
tests/                  conftest.py, fixtures, one suite per module
docs/initial-context.md architecture, invariants and constraints
docs/user-guide.md      for the player
docs/plans/             the active plan, one document per phase
docs/archive/           completed plans
docs/raw/               the spreadsheet being replaced, and its Apps Script
```

Two boundaries are load-bearing and are described in full in
`docs/initial-context.md`: `domain/tempo.py` and `domain/scheduling.py` are
pure, and **the clock and the rng are injected everywhere** — `cli.py` is the
only module that calls `datetime.now()` or builds a `random.Random`. Tests
assert exact dates because of it, with no `freezegun` and no monkeypatched
`random`.

`docs/initial-context.md` explains how `loop` is put together and which
behaviours are load-bearing. Read it before changing anything, and update it in
the same PR as any change to the architecture, the boundaries or the core
patterns.

### Testing

TDD throughout — failing test, watch it fail, minimal green, refactor
(`.claude/skills/tdd.md`). The one exception is the Phase 1 `loop` suite, which
is **characterisation**: it pins behaviour that already existed so later
refactors break loudly.

Marker fixtures are hand-written text in `tests/fixtures/`, small enough to read
in a diff, and the importer is tested against the real spreadsheet export in
`docs/raw/` rather than a tidied copy. There are no binary fixtures: audio in
tests comes from `AudioSegment.silent(duration=…)`.

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
with a local app, and grows the loop tooling into it. Phase 1 (a test suite, CI
and an importable `loop.py`) and Phase 2 (the domain, the database, the importer
and the `practice` CLI) are done, which makes the spreadsheet technically
redundant. Phases 3 to 6 put a local FastAPI/HTMX app over the same functions,
attach loops to the exercise that is due, play them in the browser, and replace
Transcribe! for marking up new tunes.
