# Phase 7 — Segments

**Phase 7 of `docs/plans/00-practice-app.md`.** Depends on Phase 6: the tune
is marked. This is `loop.py`'s job rebuilt in the page — the same engine, none
of the YAML. Wishlist stage: direction now, red/green detail when the phase
starts.

## Goal

Build a practice file by pointing at the waveform: pick marked spans, put them
in a sequence, repeat some, silence some — the same passage over and over with
chosen bars replaced by silence of exactly the same length — then render it
and export the result as a new sound file.

**Done when** the output `loop.py` builds from a YAML config can be built from
the page instead, from the same markers, played in place and downloaded.

## Decisions

- **The CLI's engine, behind a function.** `loop.py`'s pipeline — markers →
  `Score.build` → spans → pydub — already does everything except take orders
  from a page. The extractions the parked loop-editor plan opened with are
  exactly what is needed, and move here: `root:` defaulting to the config's
  own directory, `build_output(cfg, score, snippet)` split out of `main` so
  nothing shells out to Transcribe! in tests (the launch behind
  `--open/--no-open`), and a `PatternError` the web layer can catch without
  depending on click. The CLI's behaviour does not change; the
  characterisation suite from Phase 1 is what says so.
- **Sequences address markers by name, and resolve at render.** An item is
  "bars 3–6, twice" or "the span UP1, silent", stored as `Score` addresses,
  not as seconds. Markers move — that is what Phase 6 is for — and a sequence
  built on names follows them; one built on seconds would quietly rot.
- **No YAML in the page.** The YAML stays what it is: the CLI's config format,
  written by hand. The sequence tables are not `loop_config` in disguise and
  do not round-trip to it — that round trip was the parked editor's whole
  difficulty, and dropping it is what makes this phase small. If a page-built
  sequence is ever wanted as a file, an export can be added; nothing imports.
- **Rendering goes through Phase 5's cache**, keyed off the sequence and the
  media, served over the same range-capable route, and downloadable from it.
  Drills — the CLI's expansion of one line into eighteen sections — stay a CLI
  feature until the page grows a reason to want them.
- **A track set renders as a mix, and the mix is part of the key.** A sequence
  belongs to a `media_group`, and rendering a set means the members mixed down
  through ffmpeg `amix` at their stored gains and pans, muted tracks left out
  — so "the passage without the bass, four times" is one file, which is the
  point. The gain vector joins the sequence and the file hashes in the cache
  key. `loop.py`'s engine never sees the set: it is handed one mixed snippet,
  exactly as it is today.

## Schema sketch

```sql
CREATE TABLE segment_sequence (
  id INTEGER PRIMARY KEY,
  media_group_id INTEGER NOT NULL REFERENCES media_group(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE segment (
  id INTEGER PRIMARY KEY,
  sequence_id INTEGER NOT NULL REFERENCES segment_sequence(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  from_name TEXT NOT NULL,     -- Score addressing: '3', 'A2', 'UP1', '1.2'
  to_name TEXT,                -- null = the span the name closes itself
  repeat INTEGER NOT NULL DEFAULT 1,
  silent INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX segment_order ON segment(sequence_id, position);
```

## Steps

1. **The engine extractions** — the three changes above, lifted from the
   parked plan with their tests, the characterisation suite watching.
2. **Sequences as data** — the tables, resolution of a sequence against the
   marker source's score into `(start, end, silent)` spans, and errors that
   name the token when an address no longer resolves — the same voice as the
   CLI's.
3. **Render and serve** — sequence in, cached file out through
   `build_output`, played and downloaded over the media route. A set is mixed
   down first, at the mix the page is showing; a group of one skips that step
   and is the case the tests start from.
4. **The UI** — click a marked span on the waveform to add it, reorder, set
   repeats, toggle silent; the resolved timeline drawn under the sequence;
   render, and the player switches to the result. Fragments everywhere; the
   waveform interaction stays inside `player.js`'s island.
5. **The day-log tie-in** — the card of a started exercise reaches its
   sequences, so due → start → loop a passage → done is the whole scenario
   the plan promised, without Transcribe! in the middle.

## Out of scope

- The YAML round trip, the grid, drills in the page — parked with
  `08-loop-editor.md`.
- `rearrange` and its DSL, as ever.
