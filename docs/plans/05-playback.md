# Phase 5 — Playback

**Phase 5 of `docs/plans/00-practice-app.md`.** Depends on Phase 4: an
exercise carries a local audio or video file, and starting it puts a card in
the day log for the player to live on. Wishlist stage: direction now,
red/green detail when the phase starts.

The phase splits in two, and 5a is worth stopping at.

## Goal

**5a — one file.** The attached file plays in the page the way Transcribe!
plays it: a waveform with the playhead moving along it, click to seek, slow it
down without losing pitch, shift the pitch without losing speed.

**5b — several files at once.** A tune attached as 3–8 tracks — stems split
out of one recording, or a backing track beside a click — plays as one
transport with a mixer strip: per-track mute, solo, gain and pan, every track
locked to one clock. Audacity's playback, without any of its editing.

**Done when** a started exercise's tune plays from its log card — waveform,
playhead, speed and pitch controls — the speed the slider shows is the speed
the schedule reads (5a), and a set of up to eight stems plays from one
transport with no audible drift between them over the length of a tune (5b).

## Decisions

- **Two stages, two engines, and the second one absorbs the first.** 5a is
  `<audio>` with a plain URL: the browser already streams, seeks, loops and
  reports position, and the waveform is drawn from server-computed peaks, so
  nothing there needs Web Audio. 5b cannot use it — see the next bullet — so
  the multitrack player is a Web Audio graph, and the single-file case becomes
  a track set of one rather than a second engine kept alive beside it.
- **Several `<audio>` elements will not stay in sync, which is what forces Web
  Audio.** Each element carries its own clock and its own resampler: starts
  land tens of milliseconds apart and the gap grows over a tune. Between stems
  split out of one recording that is not a rough edge, it is comb filtering,
  and it is audible within seconds. Web Audio removes the problem by
  construction: fetch each track, `decodeAudioData`, one `AudioContext`, one
  `AudioBufferSourceNode` per track, every `start(t0, offset)` called against
  the same clock with the same offset. Sample-locked for as long as it plays.
  Per-track `GainNode` and `StereoPannerNode` give mute, solo, level and pan;
  the playhead reads `ctx.currentTime - t0`; seek stops every source and
  restarts them at the new offset; loop is identical `loopStart` / `loopEnd`
  on all of them, which keeps the lock across the seam.
- **Decoded audio is the budget, and the cap is eight tracks.** Decoded PCM is
  float32 — roughly 350 KB per second per stereo track at 44.1 kHz, so eight
  tracks of a four-minute tune is around 680 MB held in memory. Downmixing set
  members to mono halves that, and decoding at 22.05 kHz through an
  `OfflineAudioContext` halves it again, bringing the worst case under 200 MB.
  So: mono by default for members of a set, stereo for a lone file, and the
  eight-track cap enforced where tracks are attached rather than discovered in
  the browser. Decoding eight files takes seconds and needs a progress state,
  not a frozen page.
- **Speed stops being `playbackRate` and becomes a server-side render.** This
  is the real cost of 5b. `AudioBufferSourceNode.playbackRate` shifts pitch
  along with rate and there is no `preservesPitch`, so the slower-but-in-tune
  trick 5a gets free from the media element is not available in Web Audio.
  Render it instead, down the same ffmpeg path and into the same cache the
  pitch shift already needed — `rubberband` where the build has it, the
  `asetrate`/`atempo` pair where not — and play everything back at rate 1.0.
  One pipeline then covers both speed and pitch, and every track in a set goes
  through one job so they come back the same length. The price is that moving
  the slider costs seconds instead of nothing: pre-render the speeds that get
  used (60, 70, 80, 90, 100%) when the media is attached, and the common moves
  are cache hits.
- **The slider still means the exercise's speed.** Unchanged: bound to the
  exercise's tempo `ratio`, and moving it edits `speed` in the exercise's own
  dialect — a percentage stays a percentage, a BPM stays a BPM, `123` is never
  silently rewritten to `80%`. No `target_bpm` means no ratio: the slider sits
  at 1.0, disabled, wearing the same flag the module view uses, until the
  target is filled in.
- **Audio only, even when the file is a video.** An `.mp4` attachment plays
  through the same player: ffmpeg extracts the audio once into the render
  cache, and the page never shows a video element. The picture is not the
  practice material; the sound is.
- **A render cache, keyed by content.** Extractions, speed renders, pitch
  renders and later Phase 7's outputs are pure functions of (file,
  parameters). Key them by a hash of both, keep the files under the app data
  directory, and let them be deleted at any time; regenerating is seconds. A
  set renders member by member under one set of parameters, so a set is never
  half at one speed and half at another.
- **Range requests are not optional for 5a.** Safari will not play audio it
  cannot range-request: `Accept-Ranges: bytes`, 206 with a correct
  `Content-Range`, 416 past the end. 5b fetches whole files into
  `ArrayBuffer`s and does not need ranges, but the route stays — 5a uses it,
  video sources use it, and it costs nothing to keep. Only files under the
  cache directory and the configured roots are served, the same guard as every
  other path in.
- **Rejected: `MediaElementAudioSourceNode`.** Feeding N `<audio>` elements
  into one Web Audio graph keeps `preservesPitch` and streams instead of
  decoding, so it is cheap on memory and leaves the speed slider instant. It
  does not fix sync — the elements still each run their own clock — so it buys
  the wrong half of the problem.
- **Rejected: mixing on the server.** ffmpeg `amix` per gain vector, one file
  out, plain `<audio>`: perfect sync, no client complexity. But then every
  mute toggle is a re-render and a reload, which is the wrong feel for the
  control that gets used most. Kept in mind as the fallback if the Web Audio
  path disappoints, and Phase 7 renders its mix this way regardless.
- **The JS stops being a small island, and there is no way to test it.** A1
  holds — no framework, no Node, no `package.json` — but the mixer, scheduler
  and waveform lanes are several hundred lines of hand-written JS carrying the
  phase's riskiest logic (scheduling, seek while playing, drift), and this
  repo has no JS test runner and no way to add one without a Node toolchain.
  Keep the scheduling in one module with no DOM in it so it reads on its own,
  and verify by the checklist below. Recorded as a known gap rather than
  solved.

## Shape

```
music_tools/
    domain/render.py           # cache key, render-or-hit, eviction
    domain/waveform.py         # peaks: min/max pairs, cached, per track
    web/routes/media.py        # serving, ranges, the roots guard
    web/static/player.js       # 5a: waveform, playhead, transport, sliders —
                               # the app's first JS island beyond htmx
    web/static/transport.js    # 5b: the AudioContext, scheduling, seek, loop —
                               # no DOM in it, so it can be read on its own
    web/static/mixer.js        # 5b: the strip, the lanes, mute/solo/gain/pan
```

## Steps

**5a — one file.**

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
6. **The speed slider** — `playbackRate` with `preservesPitch`, bound to
   `ratio`, written back through the dialect rules above. Half speed here is
   Phase 6's tapping aid.
7. **Pitch shift** — the cached shifted render, a semitone control, and an
   honest look at whether the quality is usable.

**5b — several files.**

8. **Speed as a render** — the ffmpeg tempo path into the same cache, the
   pre-rendered ladder of common speeds, and the slider rewired to swap the
   source instead of setting `playbackRate`. Needs no mixer, and proves the
   expensive half of 5b against a single file first.
9. **The transport** — `AudioContext`, decode with progress, `start(t0,
   offset)` across N sources, position, seek, loop, and a drift check: play a
   set the length of a tune and confirm the sources still agree with the clock
   at the end.
10. **The mixer** — gain, pan, mute and solo per track, the state living in
    the `media_source` columns Phase 4 adds so a mix survives a reload.
11. **The lanes** — one waveform per track, stacked under a shared playhead
    and a shared time axis, peaks fetched per track.
12. **The budget** — mono downmix and the reduced decode rate for set members,
    the eight-track cap enforced on attach, and a measurement of what eight
    four-minute stems actually cost in a real browser.

## Verification

There is no JS suite, so 5b is verified by hand, and this list runs again
after any change to the transport:

- Eight stems of one recording played whole: no flanging, no drift audible
  against the start, sources still agreeing with the clock at the end.
- Seek while playing, repeatedly, then seek while paused: every track lands
  together.
- Loop over a short span: the lock survives the seam.
- Mute and solo while playing: no click, no shift in position.
- Speed change while playing: the render swaps and playback resumes where it
  was, at the new speed and the same pitch.

## Out of scope

- Markers and tapping — Phase 6.
- Segment sequencing and export — Phase 7.
- Editing audio — trimming, splitting, fades, anything that writes a track
  back. This is Audacity's playback, not Audacity.
- Showing video, recording yourself, a metronome track.
- More than eight tracks, and tracks of unequal length.
