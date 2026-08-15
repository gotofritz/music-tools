# A local practice app

## Context

Two things exist today and want to be one thing.

**A Google Sheets app** (`docs/raw/`) tracks bass practice. One sheet per
practice area — `BASS SONGS`, `BASS SLAP`, `BASS TECHNIQUE` — each row an
exercise carrying a speed, a practice count, a last-practiced date and a due
date. A menu command marks an exercise done: it bumps the count, stamps today,
computes the next due date by a Fibonacci-ish spaced-repetition schedule, writes
a line into the `BASS` day log with the clock times, and re-sorts the sheet by
due date. The log accumulates day blocks with per-module subtotals and a day
total, all held together by spreadsheet formulas.

**A pile of Python scripts** in this repo. `loop.py` is the one under active
development: it takes a snippet of audio, a marker file exported from
Transcribe!, and a YAML config of sections, and builds a rhythm-training file
where chosen bars, beats or marked spans are replaced by silence.

They belong together. The exercise being practiced *is* the tune the loop is
built from. The scenario that drives this plan:

> Practising. The SLAP module says the next thing due is **Stomp!** — 8 times
> practised, currently at 80% speed. Click **loop**, get a form, build a loop of
> a section of the tune, play it, and when done click **done** so the schedule
> and the day log both move on.

This plan replaces the spreadsheet with a local Python app, then grows the loop
tooling into it. `docs/plans/002-loop-editor.md` covers the loop half in detail
and is a phase of this plan, not a separate effort.

## Assumptions

Recorded because they were not confirmed; each is cheap to flip, and the phase
that first depends on it is named.

- **A1 — Stack: FastAPI + Jinja2 + HTMX, server-rendered, no Node.** Tailwind, if
  wanted, via the standalone binary — never a `package.json`. A practice tracker
  is lists, tables and forms, which is exactly what HTMX is good at, and the loop
  grid stays one small island of hand-written JS. Flippable until Phase 3.
- **A2 — Loop configs live in SQLite, keyed to an exercise**, and are *exported*
  to `*.loop.yml` beside the audio on every save. That keeps
  `uv run loop practice.loop.yml` working untouched, and keeps a human-readable
  copy next to the tune. Import in the other direction exists too, for the
  configs already written by hand. Phase 4.
- **A3 — History is migrated**, by a one-off importer that eats the sheet
  exports. The practice counts and due dates are the whole value of the
  spreadsheet; starting fresh throws away the schedule. Phase 1.
- **A4 — All module sheets share the `BASS SONGS` column shape**, with an
  `extra` JSON column absorbing the odd per-module extras rather than a
  per-module field definition. Phase 1; if some sheet turns out to be wildly
  different, only the importer and one migration change.
- **A5 — Single user, one machine, localhost only.** No auth, no accounts, bind
  `127.0.0.1`.

## What the spreadsheet actually does

Read from `bass.gs`, since the app has to reproduce it exactly. Naming used from
here on: a **module** is a practice area (a sheet — SLAP, SONGS, TECHNIQUE); a
**log group** is the coarser bucket the day log subtotals by (`TECHNIQUE`,
`REPERTOIRE`), which the script reads from cell `A1` of the module's sheet; a
**style** is the per-row tag in the sheet's own `MODULE` column (NEOSOUL, RNB,
DANCE), which no script reads and which is a plain label.

**Exercise rows.** Column A is speed, written freely as `100%`, `80%`, `66`,
`54`, `66/1` — a percentage of the original tempo for repertoire, a metronome
BPM for technique. Then description, style, practice count `x`, last practiced,
due, notes, and two recording columns.

**Marking one done** (`doneExercise_`): count +1, last practiced = now, next due
= *f*(count), then a line into the log, then a re-sort by due date, then the
formulas. Note the ordering — the schedule reads the count **after** the
increment, so a row at `x=8` is scheduled with `intervals[9]`.

**The schedule** (`addNextDue`):

```
intervals = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120]
days      = intervals[min(count, len - 1)]
days      = max(1, days + round(days * 0.05 * uniform(-1, 1)))   # ±5% jitter
if speed matches ^(\d+)%$:  days = days * 100 / percent
due       = last_practiced + round(days)
```

with two variants that scale the whole table — `Short` by 0.5, `Long` by 1.5,
both `ceil`ed — and two that ignore it entirely:

- **Simple Rotate**: due = (latest due anywhere in the module) + a random
  −1…+2 days. "Put it at the back of the queue."
- **No Rotation**: due = (earliest due among the *other* rows) − 1 day, applied
  only if that brings it forward. "Practised it, but it is not learned; keep it
  at the front."

Two notes on that:

- **The speed scaling is inverted, and the port fixes it.** At 80% the sheet
  computes `days * 100/80`, a 25% *longer* interval, so a tune still under tempo
  comes back *later* than one already at full speed — backwards. The port
  divides instead:

  ```
  if speed matches ^(\d+)%$:  days = days * percent / 100
  ```

  so 80% gives 0.8× the interval and returns sooner, 100% is unscaled, and a
  tune pushed past the original tempo drifts further out. Combined with the
  `max(1, …)` floor already there, nothing can schedule below a day; `0%` is
  treated as no scaling rather than dividing to zero. This is the one deliberate
  behaviour change in the port. Existing due dates are imported verbatim, so
  nothing shifts at the cutover; anything below 100% simply comes back sooner
  from its next `done` onward.
- **The table plateaus at 120 days**, and `Long` at 180. Pinned by test.

**The day log** is a running clock, not a form. `New Day` appends a row stamped
with today and `FROM = now`. Each `done` sets that row's `TO = now`, fills in
speed and description, and writes `FROM = now` into the *next* row, so entries
tile the session end-to-end. `MODULE` is written only when it changes within the
block; blanks mean "same as above". Subtotals are `SUM` over the (possibly
non-contiguous) rows of each log group, placed on that group's first row; the
day total sums the subtotals.

**Constants declared and unused** in the sample: `END_OF_DAY_HOUR = 4`,
`SLOT_INCREMENT = 18`, `NO_ESTIMATE`, `TOKEN_INVALID`. The first is worth
adopting — practice past midnight belongs to the previous day. The rest are
dropped until they mean something.

**What disappears in the port.** `bassReorder` is `ORDER BY next_due`.
`updateSummaryFormulas`, `compressRowsToRanges_`, `findLastRowWithData`,
`findDayStartRow_` and every `setFormula` call are `SUM`s over a query. The
"walk upward to find the effective module" logic is a foreign key. Roughly 250
of the 413 lines of `bass.gs` are spreadsheet mechanics with no counterpart.

## Shape

```
music_tools/
    loop.py                  # moved from ./loop.py — model, parsing, CLI
    db/
        connection.py        # open, PRAGMA foreign_keys, user_version
        migrations/001_initial.sql, 002_loops.sql, …
        repository.py        # hand-written SQL, returns pydantic models
    domain/
        models.py            # Module, Exercise, PracticeDay, PracticeEntry, …
        scheduling.py        # the five algorithms, pure, injected clock + rng
        session.py           # start day, mark done, close entry, totals
    importer/
        sheets.py            # the one-off TSV importer
    web/
        app.py               # FastAPI + uvicorn launcher
        routes/…             # practice.py, modules.py, loops.py, media.py
        templates/…          # Jinja2, HTMX fragments
        static/…             # vendored htmx.min.js, css, loop grid js
    cli.py                   # click group: practice, db, import, serve
tests/
docs/initial-context.md      # written in Phase 1 — AGENTS.md points at it and
                             # it does not exist yet
```

**Storage.** `~/.local/share/music-tools/practice.db`, overridable with
`MUSIC_TOOLS_DB`. Audio and marker files are *referenced by path*, never copied
into the app; uploaded marker files are written beside the audio they describe.

**Migrations** are numbered `.sql` files applied in order, gated by
`PRAGMA user_version`. No ORM, no Alembic: hand-written SQL against `sqlite3`
from the standard library, with pydantic models on the boundary. The whole
schema is a dozen tables and the queries are all `SELECT … ORDER BY next_due`.
Adding SQLAlchemy would be more new surface than the app it holds.

**Backups.** The spreadsheet gave version history for free and a local SQLite
file does not. `task db:dump` writes `practice.sql` (`sqlite3 .dump`, stable
line ordering) into a backup directory, so the practice history can live in a
git repo and diff row by row. Run it from the app on shutdown too.

## Schema

Sketch, not final; the migration in Phase 1 is the specification.

```sql
CREATE TABLE module (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,        -- "SLAP", "SONGS"
  slug TEXT NOT NULL UNIQUE,
  log_group TEXT NOT NULL,          -- "TECHNIQUE", "REPERTOIRE" (sheet A1)
  instrument TEXT NOT NULL DEFAULT 'bass',
  position INTEGER NOT NULL,
  archived_at TEXT
);

CREATE TABLE exercise (
  id INTEGER PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES module(id),
  name TEXT NOT NULL,               -- "Stomp!"
  style TEXT,                       -- the row's own MODULE tag
  speed TEXT,                       -- verbatim: "80%", "66", "66/1"
  practiced_count INTEGER NOT NULL DEFAULT 0,
  last_practiced TEXT,              -- ISO date
  next_due TEXT,                    -- ISO date
  notes TEXT,
  recorded TEXT, last_recorded TEXT,
  extra TEXT,                       -- JSON, per-module oddities (A4)
  archived_at TEXT
);
CREATE INDEX exercise_due ON exercise(module_id, next_due);

CREATE TABLE practice_day (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL UNIQUE,         -- ISO date, 4am boundary
  notes TEXT
);

CREATE TABLE practice_entry (
  id INTEGER PRIMARY KEY,
  day_id INTEGER NOT NULL REFERENCES practice_day(id),
  exercise_id INTEGER REFERENCES exercise(id),   -- null = ad-hoc entry
  started_at TEXT NOT NULL,
  ended_at TEXT,                    -- null = the entry running right now
  speed TEXT,
  description TEXT NOT NULL,        -- snapshot; exercises get renamed
  log_group TEXT,                   -- snapshot of module.log_group
  notes TEXT
);
CREATE INDEX entry_day ON practice_entry(day_id, started_at);
```

Durations, subtotals and day totals are computed, never stored. `description`,
`speed` and `log_group` are **snapshots** — the log is a historical record and
must not change when an exercise is renamed or moved. That is also what the
spreadsheet did, by accident of being a spreadsheet.

Loop tables (`loop_config`, `loop_section`, and later `marker_file` /
`marker`) are added in Phase 4 and specified in `002-loop-editor.md`.

## Phases

Each phase leaves a working app and is worth stopping at. TDD throughout
(`.claude/skills/tdd.md`): failing test, watch it fail, minimal green, refactor.

### Phase 0 — Test harness, and `loop.py` becomes importable

`loop.py` is a PEP 723 single-file script, so nothing can import `Score`,
`parse_markers` or `parse_pattern` from it and there is no test suite at all.
Move it to `music_tools/loop.py`, register `loop` under `[project.scripts]`,
add `pytest`/`ruff`/`ty` and a `Taskfile.yml` with a `qa` target — AGENTS.md
already assumes `task` exists.

The characterisation tests for `parse_markers` and pattern resolution are
listed in detail in `002-loop-editor.md` steps 1–2; they belong to this phase
because everything else builds on a `loop.py` that can be imported and is known
not to have regressed. Honest caveat: those tests are red only because no suite
exists, not because the behaviour is missing.

### Phase 1 — Domain, database, importer

The spreadsheet's brain, with no UI.

1. **Schema + migration runner.** Red: `migrate(conn)` on an empty database
   leaves `user_version = 1` and the tables above; running it twice is a no-op;
   a database from a future version refuses to open.
2. **Scheduling.** Red: `next_due(count, last_practiced, speed, algorithm, rng)`
   parametrised over the five algorithms and the table above — `count=0` → 1 day;
   `count=8` reads `intervals[8]` given the count is passed post-increment;
   beyond the table, the plateau; jitter within ±5% for a seeded rng and
   never below 1 day; `80%` shortens to 4/5 while `66` and `66/1` (no percent
   sign) are unscaled, and `0%` is unscaled rather than a division by zero;
   `Short`/`Long` scale by 0.5/1.5 with `ceil`. Rotate and No-Rotation take
   the module's due dates as an argument and are pure. Clock and rng are
   injected — no `freezegun`, no monkeypatching `random`.
3. **Marking done.** Red: `mark_done(exercise, algorithm, now)` bumps the count,
   stamps the date, computes the due date, closes the open `practice_entry` at
   `now`, opens the next one, and returns both. Assert an exercise with no open
   entry starts a day implicitly rather than raising.
4. **Totals.** Red: `day_summary(day)` returns per-log-group durations and the
   day total from entries, matching the sample data in `docs/raw/BASS.csv` —
   `2026-07-05` is `TECHNIQUE 00:19`, `REPERTOIRE 00:34`, total `00:53`. That
   sample is the fixture; if the port is right, the numbers come out equal.
5. **The 4am boundary.** Red: an entry at `01:30` lands on the previous day;
   `04:30` starts a new one.
6. **The importer.** Red: `import_sheets(day_log, module_sheets)` over the two
   files in `docs/raw/`. They are *tab*-separated despite the `.csv` extension,
   have trailing empty columns, forward-fill the day and module columns, and
   carry formula results (`MODULE SUBTOTAL`, `DAY TOTAL`) that are recomputed
   and therefore ignored. Assert: 4 exercises with their counts and dates; the
   day blocks reconstructed with entries tiled `FROM`→`TO`; `speed` kept
   verbatim including `66/1`; a description with a trailing `(note)` split back
   into description and note; a second run is idempotent. Rows that cannot be
   parsed are collected and reported, never dropped in silence.

Write `docs/initial-context.md` here: the domain vocabulary above, the schema,
and the module/log-group/style distinction that the sheet blurs.

### Phase 2 — Practice from the CLI

Proves the domain before any HTML exists, and remains useful afterwards.

```
uv run practice day new
uv run practice next [MODULE]        # what is due, oldest first
uv run practice done EXERCISE [--short|--long|--rotate|--hold]
uv run practice log [--day today]    # the day block, with subtotals
uv run practice add MODULE NAME --speed 80%
```

Red: click's `CliRunner` over a temp database — `done` prints the new due date
and the log line, `log` renders the block in the same shape as the sheet.

### Phase 3 — The app, and the cutover

FastAPI + Jinja2 + HTMX. This is the phase where the spreadsheet stops being
used.

- `GET /` — today: the running day log with live totals, plus what is due.
- `GET /modules/{slug}` — the module's exercises, `ORDER BY next_due`, showing
  speed, count, last, due, notes. This is the sheet, minus the sorting command.
- `POST /exercises/{id}/done?algorithm=…` — returns the updated row *and* the
  new log fragment as an HTMX out-of-band swap. One click, the two places that
  change both update.
- `POST /days`, `POST /entries/{id}/stop`, `PATCH /exercises/{id}` for inline
  edits of speed and notes.

Red: `TestClient` over each route — status, and that the fragment contains the
recomputed due date. The templates themselves are checked by hand.

The cutover: import the real exports, use both for a week, diff the totals,
then stop opening the sheet. Keep `docs/raw/` as the record of what was
replaced.

### Phase 4 — Loops, attached to exercises

Detailed in `docs/plans/002-loop-editor.md`. In short: an exercise gets a
**loop** button; a loop belongs to the exercise; creating one asks for the audio
snippet and a Transcribe! marker file, and drops into the section editor —
a grid labelled from the score, live pattern validation, drill expansion, and
generate. Saving writes both the database rows and a `*.loop.yml` beside the
audio, so the CLI keeps working on the same configs.

### Phase 5 — Play it in the app

`/api/preview` returns the generated audio, an `<audio>` element plays it, and
the practice clock keeps running while it does. The full scenario now closes:
due → loop → play → done, without leaving the page.

### Phase 6 — Markers without Transcribe!

Replace the `.txt` upload with marking in the browser: play the snippet, tap
bars and beats, name text blocks, store markers as rows rather than an imported
file. The `marker_file`/`marker` tables arrive here; `parse_markers` becomes one
of two sources feeding the same `Score`. Transcribe! import stays, because
existing tunes already have their markers there.

## Out of scope

Recorded so they do not creep in:

- **`rearrange` and its nested step DSL** (`music_tools/main.py`,
  `music_tools/configs/`). Unifying it with `loop.py` is wanted eventually and
  is not this plan.
- **`triads.py`, `intervals.py`, `generate_exercise.py`** and their JSON state
  files. They are generators of exercises rather than trackers of them; they
  could become a module type later.
- **Merging `Score` with `markers.MarkerFile`**, and the third copy of
  `parse_timestamp` in `main.py`. They answer different questions; consolidating
  belongs to the unify step.
- **Any JavaScript framework**, multi-user, remote hosting, mobile, and
  instruments other than bass beyond the `instrument` column existing.
