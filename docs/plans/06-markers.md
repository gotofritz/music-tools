# Phase 6 — Markers

**Phase 6 of `docs/plans/00-practice-app.md`.** Depends on Phase 5: the file
plays in the page, its position is readable, and half speed exists. Wishlist
stage: direction now, red/green detail when the phase starts.

## Goal

Mark up a tune in the app — tap bars and beats against the waveform, drag them
straight, name the cues — instead of doing it in Transcribe! and exporting a
`.txt`. Let the app guess a first draft where it can. Export exactly the
format Transcribe! writes, so nothing is ever locked in.

**Done when** a bare audio file can be marked up entirely in the browser, the
markers survive a round trip through the Transcribe! `.txt` format, and an
imported tune's markers can be corrected in place rather than re-exported.

## Decisions

- **Markers hang off the media file, not off a loop config.** The earlier
  marker plan attached them to the loop editor's configs; that editor is
  parked, and markers were never really the loop's anyway — they describe the
  recording. A marker set belongs to a `media_source`, and everything
  downstream (Phase 7's segments) reads it from there.
- **Markers become rows; the file becomes an import format.** `parse_markers`
  reads a `.txt`; the database becomes a second source feeding the same
  `list[tuple[float, str, str]]` into the same `Score.build`, so nothing
  downstream of `Score.build` changes. One thing inside it does: `build`
  anchors the score by shifting every timestamp back by the first marker's —
  right for a Transcribe! file, whose times are the original track's, wrong
  for taps, which are file-relative already. `build` grows a `shift` argument
  defaulting to today's behaviour, and app-origin sources pass `0.0`.
- **Transcribe! import stays forever, and export is exact.** Every tune
  already marked lives there. `kind` keeps Transcribe!'s own vocabulary —
  `section`, `measure`, `beat`, `textblock` — so the `.txt` round trip is a
  straight mapping, lossless, and pinned by a round-trip test.
- **Guessing is a draft, not an authority.** Beat and bar estimation writes
  ordinary marker rows, immediately draggable and deletable — corrected with
  the same tools tapping uses. It starts as a spike: can an off-the-shelf beat
  tracker place bars usefully on real tunes? `librosa` is the candidate and a
  heavy dependency — numpy, scipy, numba — to weigh against `aubio` or a
  hand-rolled onset picker. Timeboxed; if it cannot, tapping remains the way
  in and nothing else in the phase has moved.

## Schema sketch

```sql
CREATE TABLE marker_source (
  id INTEGER PRIMARY KEY,
  media_source_id INTEGER NOT NULL REFERENCES media_source(id) ON DELETE CASCADE,
  origin TEXT NOT NULL,             -- 'transcribe' | 'app' | 'guessed'
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

## Steps

1. **Markers from the database** — `to_entries(source)` returns what
   `parse_markers` returns, asserted by building one score from `d51.txt` and
   one from rows imported out of it and comparing bars, beats, text blocks and
   durations. The `shift` rule pinned by a first tap at 0.4 s that must not
   slide.
2. **Editing as data, before any UI** — add, move, delete, relabel (`END`
   stays reserved), renumber to `Score.build`'s own defaults. Every edit
   leaves a buildable score or fails inside its transaction; an edit that
   merely breaks a downstream span re-resolves and reports, never refuses.
3. **The routes** — insert, move, relabel, delete, and a batch endpoint for
   taps, because four bars tapped is four events in two seconds and a request
   each is silly. Every response carries re-resolved spans, so the page can
   show immediately what a moved bar line broke.
4. **The tapping UI** — play; `B` taps a bar, `space` a beat, `T` drops a
   named cue. Taps land at the audio's `currentTime` minus a latency
   calibration with a sane default. Markers draw on the waveform, drag to
   nudge, click to rename, half speed while tapping.
5. **Guessing** — the spike above, then a **guess** button that proposes
   beats and bars as a `guessed` source to accept, thin out or drag straight.
6. **Export** — `export_markers(source)` writes Transcribe!'s format exactly
   (`0:00:12.191723 Marker (section): "A"`), and re-importing the written
   file gives back the same markers. The round trip keeps the phase honest.

## Verification

Take a tune with no markers, tap in eight bars, drag the crooked ones
straight, export, open the `.txt` in Transcribe!, and confirm it agrees. Then
let the guesser try the same tune and count how many of its bars survive.

## Out of scope

- Building anything from the markers — Phase 7.
- Chord detection, key detection, alignment to a click, anything score-aware.
