# Phase 3 — The app, and the cutover

**Phase 3 of `docs/plans/00-practice-app.md`.** Depends on Phase 2: every route
here is a thin call into `domain/session.py`.

## Goal

The spreadsheet stops being used. Practice is driven from a browser page: what
is due, one click to mark it done, a day log that fills itself in with running
totals.

**Done when** a full practice session — open, several exercises, notes, speed
changes — happens without opening Google Sheets, and the day's totals match what
the sheet would have shown.

## Decisions

**FastAPI + Jinja2 + HTMX, server-rendered, no Node** (assumption A1 in the
umbrella). Concretely that means: routes return HTML fragments, not JSON; state
lives in SQLite, not in the page; and `htmx.min.js` is a vendored file in
`static/`, not a CDN link — the app must work with the network off, which is
the point of leaving Sheets.

**Forms work without JavaScript.** Every HTMX action is a real `<form>` with a
real `action` and `method`, progressively enhanced by `hx-post`. HTML forms
only submit GET and POST, so the inline-edit route answers a plain POST as
well as the `PATCH` HTMX sends — one handler, registered twice. This is not
purity: it is what makes the routes testable with `TestClient` and no browser,
and it means a broken JS file degrades to a working app rather than a dead page.

**One page per module, one page for today.** No dashboard, no charts. The
spreadsheet had two useful views and so does this.

## Shape

```
music_tools/web/
    app.py                     # create_app(db_path) factory + uvicorn launcher
    deps.py                    # per-request connection, clock, rng
    routes/
        practice.py            # today, days, entries
        modules.py             # module views, exercises
    templates/
        base.html
        today.html
        module.html
        _entry_row.html        # fragments, one per swappable thing
        _exercise_row.html
        _day_totals.html
    static/
        htmx.min.js  app.css
```

`create_app(db_path)` is a factory so tests get a temp database without
environment variables. `uv run practice serve` launches uvicorn on `127.0.0.1`
and opens a browser.

## Routes

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/` | Today: running log, totals, what is due |
| `GET` | `/modules/{slug}` | The module's exercises, `ORDER BY next_due` |
| `POST` | `/days` | Start a day; the new log fragment |
| `POST` | `/exercises/{id}/done` | Updated exercise row + log + totals (OOB) |
| `POST` | `/entries/{id}/stop` | Close the running entry |
| `PATCH` | `/exercises/{id}` | Inline edit: speed, target, notes, name |
| `POST` | `/exercises` | Add an exercise to a module |
| `POST` | `/entries` | An ad-hoc entry, not tied to any exercise |
| `GET` | `/exercises/{id}/tempo` | Resolved BPM for a typed speed, live |

`POST /exercises/{id}/done?algorithm=normal|short|long|rotate|hold` is the one
that matters. One click changes three things on screen — the exercise's due
date, the day log, the totals — so it returns the exercise row and swaps the
other two out-of-band (`hx-swap-oob`). That is the whole reason for HTMX here:
the alternative is a full page reload after every exercise, which is what the
spreadsheet did and why it was slow.

## Steps

### Step 1 — App factory and an empty page

**Red.** `tests/test_web.py`: `TestClient(create_app(tmp_db))` — `ImportError`.
Then `GET /` is 200 and the response mentions the day's date.

**Green.** `app.py`, `deps.py`, `base.html`, `today.html`. The connection is a
FastAPI dependency opened per request and closed after; the clock and rng are
dependencies too, overridden in tests with `app.dependency_overrides` so a test
can pin "now" without touching global state.

### Step 2 — Today

**Red.**

- With no day started, `GET /` offers "start a day" and no entries.
- After `POST /days`, the page shows one running entry with a start time and no
  end.
- With entries from Phase 2's fixtures, the log renders in start order with
  durations, log-group subtotals and a day total — the same numbers
  `day_summary` returns, asserted against the `2026-07-05` sample.
- The running entry shows a live duration, computed server-side at render.
- `POST /days` twice in one day does not create a second day.

**Green.** `today.html` plus `_entry_row.html` and `_day_totals.html`.

### Step 3 — A module view

**Red.**

- `GET /modules/{slug}` lists exercises ordered by due date, overdue ones marked,
  with speed, count, last practised, due, notes.
- Speed renders as `88 BPM (66%)` when a target exists, as the raw text when it
  does not, and an exercise with no target is visibly flagged — the gap the
  importer leaves gets closed by use rather than as a migration chore.
- An unknown slug is 404.
- An archived exercise is absent.

**Green.** `module.html`, `_exercise_row.html`.

### Step 4 — Done, in one click

**Red.**

- `POST /exercises/{id}/done` is 200; the response contains the recomputed due
  date; the database shows the count incremented and an entry closed.
- The response carries the log fragment and the totals fragment as out-of-band
  swaps — asserted on the markup, since that is the contract with HTMX.
- Each algorithm reaches the right branch: `?algorithm=hold` on the exercise
  with the earliest due date leaves its date alone (there is nothing earlier to
  jump in front of), while `?algorithm=rotate` sends it past the last date in
  the module.
- An unknown id is 404 and writes nothing.
- Posting twice in a row is *not* idempotent — it counts two practices — and a
  test says so, because the obvious "fix" (dedupe by exercise) would break
  practising something twice in a session, which is normal.

**Green.** `routes/practice.py`.

### Step 5 — Editing in place

**Red.**

- `PATCH /exercises/{id}` with `speed=85%` stores it verbatim and the row
  re-renders with the resolved BPM.
- `GET /exercises/{id}/tempo?written=123/2` returns `246 BPM` as a fragment, for
  live feedback while typing; unparseable input returns a quiet "?" rather than
  an error, since it is a keystroke, not a submission.
- Setting `target_bpm` re-resolves every percentage on the row.
- Editing the name does **not** rewrite past log entries, asserted directly.

**Green.** `routes/modules.py`.

### Step 6 — The page itself

**Green** (verified by hand). Layout, keyboard access on the done buttons, a
module switcher, and the running entry visible from every page. Keep `app.css`
hand-written and short. No JavaScript beyond the vendored `htmx.min.js`.

### Step 7 — Cutover

Not code. A checklist:

1. Export every sheet, import for real, and run Phase 2's verification against
   the whole history rather than the samples.
2. Practise from both for a week. The sheet stays authoritative during it.
3. Compare day totals each evening; any mismatch is a bug in the port, not a
   reason to hand-edit the database.
4. Fill in `target_bpm` for the exercises the module view flags, a few at a
   time.
5. Stop opening the sheet. Keep `docs/raw/` as the record of what was replaced,
   and archive the plan docs per AGENTS.md.
6. Turn on `task db:dump` — the spreadsheet gave version history for free and a
   local file does not.

## Verification

A real session, start to finish, with the sheet open beside it for the last
time: same entries, same subtotals, same total, same ordering of what is due.

## Out of scope

Loops (Phase 4), audio (Phase 5), charts, streaks, multi-user, any framework.
Editing the day log's past days is deliberately not offered yet — the CLI can do
it, and a log you can rewrite casually is a log you cannot trust.
