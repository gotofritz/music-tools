# Phase 5 — Playback

**Phase 5 of `docs/plans/00-practice-app.md`.** Depends on Phase 4: an
exercise carries a local audio or video file, and starting it puts a card in
the day log for the player to live on. Wishlist stage: direction now,
red/green detail when the phase starts.

## Goal

The attached file plays in the page the way Transcribe! plays it: a waveform
with the playhead moving along it, click to seek, slow it down without losing
pitch, shift the pitch without losing speed.

**Done when** a started exercise's tune plays from its log card — waveform,
playhead, speed and pitch controls — and the speed the slider shows is the
speed the schedule reads.

## Decisions

- **`<audio>` with a plain URL for transport, not the Web Audio API.** The
  browser already streams, seeks, loops and reports position; Web Audio buys
  sample-accurate scheduling nothing here needs, at the cost of decoding whole
  files into memory and rebuilding transport by hand. The waveform is drawn
  from server-computed peaks, so it does not need Web Audio either.
- **Audio only, even when the file is a video.** An `.mp4` attachment plays
  through the same audio player: ffmpeg extracts the audio once into the
  render cache, and the page never shows a video element. The picture is not
  the practice material; the sound is.
- **A render cache, keyed by content.** Extractions — and later the
  pitch-shifted renders, and Phase 7's outputs — are pure functions of
  (file, parameters). Key them by a hash of both, keep the files under the app
  data directory, and let them be deleted at any time; regenerating is
  seconds. This is the cache the earlier playback plan designed for loop
  outputs, arriving one phase earlier, for extraction.
- **Range requests are not optional.** Safari will not play audio it cannot
  range-request: `Accept-Ranges: bytes`, 206 with a correct `Content-Range`,
  416 past the end. Only files under the cache directory and the configured
  roots are served — the same guard as every other path in.
- **Speed is `playbackRate`, and it is the exercise's speed.**
  `preservesPitch = true`, since the point is to play along. The slider is
  bound to the exercise's tempo `ratio`, and moving it edits `speed` in the
  exercise's own dialect — a percentage stays a percentage, a BPM stays a BPM,
  `123` is never silently rewritten to `80%`. No `target_bpm` means no ratio:
  the slider sits at 1.0, disabled, wearing the same flag the module view
  uses, until the target is filled in.
- **Pitch shift is a server-side render, not a browser trick.** Browsers give
  rate-preserving-pitch, not pitch-preserving-rate; doing it in the page means
  Web Audio plus a DSP library, which is the no-framework rule bending.
  Instead render a shifted copy through ffmpeg into the cache — `rubberband`
  where the build has it, the `asetrate`/`atempo` pair where not — and swap
  the player's source. Semitone steps, like Transcribe!. Feasibility and
  quality to be proven; this is the most wishlist item of the phase.

## Shape

```
music_tools/
    domain/render.py           # cache key, render-or-hit, eviction
    domain/waveform.py         # peaks: min/max pairs, cached
    web/routes/media.py        # serving, ranges, the roots guard
    web/static/player.js       # waveform, playhead, transport, sliders —
                               # the app's first JS island beyond htmx
```

## Steps

1. **The render cache** — stable keys off content and parameters, render-or-
   hit, regeneration when the file is deleted underneath, eviction that leaves
   the database alone.
2. **Serving audio** — ranges, content types, the roots guard, and a 409
   naming the path when the source file has gone missing rather than a stack
   trace.
3. **Extraction** — video in, cached audio out, through the cache.
4. **Peaks** — `peaks(path, buckets)` as min/max pairs over pydub's raw
   samples, cached beside the renders and keyed the same way; mono and stereo
   give the same shape of output. No numpy for a 2000-bucket reduction of a
   snippet.
5. **The player** — waveform drawn from peaks, playhead from `timeupdate`,
   click to seek, a loop toggle. One `player.js` island; everything around it
   stays fragments.
6. **The speed slider** — bound to `ratio`, written back through the dialect
   rules above. Half speed here is Phase 6's tapping aid.
7. **Pitch shift** — the cached shifted render, a semitone control, and an
   honest look at whether the quality is usable.

## Out of scope

- Markers and tapping — Phase 6.
- Segment sequencing and export — Phase 7.
- Showing video, recording yourself, a metronome track.
