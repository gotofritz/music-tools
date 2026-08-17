# Phase 4 — Exercise media, and the log rework

**Phase 4 of `docs/plans/00-practice-app.md`.** Read that first for the stack
(FastAPI + Jinja2 + HTMX, no Node), the storage (SQLite, hand-written SQL,
numbered migrations) and the domain (module → exercise → practice entry).
Wishlist stage: the shape below is a direction, and the steps get their
red/green detail when the phase starts.

## Goal

Two changes that belong together, because the second is what makes the first
visible.

**An exercise carries its material.** Today an exercise is a name and a
schedule; the tune itself lives in Transcribe!, in a folder of scores, on
YouTube. Attach it instead: a local audio or video file, a YouTube URL, a
MuseScore file, plain text — or several at once, since one tune can be audio
downloaded from a YouTube URL with the score kept in a separate file beside
it.

**The log stops being a clock.** Today an exercise is unknown to the log until
`done` writes it, and entries tile the session end to end — `done` closes one
and opens the next, `start` drops the gap after a break, "stop the clock" ends
the day. That machinery reproduced the spreadsheet. Now: **start** an exercise
and the entry exists, immediately visible in the day log with the exercise's
media displayed on it; practise; **done** closes the entry and moves the
schedule on. No running clock to mind, nothing to stop.

**Done when** starting an exercise puts it in the day log with its material
showing, done completes it, and `restart_clock` / `stop_clock` are gone.

## Decisions

- **Media is rows; files stay on disk.** A `media_source` row per attachment,
  `kind` saying what it is, path or URL or text saying where. Local files are
  referenced by absolute path, never copied — the rule since Phase 2. Every
  path in from the browser is confined to configured roots (the scores
  directory, the app data directory), the guard the parked loop-editor plan
  specified, and the server stays on `127.0.0.1`.
- **YouTube means embed.** Another app already handles downloading from
  YouTube, so downloading is out of scope here — the two may merge one day,
  and until then the YouTube kind is a URL rendered as an embedded player.
  The accepted cost: that one card needs the network, in an app that
  otherwise works without it. A tune wanted offline is downloaded with the
  other app and attached as a local file, with the URL kept beside it as
  provenance.
- **Display per kind, minimal first.** An audio or video file gets the player
  (Phase 5 makes it a waveform; until then a bare `<audio>`), a YouTube URL
  the embedded player, a MuseScore file a link that opens it locally, and
  text is shown as text. Rendering a score to an image through the MuseScore
  CLI is possible and deferred.
- **Start replaces the tiling, and the old rules get simpler.** An entry's
  time is its own `started_at → ended_at`, stamped by **start** and **done**.
  Gaps between entries are gaps; nothing re-tiles, nothing is invented. One
  entry runs at a time: starting the next closes the running one at that
  instant — it was attributed when it was started, so closing it is honest —
  but only `done` touches the schedule. A false start gets a **discard**
  button on the card. An entry left running from an earlier day is discarded,
  as now: time nobody attributed is still not practice time.
- **The CLI keeps up.** `practice start <exercise>` starts one — repurposing
  the name, since the drop-the-gap meaning dies with the tiling —
  `practice done` completes it, `practice log` shows the open entry. Ad-hoc
  practice (`log_entry`) stays: start with a free-text description instead of
  an exercise.

## Schema sketch

```sql
CREATE TABLE media_source (
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,          -- 'file' | 'youtube' | 'musescore' | 'text'
  path TEXT,                   -- absolute; 'file' and 'musescore'
  url TEXT,                    -- 'youtube': the embed target
  body TEXT,                   -- 'text'
  label TEXT,
  position INTEGER NOT NULL,
  added_at TEXT NOT NULL
);
```

`practice_entry` already has `started_at` / `ended_at`; the change is
behavioural — who writes them and when — not structural.

## Steps

Direction, not yet red/green:

1. **The migration and the repository half** — `media_source`, CRUD in
   `domain/catalogue.py` style, the roots guard on every path in.
2. **The log rework in `domain/session.py`** — `start_exercise`, `done`
   closing the running entry, discard, the day-boundary rule, and the removal
   of `restart_clock` / `stop_clock`. The step with teeth: the session tests
   describe the old tiling and are rewritten to describe the new shape.
3. **The web flow** — the module row's button becomes **start**; the day log
   renders the running entry as a card carrying the media display; **done**
   and **discard** live on the card.
4. **Attaching media from the page** — add, remove and reorder sources on an
   exercise, with path picking confined to the roots.
5. **The YouTube embed** — the URL rendered as the embedded player on the
   card, degrading to a plain link when the network is off.
6. **CLI parity** — `start`, `done`, `log` against the new shape.

## Out of scope

- Waveforms, speed, pitch — Phase 5.
- Markers on any of it — Phase 6.
- Rendering MuseScore files to images.
- Downloading from YouTube — another app owns that; merging the two is a
  possible future, not this phase.
- More than one entry running at once.
