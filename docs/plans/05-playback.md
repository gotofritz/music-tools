# Phase 5 — Play it in the app

**Phase 5 of `docs/plans/00-practice-app.md`.** Depends on Phase 4: there is a
loop, it generates a file, and the browser has been asked to open it in Finder
ever since.

## Goal

Close the scenario. Due → loop → **play** → done, without leaving the page and
without Transcribe! in the middle.

**Done when** a generated loop plays in the browser, the practice clock keeps
running while it does, and the speed slider is the same field the schedule reads.

## Decisions

**`<audio>` with a plain URL, not the Web Audio API.** The browser already
streams, seeks, loops and reports position. Web Audio buys sample-accurate
scheduling that nothing here needs; it costs decoding the whole file into memory
and reimplementing transport controls. Phase 6 needs Web Audio for waveform
drawing and will add it there, for that.

**Generated audio is a cache, not a document.** The output of a loop is a pure
function of (config, snippet). Key it by a hash of both, keep the file under the
app data directory, and let it be deleted at any time — regenerating is seconds.
That is what makes `output:` in the YAML a CLI concern rather than something the
app has to manage.

**`playbackRate` is `ratio`.** The exercise plays at the speed it is recorded as
being practised at, and moving the slider is what edits `speed`. Nothing is
typed into two places. `preservesPitch = true`, since the point is to play along.

## Shape

```
music_tools/
    web/routes/media.py        # preview, range requests, cache
    domain/render.py           # cache key, render-or-hit, eviction
    web/static/player.js       # transport + rate slider, the second JS island
```

## Steps

### Step 1 — The render cache

**Red.** `tests/test_render.py`:

- `cache_key(config, snippet)` is stable across processes and changes when any
  section, repeat, pattern or the snippet's mtime/size changes — parametrised
  over one mutation each.
- `render(config)` writes the file and returns its path; a second call does not
  rewrite it (assert on mtime).
- With the file deleted under it, `render` regenerates rather than raising.
- `evict(older_than)` removes cached files and leaves the database untouched.

**Green.** `domain/render.py` over `build_output` from Phase 4.

### Step 2 — Serving audio

**Red.** `tests/test_media.py`:

- `GET /loops/{id}/preview.wav` is 200, `Content-Type: audio/wav`, and the body
  is the rendered file.
- `Accept-Ranges: bytes` is advertised, and a `Range: bytes=100-199` request
  returns **206** with exactly 100 bytes and a correct `Content-Range`. Safari
  will not play audio it cannot range-request, so this is not optional.
- An out-of-range request returns 416.
- A loop whose snippet has gone missing returns 409 with the path in the
  message, rather than a stack trace.
- Only files under the cache directory and the configured scan roots can be
  served: a crafted path is 403. Same guard as `04`'s `/browse`.

**Green.** `web/routes/media.py`.

### Step 3 — The player

**Red.** `GET /loops/{id}` now includes an `<audio>` with the preview URL and a
rate slider bound to the exercise's `ratio`; `PATCH /exercises/{id}` from a rate
change stores the new speed in the exercise's own dialect — a percentage stays a
percentage, a BPM stays a BPM. That last one is a real test: dragging the slider
on `123` must not silently rewrite it to `80%`. An exercise with no
`target_bpm` has no ratio: the slider renders at 1.0 and disabled, wearing the
same flag the module view uses — there is nothing to scale and no dialect to
write back into. Backfilling the target is what unlocks it.

**Green.** `player.js` plus the template change. Transport is the browser's;
the file adds the rate slider, a loop toggle, and section markers drawn as a
strip under the transport from the resolved spans the page already has.

### Step 4 — Practising against it

**Red.** Playing does not touch the schedule — only `done` does. But the running
practice entry should reflect what is being played: `POST /entries/current`
with a loop id attaches it to the open entry, so the day log reads
"Stomp! (verse slap figure)" rather than just the tune. Assert the entry
snapshots the loop name, and that deleting the loop later leaves the entry
readable.

**Green.** Migration `003_entry_loop.sql`: a nullable `loop_config_id` on
`practice_entry`, `ON DELETE SET NULL` so a deleted loop leaves the entry
readable, plus the snapshot in `description`.

### Step 5 — By hand

Play a real generated loop end to end: seek, loop, half speed, and confirm the
day log ends up with the time in the right module.

## Verification

`pydub` needs ffmpeg for mp3; wav is the safe output format for the cache. The
suite renders from `AudioSegment.silent`, so nothing here needs a real recording
or a working audio device.

## Out of scope

Recording yourself, a metronome track, click-in counts, pitch shifting, and
anything that needs the Web Audio API — except the waveform, which is Phase 6's
problem.
