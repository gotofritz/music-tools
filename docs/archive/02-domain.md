# Phase 2 — Domain, database, importer

**Phase 2 of `docs/plans/00-practice-app.md`.** Read that first: the tempo
grammar, the schedule and the schema are specified there and this document
implements them. Depends on Phase 1 (a working test suite).

## Goal

Everything the spreadsheet does, as Python with tests, plus the importer that
carries the history over and a CLI thin enough to be a demo of the domain. No
HTML. At the end of this phase practice can be tracked from a terminal and the
sheet is technically redundant — Phase 3 only makes it pleasant.

**Done when** `uv run practice done "le freak"` moves the schedule and writes a
log entry, and importing `docs/raw/` reproduces the sample day totals exactly.

## Shape

```
music_tools/
    db/
        connection.py          # open_db, transactions, PRAGMA setup
        migrate.py             # user_version-gated runner
        migrations/
            001_initial.sql
        repository.py          # SQL in, pydantic out
    domain/
        tempo.py               # Tempo, parse_tempo
        scheduling.py          # Algorithm, next_due — pure
        session.py             # start_day, mark_done, close_entry, summaries
        models.py              # Module, Exercise, PracticeDay, PracticeEntry
    importer/
        sheets.py
    cli.py                     # click group "practice"
tests/
    conftest.py                # db fixture, frozen clock, seeded rng
    test_migrations.py  test_tempo.py  test_scheduling.py
    test_session.py     test_importer.py  test_cli.py
```

**No ORM.** `sqlite3` from the standard library, hand-written SQL, pydantic
models on the boundary. The whole schema is four tables and the hot query is
`ORDER BY next_due`.

**Two things are injected everywhere**: a clock (`now: datetime`) and a
`random.Random`. No `freezegun`, no monkeypatching the `random` module. Any
function that would otherwise call `datetime.now()` takes it as an argument;
the CLI is the only place that supplies the real one.

## Steps

### Step 1 — Migration runner

**Red.** `tests/test_migrations.py`:

- `migrate(conn)` on an empty in-memory database leaves `user_version = 1` and
  the four tables of the schema in `00-practice-app.md`, indexes included.
- Running it twice is a no-op and does not error.
- A database whose `user_version` is higher than the newest migration raises,
  rather than running anything — an old binary must not touch a newer file.
- `open_db(path)` sets `PRAGMA foreign_keys = ON` (off by default in SQLite,
  which would silently void every `REFERENCES` in the schema) and
  `PRAGMA journal_mode = WAL`.
- A `DELETE` of a module with exercises fails on the foreign key rather than
  orphaning rows.

**Green.** `db/connection.py`, `db/migrate.py`, `db/migrations/001_initial.sql`.
Migrations are numbered `.sql` files read from the package directory, sorted by
name, each wrapped in a transaction with `user_version` bumped inside it.

### Step 2 — Tempo

The grammar is in `00-practice-app.md`. It is pure, total, and never raises.

```python
@dataclass(frozen=True)
class Tempo:
    written: str              # exactly as typed
    bpm: float | None
    target_bpm: float | None
    ratio: float | None       # bpm / target_bpm, capped at 1.0

def parse_tempo(written: str, target_bpm: float | None = None) -> Tempo: ...
```

**Red.** `tests/test_tempo.py`, parametrised:

| Written | target | bpm | ratio |
| --- | --- | --- | --- |
| `123` | – | 123 | – |
| `123/1` | – | 123 | – |
| `123/2` | – | 246 | – |
| `123/0.5` | – | 61.5 | – |
| `66%` | 133 | 87.78 | 0.66 |
| `66/1` | 66 | 66 | 1.0 |
| `88` | 133 | 88 | 0.6617 |
| `120` | 100 | 120 | 1.0 (capped) |
| `66%` | – | – | – |
| `fast` | 133 | – | – |
| `` (empty) | 133 | – | – |

Plus: `written` survives byte-for-byte in every case, including
`  80 % ` with its spaces; `0%` gives a `bpm` of 0 and a ratio of 0 that the
scheduler must not divide by; a negative or nonsense divisor (`123/0`) parses to
unknown rather than raising or dividing by zero.

**Green.** Two regexes, a dataclass, no dependencies.

### Step 3 — Scheduling

Pure function, no database, no clock of its own.

```python
class Algorithm(StrEnum):
    NORMAL = "normal"; SHORT = "short"; LONG = "long"
    ROTATE = "rotate"; HOLD = "hold"      # HOLD is the sheet's "No Rotation"

INTERVALS = (1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120)

def next_due(
    *,
    algorithm: Algorithm,
    count: int,               # already incremented, as the sheet does it
    last_practiced: date,
    ratio: float | None,
    module_dues: Sequence[date],   # for ROTATE and HOLD
    rng: random.Random,
) -> date: ...
```

**Red.** `tests/test_scheduling.py`:

- `NORMAL`, with jitter neutralised by a seeded rng: `count=0` → 1 day;
  `count=8` reads `INTERVALS[8]`, because the count arrives post-increment and
  the sheet does the same; `count=99` gives the 120-day plateau.
- Jitter over 1000 seeded draws stays within ±5% of the table value and never
  produces less than one day, including at `INTERVALS[0]` where a −5% jitter
  would otherwise round to zero.
- **Rounding matches the sheet.** Apps Script's `Math.round` is half-up;
  Python's `round` is banker's, so `round(2.5)` is `2` and the two implementations
  drift apart on exact halves. Use `math.floor(x + 0.5)`, and pin it with a test
  at `2.5` and `-0.5`.
- `SHORT` and `LONG` scale the whole table by 0.5 and 1.5 with `ceil`, so
  `LONG` plateaus at 180 and `SHORT` at 60, and neither drops below a day.
- Tempo: `ratio=0.8` gives 0.8× the interval; `ratio=None` does not scale;
  `ratio=1.0` is unchanged; a ratio above 1 cannot arrive because `Tempo` caps
  it, asserted anyway so the cap cannot quietly move.
- The order of operations is jitter first, then the tempo scaling, then
  `max(1, …)`, then round — which deliberately does **not** match the sheet:
  `bass.gs` floors before it scales, which was safe while scaling could only
  stretch and stops being safe now that a ratio shrinks. The floor moving
  after the scaling is part of the scaling fix in `00-practice-app.md`. A test
  with a fixed seed pins the exact date so a later reordering is visible.
- `ROTATE`: the latest date in `module_dues` plus a random −1…+2 days. The
  exercise's own current due date is **included**, because the sheet's max scan
  includes it — a row already at the back of the queue rotates from its own
  date, not the runner-up's. With an empty `module_dues`, falls back to
  `last_practiced` (the sheet rotates from epoch 1970 here; a bug, not a
  behaviour).
- `HOLD`: the earliest of `module_dues` minus a day, applied **only if it brings
  the date forward** — an exercise already due sooner keeps its date. Here the
  exercise's own due date is **excluded**, because the sheet's min scan skips
  the current row; a test pins that passing it in would be wrong. With no other
  dated rows the date is left unchanged (the sheet would write 9999-12-30;
  also a bug, not a behaviour).

**Green.** `domain/scheduling.py`. One dispatch on the enum, five small
functions, no I/O.

### Step 4 — Repository

**Red.** `tests/test_session.py` (first half), against a temp database:

- `create_module`, `create_exercise`, `get_exercise`, round-tripping pydantic
  models with `target_bpm` and a null `target_bpm`.
- `exercises_due(module, on=date)` returns rows `ORDER BY next_due`, nulls last,
  archived rows excluded. This is `bassReorder`, and it is a query.
- `module_dues(module, excluding=None)` returns the dates the scheduler needs.
  `excluding` takes the row being scheduled: HOLD passes it, ROTATE does not —
  the sheet's two scans disagree on exactly this, and the port keeps both.
- Writes go through a `with transaction(conn):` helper that rolls back on an
  exception, asserted by raising inside one and finding the row absent.

**Green.** `db/repository.py`, `domain/models.py`.

### Step 5 — Marking an exercise done

The knot the whole app pulls on. `doneExercise_` did five things at once and the
port keeps them in one transaction.

```python
def mark_done(
    conn, *, exercise_id: int, algorithm: Algorithm, now: datetime,
    rng: random.Random, notes: str | None = None,
) -> DoneResult   # updated exercise + closed entry + opened entry
```

**Red.**

- Count +1, `last_practiced = now.date()`, `next_due` from step 3.
- The open entry for the current day is closed at `now`, and a new one opened
  at `now` — the running clock the sheet kept by writing `FROM` into the next
  row.
- The closed entry snapshots `description`, `speed`, `bpm` and `log_group`;
  renaming the exercise afterwards leaves the entry unchanged.
- No open entry (first thing after opening the app) → a day is started
  implicitly and the entry runs from that moment, rather than raising.
- No day at all → `start_day` is called for the day `now` falls in.
- An open entry left over from an **earlier day** — the running clock nobody
  stopped — is discarded when a later day starts, not closed at some invented
  time. It is the ported dangling FROM row: time that was never attributed.
- An exception mid-way leaves the exercise's count unchanged: the whole thing is
  one transaction.

**Green.** `domain/session.py`.

### Step 6 — Days, totals and the 4am boundary

**Red.**

- `practice_day_for(now)` puts `01:30` on the previous calendar day and `04:30`
  on a new one — `END_OF_DAY_HOUR = 4`, declared but never used in `Code.gs`.
- An entry that starts at `23:50` and ends at `00:20` belongs entirely to the
  day it started in, and its duration is 30 minutes, not negative.
- `day_summary(day)` returns per-log-group durations and a day total. Against
  the sample in `docs/raw/BASS.csv`, `2026-07-05` gives `TECHNIQUE 00:19`,
  `REPERTOIRE 00:34`, total `00:53` — the numbers the spreadsheet formulas
  produced, so if the port is right they come out equal.
- Log groups need not be contiguous: a day going TECHNIQUE, REPERTOIRE,
  TECHNIQUE sums both TECHNIQUE entries into one subtotal, which is what
  `compressRowsToRanges_` was for and what a `GROUP BY` is for.
- A still-running entry (`ended_at IS NULL`) counts up to `now` in the summary
  and does not break the total — but only when it belongs to the day `now`
  falls in. A stale open entry in an earlier day adds nothing to that day's
  totals; it is the row step 5 discards.

**Green.** Durations computed in SQL or in Python, never stored.

### Step 7 — The importer

**Red.** `tests/test_importer.py`, against the real files in `docs/raw/`:

- They are **tab**-separated despite the `.csv` extension, and carry a long tail
  of empty columns on every row. `csv.reader(f, delimiter="\t")`.
- **Module sheets**: the file name gives the module (`BASS SONGS` → `SONGS`,
  instrument `bass`), and the first header cell gives the log group
  (`REPERTOIRE`) — that is the `A1` the script read. Four exercises come out
  with their speeds, counts and dates; `speed` is kept verbatim, `66/1`
  included; `target_bpm` is left null, since the sheet has no such column and
  `80%` says nothing about what 100% is.
- **The day log**: `DAY` is only on the first row of a block, so it forward-fills;
  `MODULE` likewise, and a blank means "same as the row above" *within the
  block*. `MODULE SUBTOTAL` and `DAY TOTAL` are formula results and are ignored,
  because they are recomputed.
- Entries tile `FROM`→`TO`; a `TO` earlier than its `FROM` means the session
  crossed midnight and the end takes the next calendar day.
- A description with a trailing parenthetical splits back into description and
  note — `019 Tempo Builder (random tempo…)` is the round trip of
  `values[0][COL_BASS_DESC] += " (" + notes + ")"`. Nested or unbalanced
  brackets stay in the description untouched.
- An entry whose description matches an exercise in the imported modules is
  linked to it; one that does not is kept as an ad-hoc entry with a null
  `exercise_id`, never dropped.
- The `2026-07-09` block pins the awkward case: "le freak" is a SONGS exercise,
  but the blank MODULE forward-fills TECHNIQUE over its row, and the sheet's
  own subtotal (01:07 — the whole day) agrees. The entry links to the exercise
  **and** keeps the file's log group: snapshots come from the log, never from
  the exercise the entry points at.
- The last row of a block may carry only a `FROM` — the dangling stamp the
  running clock writes into the next row (`22:31` in the sample). Expected
  structure, not a mangled row: skipped silently, never reported.
- **Idempotent**: a second run over the same files changes nothing. Natural key
  is `(day, started_at)` for entries and `(module, name)` for exercises — the
  partial unique index in the schema enforces the latter, so a rerun conflicts
  instead of duplicating.
- Rows that cannot be parsed are collected into a report and returned, never
  dropped in silence and never fatal. The test asserts a deliberately mangled
  row appears in the report and the rest still import.

**Green.** `importer/sheets.py`, driven by
`uv run practice import --day-log BASS.csv --modules "BASS *.csv"`.

### Step 8 — The CLI

Thin: every command is a few lines over the domain. It exists to prove the
domain before HTML, and it stays useful afterwards.

```
uv run practice day new
uv run practice next [MODULE]                  # due, oldest first
uv run practice done EXERCISE [--short|--long|--rotate|--hold]
uv run practice log [--day today]              # the block, with subtotals
uv run practice add MODULE NAME --speed 80% --target-bpm 133
uv run practice speed EXERCISE 85%
uv run practice import --day-log … --modules …
```

**Red.** `tests/test_cli.py` with click's `CliRunner` over a temp database:
`done` prints the new due date and the log line; `next` orders by due date and
says how many days overdue; tempo renders as `88 BPM (66%)` in both dialects and
as the raw text when it cannot be parsed; `log` renders the day block in the
same shape as the sheet, subtotals included; an unknown exercise name exits
non-zero with a message listing near matches, and a name found in two modules
exits non-zero naming both — `MODULE/NAME` disambiguates.

**Green.** `cli.py`, a click group registered as
`practice = "music_tools.cli:practice"`. The clock and rng are constructed here
and passed down — the only place in the codebase that calls `datetime.now()`.

### Step 9 — `docs/initial-context.md`

AGENTS.md tells every agent to read it before doing anything and it has never
existed. Now there is something to write down: the domain vocabulary (module,
log group, style, exercise, entry), the tempo grammar, the schema, the
injected-clock-and-rng rule, and the boundary between `domain/` (pure) and
`db/` (I/O). Written last in this phase, when the vocabulary has stopped moving.

## Verification

Beyond the suite, on the real export:

1. Import the full sheet export, not just the samples in `docs/raw/`.
2. `uv run practice log --day 2026-07-05` against the spreadsheet's own row
   block: same entries, same subtotals, same total.
3. `uv run practice next SONGS` against the sheet sorted by `DUE`: same order.
4. Mark something done in both, and compare the new due dates — allowing for
   jitter, since each side draws its own: ±5% of the interval for the table
   algorithms, −1…+2 days for Rotate. At full speed the dates must land within
   the shared jitter band; anything under target comes back sooner, by the
   scaling fix in `00-practice-app.md`. A difference the bands cannot explain
   is a bug.

## Out of scope

No HTTP, no HTML, no loops. `target_bpm` backfill is a Phase 3 chore, done
through the module view rather than a script.
