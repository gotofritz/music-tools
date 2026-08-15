# Phase 6 — Markers without Transcribe!

**Phase 6 of `docs/plans/00-practice-app.md`.** Depends on Phase 5: audio plays
in the page and its position is readable.

## Goal

Mark up a snippet in the app — tap the bars, tap the beats, name the cues —
instead of exporting a `.txt` from Transcribe! and uploading it. A loop can then
be built for a tune that has never been through Transcribe! at all.

**Done when** a new tune goes from a bare audio file to a working loop without
leaving the browser, and an existing tune's imported markers can be corrected in
place rather than re-exported.

## Decisions

**Markers become rows; the file becomes an import format.** Up to now
`parse_markers` reads a file and `Score.build` turns entries into a score.
Phase 6 adds a second source — the database — feeding the same
`list[tuple[float, str, str]]` into the same `Score.build`. Nothing downstream
of `Score` changes, which is what makes this phase small: the score is already
the boundary.

**Transcribe! import stays forever.** Every tune already marked lives there, and
the app is not going to be better at tapping along than a tool built for it.
Export stays too — a `.txt` written back out means the app never becomes a
place data can only go into.

**Web Audio arrives here, for the waveform only.** Transport stays on
`<audio>` from Phase 5. Peaks are computed once, server-side, and stored — a
waveform is a picture of the file, not something to recompute per page load.

## Schema

```sql
CREATE TABLE marker_source (
  id INTEGER PRIMARY KEY,
  loop_config_id INTEGER NOT NULL REFERENCES loop_config(id) ON DELETE CASCADE,
  origin TEXT NOT NULL,             -- 'transcribe' | 'app'
  imported_from TEXT,               -- the .txt it came from, if any
  offset_seconds REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE marker (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES marker_source(id) ON DELETE CASCADE,
  at_seconds REAL NOT NULL,
  kind TEXT NOT NULL,               -- 'section' | 'measure' | 'beat' | 'textblock'
  label TEXT NOT NULL DEFAULT ''
);
CREATE INDEX marker_order ON marker(source_id, at_seconds);
```

`kind` uses Transcribe!'s own vocabulary rather than a tidier one, so
`to_entries()` is a straight mapping and a round trip through the `.txt` format
is lossless. `offset_seconds` records the shift `Score.build` applies when
markers come from a file whose timestamps are the original track's; markers
tapped in the app are already snippet-relative and have an offset of 0.

## Steps

### Step 1 — Markers from the database

**Red.** `tests/test_marker_source.py`:

- `to_entries(source)` returns what `parse_markers` returns for the same
  markers, so `Score.build` accepts either — asserted by building a score twice,
  from `d51.txt` and from rows imported out of it, and comparing bars, beats,
  text blocks and durations.
- Import of a `.txt` records `origin='transcribe'` and the file it came from.
- A source with no bar markers raises the same message as the file path does.

**Green.** Migration `004_markers.sql`, `domain/markers_db.py`. `loop_config`
gains a nullable `marker_source_id`; `marker_path` stays for configs still
pointing at a file, and a config may have exactly one of the two.

### Step 2 — Editing markers as data

**Red.** Before any UI, the operations:

- `add_marker(source, at, kind, label)` inserts in time order.
- `move_marker(id, to)` and `delete_marker(id)`.
- `relabel(id, label)`; a label that would shadow the reserved `END` is
  rejected with the reason.
- `renumber(source)` fills unlabelled bars as `1, 2, 3…`, the same default
  `Score.build` applies, so the two never disagree.
- Every one of these leaves a score that still tiles the snippet with no gaps.

**Green.** Repository functions plus the guard that a score is rebuilt and
validated inside the same transaction, so an edit that would break every pattern
in the config fails before it lands.

### Step 3 — Waveform peaks

**Red.** `peaks(path, buckets=2000)` returns that many min/max pairs, is stable
across runs, and is cached beside the render cache from Phase 5, keyed on the
file's size and mtime. A mono and a stereo file give the same shape of output.

**Green.** `domain/waveform.py` over `pydub`'s raw samples. No new dependency —
`numpy` would be faster and is not needed for a 2000-bucket reduction of a
30-second snippet.

### Step 4 — Tapping

**Red.** The routes, tested without a browser:

- `POST /loops/{id}/markers` with `{at, kind, label}` inserts and returns the
  redrawn marker strip.
- `PATCH /markers/{id}` moves or relabels; `DELETE /markers/{id}` removes.
- `POST /loops/{id}/markers/tap` accepts a batch — a whole take of taps arrives
  as one array, because tapping four bars means four events in two seconds and a
  request each is silly.
- Every one of them returns the re-resolved spans for the config's patterns, so
  the page can show immediately that moving a bar line broke `[JOHN-3.2]`.

**Green.** `web/routes/markers.py`.

### Step 5 — The marking UI

**Green** (verified by hand). Play the snippet; `B` taps a bar, `space` taps a
beat, `T` drops a text block and asks for a name. Taps land at the audio's
`currentTime` minus a calibration offset for input latency, which is a setting
with a sane default. Markers draw on the waveform, drag to nudge, click to
rename. A "half speed while tapping" toggle, since tapping 16ths at tempo is how
markers end up crooked.

Then: the same page already edits sections, so a new tune goes audio → taps →
grid → generate without a second tool.

### Step 6 — Export

**Red.** `export_markers(source)` writes the Transcribe! format exactly —
`0:00:12.191723 Marker (section): "A"` — and re-importing the written file gives
back the same markers. That round trip is the test that keeps this phase honest.

**Green.** A formatter, and `GET /loops/{id}/markers.txt`.

## Verification

Take a tune with no markers at all, tap in eight bars, build a loop, play it,
and check the bar lines land where the ear says they do. Then export, open the
`.txt` in Transcribe!, and confirm it agrees.

## Out of scope

Beat detection, tempo estimation, alignment to a click, and any attempt to
guess bars from the audio. Tapping is the feature; automatic marking is a
different project and a much larger one.
