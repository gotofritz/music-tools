# Initial context

Architecture, boundaries and constraints. Read this before changing anything;
update it in the same PR as any change to the architecture, the boundaries or
the core patterns (`AGENTS.md`).

Describing the repo as it stands at the end of Phase 2 of
`docs/plans/00-practice-app.md`, not as that plan leaves it.

## What this repo is

A single musician's bass practice tooling, for one person on one machine.
Three things live here, and the plan in `docs/plans/` is about making them one
thing:

- **`practice`** — the practice tracker: modules, exercises, spaced repetition
  and a day log, over SQLite. It replaces a Google Sheets app whose sample and
  Apps Script are kept in `docs/raw/`, and which the importer reads.
- **`loop`** — the audio half. It takes a snippet of audio, a marker file
  exported from Transcribe!, and a YAML config, and builds a rhythm-training
  file in which chosen bars, beats or marked spans are replaced by silence of
  the same length.
- **`rearrange`** — an older, larger generator driven by a nested step DSL. It
  works and it is not being developed. Unifying it with `loop` is wanted
  eventually and is explicitly out of scope for the current plan.

The point of the plan is that the exercise being practised *is* the tune the
loop is built from: due → loop → play → done. Phase 4 attaches loops to
exercises; today they are two commands over one database's worth of vocabulary.

## Layout

```
music_tools/
    cli.py               practice: the click group, and the only clock and rng
    db/
        connection.py    open_db, the pragmas, the transaction helper
        migrate.py       user_version-gated runner
        migrations/      numbered .sql, applied in order
        repository.py    hand-written SQL in, pydantic models out
    domain/
        models.py        Module, Exercise, PracticeDay, PracticeEntry, ...
        tempo.py         the speed grammar
        scheduling.py    the five algorithms, pure
        session.py       start a day, mark done, day totals
    importer/
        sheets.py        the one-off spreadsheet importer
    loop.py              the loop tool: model, parsing, rendering, CLI
    main.py              rearrange: the CLI and the step interpreter
    config.py            rearrange: pydantic config models
    generator.py         rearrange: output assembly
    markers.py           rearrange: its own marker reader
    configs/             rearrange: worked example configs
tests/
    conftest.py          marker fixtures, the db fixture, the seeded rngs
    fixtures/*.txt       hand-written marker exports
    test_migrations.py test_tempo.py test_scheduling.py
    test_session.py    test_importer.py test_cli.py
    test_score.py      test_patterns.py test_drills.py
docs/
    initial-context.md   this file
    user-guide.md        for the player, not the programmer
    plans/               the active plan, one document per phase
    archive/             completed plans
    raw/                 the spreadsheet being replaced, and its scripts
triads.py                standalone practice generators, unrelated to the above
intervals.py
generate_exercise.py
config/, tunes/          hand-kept example inputs and shell wrappers
```

## Vocabulary

The sheet used one word for three things, so, once and for all:

- A **module** is a practice area — one sheet: `SLAP`, `SONGS`, `TECHNIQUE`.
- A **log group** is the coarser bucket the day log subtotals by — `TECHNIQUE`,
  `REPERTOIRE`. The Apps Script read it from cell `A1` of the module's sheet,
  and the importer still does.
- A **style** is the per-row tag in the sheet's own `MODULE` column — `NEOSOUL`,
  `RNB`, `DANCE`. No code reads it; it is a label.
- An **exercise** is a row of a module. An **entry** is a line of the day log.
- A **practice day** runs to 4am, not midnight (`END_OF_DAY_HOUR`).

## How `practice` is put together

```
CLI  ─── now, random.Random ───▶  domain/session   ──▶  db/repository ──▶ SQLite
                                    │      ▲                (SQL, pydantic)
                        domain/tempo│      │domain/scheduling
                          (pure)    ▼      │      (pure)
                                 Tempo   next_due
```

Three rules hold the shape:

- **`domain/tempo.py` and `domain/scheduling.py` are pure.** No I/O, no clock,
  no global `random`. They take what they need and return a value.
- **`domain/session.py` is the only place that composes writes.** It opens one
  transaction per operation and calls the repository inside it.
- **`db/repository.py` never opens a transaction** and never makes a decision.
  SQL in, models out.

**The clock and the rng are injected everywhere.** Any function that would
otherwise call `datetime.now()` takes `now` as an argument, and anything random
takes a `random.Random`. `cli.py` is the only module that constructs either, so
tests assert exact dates without `freezegun` and without monkeypatching
`random`.

### The tempo grammar

The speed column is a small language, and different tools speak different
dialects of it — Transcribe! in percentages, metronomes in BPM. `parse_tempo`
resolves both against the exercise's `target_bpm`:

| Written | Means | BPM |
| --- | --- | --- |
| `123` | 123 BPM | 123 |
| `123/1` | the same, spelled out | 123 |
| `123/2` | 123 a minute, one every 2nd beat | 246 |
| `123/0.5` | 123 a minute, one every half beat | 61.5 |
| `66%` | 66% of the target | 88 at a target of 133 |

`ratio = bpm / target_bpm`, capped at 1.0, is what the scheduler reads: it is
what makes the two dialects comparable. Parsing is **total** — the column has
years of free text in it, so anything unreadable (and any percentage with no
target to resolve against) comes back as unknown, is kept verbatim, and simply
does not scale the schedule.

### Scheduling

`INTERVALS = (1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120)`, read
at the **post-increment** count, ±5% jitter, `SHORT` and `LONG` scaling the
whole table by 0.5 and 1.5 with `ceil`. `ROTATE` and `HOLD` ignore the table and
move the exercise to one end of the module's queue; `ROTATE`'s scan of the
module's due dates includes the exercise itself and `HOLD`'s excludes it,
because the sheet's two scans disagreed on exactly that.

Two things are deliberately not the sheet, and both are pinned by tests:

- **Tempo scaling is inverted from the sheet, and the floor moved with it.**
  `bass.gs` multiplied by `100/percent`, so a tune under tempo came back
  *later*. Here the interval is multiplied by the ratio, and the `max(1, …)`
  floor is applied **after** the scaling, so nothing can schedule below a day.
- **Rounding is half-up** (`math.floor(x + 0.5)`), because Apps Script's
  `Math.round` is and Python's `round` is banker's.

### The day log

`mark_done` is `doneExercise_`, in one transaction: count +1, `last_practiced`,
`next_due`, close the running entry, open the next one at the same instant, so
entries tile the session end to end. An entry left running from an earlier day
is **discarded** rather than closed at an invented time — it is the dangling
`FROM` the sheet left behind, and it was never attributed.

Tiling is the default and not the rule. `restart_clock` (the `start` command)
restamps the running entry's `started_at` to now, so the gap since the last
`done` — a break — is not logged against whatever is played next. The rule
underneath both cases is the same: **time nobody attributed is not practice
time**, and the app will not invent an attribution for it.

`description`, `speed`, `bpm` and `log_group` on an entry are **snapshots**: the
log is a record and must not change when an exercise is renamed, retuned or
moved. Durations, subtotals and day totals are **computed, never stored** —
which is what `updateSummaryFormulas` and `compressRowsToRanges_` were doing by
hand, and what a `GROUP BY` does. Time not yet attributed to a log group (the
entry running right now) counts towards the day total but has no subtotal.

### Storage

`~/.local/share/music-tools/practice.db`, overridable with `MUSIC_TOOLS_DB` or
`--db`. Audio and marker files are *referenced by path*, never copied.

No ORM and no Alembic: `sqlite3` from the standard library, hand-written SQL,
numbered `.sql` migrations gated by `PRAGMA user_version` and applied in their
own transaction. `open_db` sets `foreign_keys = ON` (off by default in SQLite,
which would silently void every `REFERENCES`) and `journal_mode = WAL`. A
database stamped newer than the code is refused rather than touched.

Four tables — `module`, `exercise`, `practice_day`, `practice_entry`. The
importer's natural keys are `(module, name)` for exercises, enforced by a
partial unique index, and `(day, started_at)` for entries, which is a lookup
rather than a constraint because two exercises marked done in the same second
share an instant.

`practice db dump` (and `task db:dump`) writes `backups/practice.sql` through
`sqlite3.iterdump`, so no `sqlite3` binary is needed and the practice history
can live in a git repository and diff row by row. The spreadsheet gave version history
for free and a local file does not.

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

The practice half raises `click.ClickException` only from `cli.py`; the domain
raises plain Python exceptions (`UnknownExercise`, `MigrationError`) so a web
layer can catch them without depending on click.

## Constraints

- **Python 3.12+, `uv` for everything.** Dependencies are `click`, `pydantic`,
  `pydub` and `pyyaml`; dev dependencies are `pytest`, `ruff` and `ty`.
- **`ffmpeg` must be on `PATH`** for anything that is not a `.wav`; pydub shells
  out to it. CI installs it. Nothing in the practice half needs it.
- **One machine, one user, local files.** No auth, no accounts; when a server
  arrives in Phase 3 it binds `127.0.0.1`.
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

`task qa` runs lint, types and tests. The Phase 1 suite is
**characterisation** — it pins `loop` behaviour that already existed so later
refactors break loudly. Everything from Phase 2 on is red-first
(`.claude/skills/tdd.md`): a failing test, watched failing, then the minimal
green.

Fixtures are hand-written text, small enough to read in a diff: marker exports
in `tests/fixtures/`, and the spreadsheet sample in `docs/raw/`, which
`test_importer.py` reads directly so the importer is tested against the real
export rather than a tidied copy. There are no binary fixtures anywhere: audio
in tests comes from `AudioSegment.silent(duration=…)`.

The database fixture is in-memory and migrated per test; `steady_rng` dials the
jitter out for exact assertions and `rng` is a seeded `random.Random` for the
statistical ones.

## Where this is going

`docs/plans/00-practice-app.md` is the map. Phases 1 (test suite, CI, an
importable `loop.py`) and 2 (the domain, the database, the importer and the
CLI) are done, and the spreadsheet is technically redundant. Phase 3 puts a
FastAPI/HTMX app over the same functions and retires the sheet for good; Phases
4 to 6 attach loops to the exercise that is due, play them in the browser, and
finally replace Transcribe! for marking up new tunes.

Out of scope throughout: `rearrange` and its step DSL, the standalone
`triads.py` / `intervals.py` / `generate_exercise.py` generators, merging
`Score` with `markers.MarkerFile`, and anything multi-user or remote.
