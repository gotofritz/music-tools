# Initial context

Architecture, boundaries and constraints. Read this before changing anything;
update it in the same PR as any change to the architecture, the boundaries or
the core patterns (`AGENTS.md`).

Describing the repo as it stands at the end of Phase 3 of
`docs/plans/00-practice-app.md`, not as that plan leaves it.

## What this repo is

A single musician's bass practice tooling, for one person on one machine.
Three things live here, and the plan in `docs/plans/` is about making them one
thing:

- **`practice`** — the practice tracker: modules, exercises, spaced repetition
  and a day log, over SQLite. It replaced a Google Sheets app; the history was
  imported, and the sheet's sample, its Apps Script and the one-off importer
  that read them have all been removed — this database is the only record now.
  It has two front ends over one domain: a click CLI, and a local browser app
  (`practice serve`).
- **`loop`** — the audio half. It takes a snippet of audio, a marker file
  exported from Transcribe!, and a YAML config, and builds a rhythm-training
  file in which chosen bars, beats or marked spans are replaced by silence of
  the same length.
- **`rearrange`** — an older, larger generator driven by a nested step DSL. It
  works and it is not being developed. Unifying it with `loop` is wanted
  eventually and is explicitly out of scope for the current plan.

The point of the plan is that the exercise being practised *is* the tune the
loop is built from: due → start → play → done. Phase 4 attaches the tune's
media to exercises; today they are two commands over one database's worth of
vocabulary.

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
        catalogue.py     modules and their rows: CRUD, and what may be deleted
        session.py       start a day, mark done, day totals
    web/
        app.py           create_app(db_path), and the `practice serve` launcher
        deps.py          per-request connection, clock, rng, and the templates
        views.py         what each page reads, gathered off the routes
        routes/          practice.py (the day), modules.py (the catalogue)
        templates/       base, today, module, and one fragment per swappable thing
        static/          htmx.min.js (vendored via pnpm, 2.0.4) and app.css
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
    test_catalogue.py  test_session.py  test_cli.py
    test_score.py      test_patterns.py test_drills.py  test_web.py
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

- A **module** is a practice area — one sheet: `SLAP`, `SONGS`, `TECHNIQUE`. It
  is the fundamental abstraction: a queue of its own, scheduled within itself,
  asked for a module at a time. `ROTATE` and `HOLD` scan one module's due dates
  and no other's, `next` prints a block per module, and archiving one takes its
  whole queue out of circulation. Nothing crosses modules except the day log,
  which adds their time up by log group.
- A **log group** is the coarser bucket the day log subtotals by — `TECHNIQUE`,
  `REPERTOIRE`. The Apps Script read it from cell `A1` of the module's sheet;
  here it is a column on `module`, set when the module is made.
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
- **`domain/session.py` and `domain/catalogue.py` are where writes are
  composed.** They open one transaction per operation and call the repository
  inside it. `session.py` is a practice session — the clock, `mark_done`, the
  totals. `catalogue.py` is the shape of the catalogue itself — modules, their
  rows, and what may be renamed, archived or deleted.
- **`db/repository.py` never opens a transaction** and never makes a decision.
  SQL in, models out. Refusing to delete a row with history is a decision, which
  is why that lives in `catalogue.py` and not next to the `DELETE`.

**The clock and the rng are injected everywhere.** Any function that would
otherwise call `datetime.now()` takes `now` as an argument, and anything random
takes a `random.Random`. Exactly two modules construct either — `cli.py` for
the terminal and `web/deps.py` for the browser, one front end each — so tests
assert exact dates without `freezegun` and without monkeypatching `random`.

**Both front ends let a test pin that one construction**, which is what makes
the suites deterministic rather than merely correct at the hour they run. The
browser app overrides `get_now` and `get_rng` through
`app.dependency_overrides`. The CLI takes a hidden `--now`: `ctx.obj` is an
`Env(db_path, now)`, `_now(ctx)` is the single read, and `Env.clock()` falls
back to the real clock when the flag is absent — the same trick `--db` plays
for storage. Without it `test_cli.py` compared the day log against
`date.today()`, which is not the practice day between midnight and 4am, so the
suite passed for twenty hours a day and failed for four. CI runs in UTC and
nothing ever merged in that window, so it went unnoticed. **No test may read
the wall clock**; the suite is pinned to `NOW = 2026-07-05 22:27` and passes at
any hour, in any timezone.

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
`done` — a break — is not logged against whatever is played next. `stop_clock`
(the page's "stop the clock") ends a session the same way: an entry that
already says what was played is closed at `now`, and the running one, which
never does, is deleted. The rule underneath all three cases is the same:
**time nobody attributed is not practice time**, and the app will not invent an
attribution for it.

`log_entry` is `mark_done` without the schedule half, for practice the
catalogue does not know about — a warm-up, a jam, a lesson. It snapshots a
description into the running entry, closes it, and opens the next one at the
same instant, so an ad-hoc block still tiles.

### Archiving and deleting

`archived_at` on both `module` and `exercise` is the normal way things leave:
reversible, and the day log stays intelligible. `exercises_due` excludes
archived rows *and* the rows of archived modules, so archiving a module retires
its queue in one move.

Hard deletes are for mistakes and stop at history: `catalogue.delete_exercise`
refuses once any entry points at the row, and `delete_module` refuses unless it
is empty or `force`d, and refuses either way once any of its rows has been
practised. The rule is that the day log is a record — the catalogue may not
punch holes in it.

The log is written as practice happens, and it can be corrected afterwards:
`amend_entry` rewrites the fields it is passed on one finished entry. The
limits on it are practical, not solemn — this is one player's practice log,
and a wrong correction costs a wrong number about a tune:

- **An entry keeps the day it happened on.** Moving one between days would
  change two days' totals from one edit, which is more surprise than the edit
  is worth. Only the time of day is editable, so an entry that crossed
  midnight keeps both its dates.
- **The running entry is refused** (`EntryRunning`). That one is the clock;
  `mark_done` and `stop_clock` write it, and a hand-edit would put the two out
  of step.
- **Nothing re-tiles.** Shortening an entry leaves a gap, and a gap is time
  that is not in the total — the same rule as everywhere else here.
- **A line can be removed** (`delete_entry`), for the block that should never
  have been written down — a session logged twice, or against the wrong thing
  entirely. Correcting it is the usual move; removing it is for when there is
  nothing to correct. The day itself stays, empty totals and all.

**Editing is per day and asked for.** `GET /days/{day}/edit` redraws that one
day with boxes round its lines and a **remove** button on each, `GET /days/{day}`
puts it back, and both are real links so the toggle survives the JavaScript
being off. The default is read-only because the log is mostly read: a page of
input boxes reads like a form rather than a record of practice. Removal is
`DELETE /entries/{id}`, with `POST /entries/{id}/delete` as the same handler
for a form, and `hx-confirm` in front of it.

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
`open_db(..., check_same_thread=False)` is for the web app alone: its handlers
run on a thread pool, and a connection opened and closed inside one request is
not shared with anything, which is what the check exists to catch.

Four tables — `module`, `exercise`, `practice_day`, `practice_entry`. The
schema sketch in `00-practice-app.md` also gave `module` an `instrument`
column, against a second instrument turning up one day; it is not here. One
player, one instrument, and nothing would ever have read it. Two natural keys
outlive the importer that needed them: `(module, name)` for exercises, enforced
by a partial unique index, and `(day, started_at)` for entries, which is a
lookup rather than a constraint because two exercises marked done in the same
second share an instant.

`practice db dump` (and `task db:dump`) writes `backups/practice.sql` through
`sqlite3.iterdump`, so no `sqlite3` binary is needed and the practice history
can live in a git repository and diff row by row. The spreadsheet gave version history
for free and a local file does not.

## How the browser app is put together

`practice serve` is the second front end over the same domain. It is FastAPI +
Jinja2 + HTMX, server-rendered, with no Node and no JavaScript framework
(assumption A1 of `00-practice-app.md`).

```
browser ──form/hx-post──▶ routes/ ──▶ domain/session, domain/catalogue ──▶ SQLite
                             │                    ▲
                          views.py ───────────────┘   (what a page reads)
                             ▼
                       Jinja2 fragments ── hx-swap-oob ──▶ log, totals, clock
```

- **`app.py` is a factory.** `create_app(db_path)` takes a path, migrates it
  once, mounts `static/` and includes the two routers. Tests get their own
  database without touching `MUSIC_TOOLS_DB`, and two apps in one process
  cannot share one. `serve` binds `127.0.0.1` and opens a browser.
- **`deps.py` is the wiring**: a connection per request, `get_now`, `get_rng`,
  and the Jinja environment. The clock and the rng are dependencies for the
  same reason the CLI passes them down — a test overrides them with
  `app.dependency_overrides` and asserts exact dates.
- **`views.py` is what a page reads.** A route writes, then re-reads through
  the same context builder that rendered the page, so a fragment and the page
  it is swapped into cannot disagree.
- **`routes/` is thin.** Every handler is a domain call and a render. Domain
  refusals map to status codes there and only there: `UnknownExercise` and
  `NotFound` are 404, `InUse` is 409.

Three rules hold this shape, and the tests in `tests/test_web.py` enforce them:

- **Fragments, not JSON.** `POST /exercises/{id}/done` changes three things at
  once, so it answers with the exercise row and swaps the day log, the totals
  and the clock out of band (`hx-swap-oob`). The same id must not appear twice
  in one response, or the swaps fight.
- **Every action is a real form.** HTML forms send only GET and POST, so the
  inline edit is registered for both `PATCH` and `POST`, and a request without
  the `HX-Request` header gets a 303 back to the page it came from instead of a
  fragment. A broken `htmx.min.js` costs page reloads, not the app.
- **Nothing is fetched over the network.** `htmx.min.js` is vendored in
  `static/`; there is no CDN link and no build step. Leaving Sheets was about
  practising with the network off.

**History is paginated by date, not by offset.** `GET /days?before=<iso>`
reads the five finished days before that date, and the button asks for the
oldest day it just drew — no counting, no `OFFSET`, and a page that cannot
shift under an insert. One row past the page is read and thrown away, which is
how the button knows whether to draw itself. The same URL is the link's `href`
and HTMX's `hx-get`: with JavaScript the next page swaps in over the button,
without it the link opens a page of history that carries its own button.

Two behaviours are the web layer's own, both because of what the domain
already does: a row added from the page is due **today** (`exercises_due` drops
undated rows, so an undated one would never reach the list it was typed into),
and a speed typed into the row resolves live through
`GET /exercises/{id}/tempo`, which answers a quiet `?` rather than an error
because it is reading a keystroke, not a submission.

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
`PatternError` from `ClickException` belongs to Phase 7 (segments), where a web
layer needs to catch these without depending on click.

The practice half raises `click.ClickException` only from `cli.py`; the domain
raises plain Python exceptions (`UnknownExercise`, `MigrationError`) so a web
layer can catch them without depending on click.

## Constraints

- **Python 3.12+, `uv` 0.11+ for everything.** Dependency resolution is bounded
  by `exclude-newer = "7 days"` in `pyproject.toml`: a rolling window, so a
  release a few days old is never picked up, and — being project-level — it
  overrides whatever fixed stamp a developer keeps in their own uv config.
  Relative values need uv 0.11; the lock records the window as
  `exclude-newer-span = "P7D"`.
- **Dependencies** are `click`, `pydantic`,
  `pydub`, `pyyaml`, and — for the browser app — `fastapi`, `jinja2`,
  `uvicorn` and `python-multipart`; dev dependencies are `pytest`, `httpx`
  (which `TestClient` needs), `ruff` and `ty`.
- **`ffmpeg` must be on `PATH`** for anything that is not a `.wav`; pydub shells
  out to it. CI installs it. Nothing in the practice half needs it.
- **One machine, one user, local files.** No auth, no accounts, no sessions:
  `practice serve` binds `127.0.0.1` and that is the whole of the security
  model. Anything multi-user would need one from scratch.
- **No Node, and no JavaScript framework.** Recorded in the plan as assumption
  A1 and worth keeping until something forces it. The only JavaScript in the
  repo is the vendored `htmx.min.js` (2.0.4), fetched with `pnpm` in a throwaway
  directory and copied in — there is no `package.json`, no lockfile and no
  build step in this repository. Upgrading it means repeating that fetch and
  saying so in the commit; the README has the two lines.
- **One macOS-only line**: `main` ends by launching Transcribe! on the output.
  Nothing in CI may call `main` until Phase 7 puts that behind a flag.
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
in `tests/fixtures/`. There are no binary fixtures anywhere: audio in tests
comes from `AudioSegment.silent(duration=…)`. The `sample_day` fixture is a day
block copied out of the spreadsheet by hand, kept because the subtotals its own
formulas produced — 00:19, 00:34, 00:53 — are what the port reproduces.

The database fixture is in-memory and migrated per test; `steady_rng` dials the
jitter out for exact assertions and `rng` is a seeded `random.Random` for the
statistical ones.

## Where this is going

`docs/plans/00-practice-app.md` is the map. Phases 1 (test suite, CI, an
importable `loop.py`), 2 (the domain, the database and the CLI) and 3 (the
browser app, and the cutover) are done: the history is imported and the
spreadsheet is no longer used, so this repo is now the only record of what was
practised and when. The importer, and the sheet exports it was tested against,
have been deleted now that the backfill is complete — a one-off job that had
been done, and git history has it if it is ever needed again. Two things follow
from being the only record. `task db:dump` and a committed
`backups/practice.sql` are the whole of the version history a spreadsheet used
to give away. And `target_bpm` is still missing on the rows the import could not
fill; the module view flags them, and they get filled in by use.

Phases 4 to 7 attach the tune's media to the exercise that is due, play it in
the browser — waveform, slow-down, pitch — mark it up there, and rebuild the
loop output from the markers by pointing at the page, replacing Transcribe!
piece by piece. The YAML loop editor is parked at the back of the queue
(`docs/plans/08-loop-editor.md`).

Out of scope throughout: `rearrange` and its step DSL, the standalone
`triads.py` / `intervals.py` / `generate_exercise.py` generators, merging
`Score` with `markers.MarkerFile`, and anything multi-user or remote.
