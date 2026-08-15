# Practising with music-tools — a user guide

This guide is for playing, not programming. It assumes you can open a
Terminal window and type into it, and nothing else.

## What the tool does

You have a tricky four bars. You can play them slowly. You cannot play them
in time, and you cannot play them without looking.

`loop` takes a short piece of audio and builds a practice track from it: the
same passage, over and over, with bits of it replaced by silence. The silence
is the point. Where the recording stops, you keep playing, and the next time
it comes back in you find out whether you were still in the right place.

Nothing is stretched or slowed down. Silence is exactly as long as the audio
it replaces, so the pulse never moves.

## What you need

- **A snippet.** A few seconds of the tune, cut out as a `.wav` or `.mp3`.
- **A marker file** (optional, but it is what makes everything below work).
  This is a text file exported from
  [Transcribe!](https://www.seventhstring.com/xscribe/overview.html), saying
  where each bar and each beat falls in your snippet.
- **A settings file.** A short text file, ending in `.yml`, where you say
  what you want. This guide is mostly about writing that.

Ask a developer to do the one-off setup on page
[README.md](../README.md#setup) first. After that you only ever type one
command.

## Marking up the snippet

In Transcribe!, drop a marker on every barline, and a beat marker on every
beat. Then **File → Export markers** to a `.txt` file next to your audio.

Three things are worth knowing:

- **Mark the pickup.** The tool lines the first bar up with the very start of
  the snippet. Any audio *before* your first marker cannot be reached, and it
  pushes everything else out of place. If your snippet starts on an upbeat,
  put a marker on that upbeat.
- **A short first bar is a pickup.** If the first bar has fewer beats than the
  rest, the tool treats it as an upbeat rather than a bar, and calls it bar
  **0**. Bar **1** is still the first full bar.
- **A last marker with nothing under it ends the passage.** If you dropped a
  marker on the closing barline, that marker is where the music stops. It is
  never played.

You can name markers whatever you like — `A1`, `D51`, `CHORUS`. Those names
become the names you use below.

## Writing the settings file

Make a file called something like `practice.yml`, in the same folder as your
audio, and put this in it:

```yaml
snippet: I Want You Back - loop 1.wav
marker_file: I Want You Back - loop 1.txt
output: I Want You Back - practice 1.wav

sections:
  - name: The whole thing, twice
    repeat: 2
    bars: "1111"
```

Read that as: take this snippet, take these markers, and write the result to
that file. Then play one **section**: all four bars, twice through.

If you keep everything in one folder, you can name the folder once at the top
and then use only file names:

```yaml
root: ~/Music/Jacksons 5
snippet: I Want You Back - loop 1.wav
```

## Sections

The file is a list of sections, played one after another, top to bottom. Each
section says how many times to `repeat` it, and gives a **pattern**.

There are four kinds of pattern, and each section uses exactly one.

### `sequence` — one character per pass

```yaml
  - name: Play it, imagine it, play it
    repeat: 1
    sequence: "1x1x"
```

`1` plays the whole snippet. `x` replaces the whole snippet with silence of
the same length. So this is: play, silence, play, silence.

### `bars` — one character per bar

```yaml
  - name: Lose the last bar
    repeat: 4
    bars: "111x"
```

One character per bar of your snippet, in order. Four bars, four characters.

### `beats` — one character per beat

```yaml
  - name: Lose the end of every bar
    repeat: 4
    beats: "1111 1111 1111 11xx"
```

One character per beat. Spaces are ignored, so group them by bar to keep them
readable. This is the one that gets you playing through the gaps.

### `markers` — pick out any span you like

The first three chop the snippet up on a grid. `markers` lets you say
"from here to there", in any order, as many times as you want:

```yaml
  - name: Drill bar 1, then run into bar 3
    repeat: 3
    markers: "[1-2][1-2][1-2] [JOHN-3]"
```

Each `[...]` is one span. What can go inside:

| Written | Means |
| --- | --- |
| `[4]` | bar 4 |
| `[D51]` | the bar or beat you named D51 |
| `[1.4]` | bar 1, beat 4 |
| `[JOHN]` | the text block you called JOHN |
| `[1-3]` | from bar 1 up to where bar 3 starts |
| `[1.4-3]` | from bar 1 beat 4 up to bar 3 |
| `[4-END]` | bar 4 through to the end of the snippet |
| `[4x]` | bar 4, silent |

Four rules cover the rest:

- **An end is where the named thing begins.** `[1-3]` is bars 1 and 2. Bar 3
  is where it stops, not something it includes.
- **A span with no end of its own runs to wherever the next one starts**, or
  to the end of the snippet if nothing follows. That is what lets
  `[1.1][UP1][UP2]` cut the snippet into three consecutive pieces.
- **To repeat or reorder, give each span its own end.** `[1][1]` is two spans
  of nothing, because the first is closed by the second. `[1-2][1-2]` is bar 1
  played twice.
- **`END` always means the end of the snippet**, wherever you write it.

A trailing `x` silences a span — unless a bar really is *called* `D51x`, in
which case `[D51x]` plays it. Names win.

## Drills

A **drill** is one line that stands for a whole run of sections. You name the
regions of the phrase, and the tool takes them away one at a time:

```yaml
  - name: heaven
    drill: "[START][M1.1][M2.1][M3.1-END]"
    steps: [widen, solo]
    reference: 1
    repeat: 3
    keep: 1
```

With four regions called A, B, C and D, and `keep: 1` holding A:

| Step | What it does |
| --- | --- |
| `each` | one region at a time: Bx, then Cx, then Dx |
| `head` | a growing head: Bx, then BxCx, then BxCxDx |
| `tail` | a growing tail: Dx, then CxDx, then BxCxDx |
| `build` | a shrinking tail, so the phrase grows back a region at a time |
| `widen` | a window that slides along, widens by one, and slides again |
| `solo` | each region in turn as the only one still sounding |

The other settings:

- `steps` — which drills to run, in the order given. The default is
  `[widen, solo]`.
- `keep` — how many regions at the front to leave alone, so you always get a
  run-up. `keep: 0` lets the silence reach everything, so `tail` finishes on
  total silence.
- `repeat` — how many times each silenced version is played.
- `reference` — how many times the plain, unsilenced phrase is played before
  each step, so you hear what you are aiming at.
- `cycle` — how many times the regions are laid down to make one pass. With
  `cycle: 2` the phrase keeps turning while the hole moves through it, so you
  hear the silence in time rather than as a gap.

To see exactly what a drill will produce before you commit to it, run it with
`--expand` (below). It prints the sections the drill stands for and stops. You
can paste those back in its place and edit them by hand.

## Running it

Open Terminal, go to the project folder, and run:

```bash
uv run loop ~/Music/Jacksons\ 5/practice.yml
```

Or, to see what a drill stands for without building any audio:

```bash
uv run loop --expand ~/Music/Jacksons\ 5/practice.yml
```

It prints what it found in your marker file — the bars, the beats, the text
blocks — and then what it is doing for each section. On a Mac it opens the
result in Transcribe! when it is done. On anything else that very last step
fails with a "no such file" — the practice file has already been written by
then, so ignore it.

## When it complains

The messages are meant to be read. A few common ones:

- **"no such bar, beat or text block: X"** — you named something that is not
  in the marker file. The end of the message names exactly the part that did
  not resolve. Scroll up: the tool prints the whole score as it read it, with
  every address you *can* use.
- **"X has 3 beats, expected 4"** — a bar in the middle of the snippet has an
  odd number of beat markers. Usually a missed or a doubled tap. The tool
  prints the beat times so you can see which. It is a warning, not an error.
- **"has nowhere to run"** — a span is closed by the one after it, and the one
  after it starts earlier. Either put the spans in time order, or give this
  one an end of its own.
- **"Markers run past the end of the snippet"** — the marker file and the
  audio are not the same passage.
- **"beats has 16 characters but the markers define 15 beats"** — count them
  again; the message tells you the shape it expected.

An error never leaves a half-written file behind. Fix the line it names and
run it again.
