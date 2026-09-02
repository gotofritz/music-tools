# music-tools

[![qa](https://github.com/gotofritz/music-tools/actions/workflows/qa.yml/badge.svg)](https://github.com/gotofritz/music-tools/actions/workflows/qa.yml)
[![coverage](https://raw.githubusercontent.com/gotofritz/music-tools/badges/coverage.svg)](https://github.com/gotofritz/music-tools/actions/workflows/qa.yml)

Bass practice tooling for one player on one machine.

**`practice`** is the practice tracker: modules of exercises, spaced
repetition, and a running day log. It replaced a Google Sheets app, reproducing
its schedule; the history was imported and the sheet, its Apps Script and the
one-off importer are all gone. This repo is the record now.

```bash
uv run practice serve                # practise from a browser page
uv run practice module list          # every module: how many rows, how many due
uv run practice next SONGS           # that module's rows, most overdue first
uv run practice start "le freak"     # playing it now: it goes into the log
uv run practice done                 # schedule it, and close the line
uv run practice log                  # today's block, with subtotals
```

An exercise also carries its material: audio or video files, a YouTube URL, a
MuseScore file, text — several at once if that is what the tune is, and several
audio files can be one **track set** (stems, a click beside a backing track).
Files are referenced by absolute path, never copied, and every path in is
confined to the configured roots.

`practice serve` opens the same thing as a page on `127.0.0.1`: what is due, a
card carrying the material for whatever is being practised right now, and a day
log that fills itself in. Every row of a module carries a **start** and a
**stop** button — starting one row closes whichever was running and schedules
it the normal way, and stop is how you choose the interval instead. It needs no
network — the one JavaScript file it uses
is served from the package, and only a YouTube attachment reaches out — and it
works with the JavaScript off, more slowly.

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

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) **0.11 or newer**,
[Task](https://taskfile.dev/), and `ffmpeg` on `PATH` (pydub shells out to it
for anything that is not a `.wav`). `uv self update` if yours is older: the
project sets `exclude-newer = "7 days"` in `pyproject.toml`, and relative
values are only understood from 0.11 on.

That setting is a rolling window — nothing published in the last week is
resolved — and being in `pyproject.toml` it also overrides any `exclude-newer`
in your own `~/.config/uv/uv.toml`, which is the usual reason a sync here
resolves to something ancient or refuses outright. `uv.lock` records it as
`exclude-newer-span = "P7D"`; the `0001-01-01` stamp beside it is uv's own
backwards-compatibility marker and means nothing.

```bash
uv sync --all-groups
source .venv/bin/activate
```

### Running it

```bash
uv run practice --help              # the tracker: module, next, start, done, log, serve
uv run practice serve               # the same thing as a page on 127.0.0.1:8567
uv run loop practice.yml            # build the practice file
uv run loop --expand practice.yml   # print what a drill stands for, and stop
uv run loop --help                  # the full pattern grammar
uv run rearrange --help
```

The practice database lives at `~/.local/share/music-tools/practice.db`.
`MUSIC_TOOLS_DB` moves it, and `--db` overrides both — which is how the tests
run against a temporary file. Migrations are numbered `.sql` files applied on
every open, gated by `PRAGMA user_version`.

Media paths are confined to `MUSIC_TOOLS_MEDIA_ROOTS`, a `:`-separated list
defaulting to the home directory plus the app data directory. Every path in from the browser is resolved and checked against them
— on the way in *and* on the way out, since the roots can be narrowed later —
and the tests point them at a `tmp_path`.

`--now` is the same idea for the clock: hidden, defaulting to the real one, and
pinned by `test_cli.py` so the suite asserts exact dates instead of asking the
wall clock what day it is. A practice day runs to 4am, so a suite that asked
`date.today()` was wrong between midnight and 4am — no test may read the clock.

`practice serve --port 9000 --no-browser` moves the port and leaves the browser
alone. It is FastAPI + Jinja2 + HTMX, server-rendered: routes return HTML
fragments, `htmx.min.js` is vendored in `music_tools/web/static/` rather than
loaded from a CDN, and there is no Node in the build. Every action is a real
`<form>` progressively enhanced with `hx-post`, so the app degrades to page
reloads rather than dying when the JavaScript does.

The vendored file is htmx 2.0.4, fetched once with `pnpm` outside the
repository — there is no `package.json` here and there is not going to be one:

```bash
cd "$(mktemp -d)" && pnpm add htmx.org@2.0.4
cp node_modules/htmx.org/dist/htmx.min.js \
   ~/music-tools/music_tools/web/static/htmx.min.js
```

Upgrading it means running that with a newer version, checking the page still
works, and saying so in the commit.

`uv run loop --help` is the reference for the config format; the
[user guide](docs/user-guide.md) is the same material written for a player.

### Workflow

```bash
task qa       # lint, types, tests — run this before opening a PR
task test     # pytest, with a coverage report
task lint     # ruff check + ruff format --check
task types    # ty check
task db:dump  # back the practice database up to backups/practice.sql
```

CI runs `task qa` on every push to `main` and every pull request
(`.github/workflows/qa.yml`). A push to `main` also uploads `.coverage` and
regenerates the coverage badge onto the `badges` branch — generated output,
kept off `main`. Coverage measures `music_tools/` less the `rearrange`
modules, which have no suite and are out of scope for the practice app.

The two badges at the top read from that: the first is the workflow's own
status badge, the second is `coverage.svg` off the `badges` branch. The
coverage one stays broken until the first push to `main` creates that branch.

### Layout

```
music_tools/cli.py      practice: the click group, and the only clock and rng
music_tools/db/         connection, migrations, repository (SQL in, models out)
music_tools/domain/     tempo, scheduling, session, catalogue, media, models
music_tools/web/        the browser app: app.py, deps.py, routes/, templates/
music_tools/loop.py     the loop tool: model, parsing, rendering, CLI
music_tools/main.py     rearrange, plus config.py, generator.py, markers.py
tests/                  conftest.py, fixtures, one suite per module
docs/initial-context.md architecture, invariants and constraints
docs/user-guide.md      for the player
docs/plans/             the active plan, one document per phase
docs/archive/           completed plans
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
in a diff. There are no binary fixtures: audio in tests comes from
`AudioSegment.silent(duration=…)`.

Nothing macOS-only may run in CI. `main` ends by launching Transcribe! on the
output, so no test may call it until that is behind a flag (Phase 7).

### Conventions

- Small, atomic commits; imperative present tense; subject ≤ 72 characters.
- Branches are `feature/<name>` or `fix/<name>`.
- Ruff is pinned to the `E`/`F`/`I` rules at line length 88, and `ty` is scoped
  away from the `rearrange` modules. Both are documented in `pyproject.toml`
  and are clean-ups of their own rather than silent suppressions.
- `AGENTS.md` is the full set of rules, and `CLAUDE.md` points at it.

### Where this is going

`docs/plans/00-practice-app.md` replaced the practice spreadsheet with a local
app, and grows the audio tooling into it. Phase 1 (a test suite, CI and an
importable `loop.py`), Phase 2 (the domain, the database and the `practice`
CLI), Phase 3 (`practice serve`: the browser app over the same domain
functions, and the cutover) and Phase 4 (media on an exercise, and **start**
replacing the running clock) are done — the history is imported, the
spreadsheet is retired, and the importer that carried it over has been removed
along with it. Phases 5 to 7 play the attached media in the browser —
waveform, slow-down, pitch, and then a tune's 3–8 stems from one transport with
a mixer strip — mark it up there, and rebuild the loop output from the markers
by pointing at the page, replacing Transcribe! piece by piece. The YAML loop
editor is parked at the back of the queue.
