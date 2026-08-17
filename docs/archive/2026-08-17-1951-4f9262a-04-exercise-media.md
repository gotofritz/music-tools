# Phase 4 — Exercise media, and the log rework

**Phase 4 of `docs/plans/00-practice-app.md`.** Read that first for the stack
(FastAPI + Jinja2 + HTMX, no Node), the storage (SQLite, hand-written SQL,
numbered migrations) and the domain (module → exercise → practice entry).

**Done.** All seven steps are built and tested (`music_tools/domain/media.py`,
`music_tools/db/migrations/002_media.sql`, `music_tools/web/routes/media.py`,
`tests/test_media.py`, and the reworked `domain/session.py`). Three notes on
what the build decided where the plan left room:

- **The card lives at the top of the day log**, and the header clock is gone
  rather than repurposed. A module row carries the same **done** and **discard**
  while it is the one running, so a session can be driven from either page.
- **`done` acts on the entry, not on the exercise** (`POST /entries/{id}/done`),
  which is what makes an ad-hoc line finishable by the same button. `practice
  done NAME` with nothing running still schedules the row and logs no time for
  it — practising away from the terminal is normal, and inventing a start time
  is not.
- **Paths are typed, not browsed.** The page names the roots and the domain
  refuses anything outside them; a file browser belongs to the parked
  loop-editor plan. Serving re-checks the roots, because they can be narrowed
  after a row was written.

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
- **Several files can be one thing to play: a track set.** A tune is often
  3–8 files rather than one — stems split out of a recording, a backing track
  beside a click — and they are one player with a mixer strip, not eight
  cards in a row. So a `media_group` row, `media_source` rows pointing at it,
  and the mix state (gain, pan, mute) living on the member. Phase 5b builds
  the player; the grouping lands here because retrofitting it after markers
  hang off individual files is the expensive order. A file with no group is a
  set of one, which is what the bare `<audio>` above plays.
- **Members of a set must agree, and there are at most eight.** Same
  duration within a tolerance, and eight members maximum — Phase 5b holds
  every track decoded in memory at once, and eight four-minute stems is
  already a few hundred megabytes. Both are checked on attach, where the
  message can name the file that disagrees, rather than in the browser where
  it is a stall or a crash.
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
CREATE TABLE media_group (       -- one player over several files; a track set
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  label TEXT,                    -- "stems", "with click"
  position INTEGER NOT NULL,
  added_at TEXT NOT NULL
);

CREATE TABLE media_source (
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES media_group(id) ON DELETE CASCADE,
                               -- required for 'file'; null for the rest
  kind TEXT NOT NULL,          -- 'file' | 'youtube' | 'musescore' | 'text'
  path TEXT,                   -- absolute; 'file' and 'musescore'
  url TEXT,                    -- 'youtube': the embed target
  body TEXT,                   -- 'text'
  label TEXT,                  -- also the track name in a set: "bass", "drums"
  position INTEGER NOT NULL,   -- order in the exercise, or in the set
  gain REAL NOT NULL DEFAULT 1.0,
  pan REAL NOT NULL DEFAULT 0.0,     -- -1 left … +1 right
  muted INTEGER NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL
);
CREATE INDEX media_source_group ON media_source(group_id, position);
```

**Every audio file is in a group, and most groups have one member.** A single
attached file gets a group made for it, so there is one shape downstream
instead of two: Phase 5b plays a set of one, and Phase 6 hangs markers off the
group without caring whether the tune came as stems. Adding a second file to
an existing group is what makes a track set, and it is the only way to make
one. Only `kind = 'file'` carries a `group_id` — a YouTube embed cannot be
sample-locked to anything, and text has no timeline.

Solo is not stored: it is a view over the mute state, and which track is
soloed does not deserve to outlive the page.

`practice_entry` already has `started_at` / `ended_at`; the change is
behavioural — who writes them and when — not structural.

## Steps

Direction, not yet red/green:

1. **The migration and the repository half** — `media_group` and
   `media_source`, CRUD in `domain/catalogue.py` style, the roots guard on
   every path in.
2. **The log rework in `domain/session.py`** — `start_exercise`, `done`
   closing the running entry, discard, the day-boundary rule, and the removal
   of `restart_clock` / `stop_clock`. The step with teeth: the session tests
   describe the old tiling and are rewritten to describe the new shape.
3. **The web flow** — the module row's button becomes **start**; the day log
   renders the running entry as a card carrying the media display; **done**
   and **discard** live on the card.
4. **Attaching media from the page** — add, remove and reorder sources on an
   exercise, with path picking confined to the roots.
5. **Track sets** — add a file to an existing group, name the members, order
   them, and reject a set whose members disagree on length or run past eight.
   Storage and validation only; the set renders as stacked `<audio>` elements
   until Phase 5b, which is honest about being unsynchronised rather than
   pretending otherwise.
6. **The YouTube embed** — the URL rendered as the embedded player on the
   card, degrading to a plain link when the network is off.
7. **CLI parity** — `start`, `done`, `log` against the new shape.

## Out of scope

- Waveforms, speed, pitch — Phase 5.
- Playing a track set in sync, and the mixer that goes with it — Phase 5b.
  This phase only stores the grouping and the mix state.
- Markers on any of it — Phase 6.
- Rendering MuseScore files to images.
- Downloading from YouTube — another app owns that; merging the two is a
  possible future, not this phase.
- More than one entry running at once.
