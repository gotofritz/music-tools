# Practising with music-tools — a user guide

This guide is for playing, not programming. It assumes you can open a
Terminal window and type into it, and nothing else.

There are two tools, and they are heading towards being one:

- **`practice`** keeps track of *what* to play — every exercise, how fast you
  are playing it, when you last did it, and when it comes back. It is the
  spreadsheet, as a program.
- **`loop`** builds the practice track itself: a passage over and over with
  bits of it replaced by silence.

Part 1 below is `practice`. Part 2 is `loop`. Read whichever you need.

Ask a developer to do the one-off setup in [README.md](../README.md#setup)
first.

---

# Part 1 — Keeping track of what to practise

Practice is organised in three layers:

- A **module** is a practice area — `SLAP`, `SONGS`, `TECHNIQUE`. One per
  sheet, back when this was a spreadsheet.
- An **exercise** is a row in it: a tune or a study, with the speed you play it
  at, how many times you have practised it, and the date it is next due.
- The **day log** is what you actually did, in blocks of a day, with a subtotal
  per **log group** (`TECHNIQUE`, `REPERTOIRE`) and a total for the day.

Everything lives in one file: `~/.local/share/music-tools/practice.db`. Set
`MUSIC_TOOLS_DB` to keep it somewhere else, or pass `--db` to any command.

## A practice session

```bash
uv run practice day new              # start the clock
uv run practice next                 # what is due, most overdue first
uv run practice done "le freak"      # played it — schedule it and log the time
uv run practice log                  # today's block, with subtotals
```

`next` prints one line per exercise:

```
2026-12-03   3 days overdue   SONGS/le freak    87.8 BPM (66%)   x12
```

— the date it was due, how late that is, which module it is in, what speed you
are playing it at, and how many times you have practised it.

`done` is the one that matters. It bumps the count, stamps today, works out
when the exercise comes back, closes the entry that was running and starts the
next one, all at once:

```
le freak done — practised 13 times, next due 2027-01-15 (in 153 days)
logged 22:46-23:03  00:17  REPERTOIRE  87.8 BPM (66%)
```

You never type a start time. The clock runs from the last thing you finished,
so entries tile the session end to end. A day ends at 4am, not midnight —
practice past midnight belongs to the evening it started in.

If a name exists in two modules, say which: `uv run practice done SONGS/"le
freak"`. If you mistype it, the message lists the near misses.

## How fast you are playing it

The speed column understands two dialects, because Transcribe! counts in
percentages and metronomes count in BPM:

| You type | It means | At a target of 133 |
| --- | --- | --- |
| `123` | 123 BPM | 123 |
| `123/1` | the same, spelled out | 123 |
| `123/2` | 123 a minute, one every 2nd beat | 246 |
| `123/0.5` | 123 a minute, one every half beat | 61.5 |
| `66%` | 66% of what you are aiming at | 87.8 |

```bash
uv run practice speed "le freak" 85%
uv run practice speed "le freak" 85% --target-bpm 133
```

The **target** is the tempo the exercise is aiming at — the tune's real tempo,
or the marking on the page. It is worth filling in, because it is what makes
the two dialects comparable, and because **an exercise you are playing under
tempo comes back sooner**. At 80% of target the interval is 80% as long. Past
the target nothing shrinks further.

Anything the app cannot read — `fast`, `medium-ish`, an empty cell — is kept
exactly as you typed it and simply does not affect the schedule.

## When it comes back

Intervals grow the way they did in the spreadsheet: 1, 1, 2, 3, 5, 8, 13, 21,
34, 55, 89 days and on up to a ceiling of 120, with a few percent of jitter so
everything does not pile up on the same day. Four variations, when the default
is wrong:

| Command | What it does |
| --- | --- |
| `practice done X` | the normal interval |
| `practice done X --short` | half of it — this one is not sticking |
| `practice done X --long` | half again as long — this one is solid |
| `practice done X --rotate` | to the back of this module's queue |
| `practice done X --hold` | to the front: practised, but not learned |

## Adding things

```bash
uv run practice module add SLAP --log-group TECHNIQUE
uv run practice add SLAP "Stomp!" --speed 80% --target-bpm 133
uv run practice module list
```

## Bringing the spreadsheet over

Export each sheet from Google Sheets (**File → Download → Tab-separated
values**) and point the importer at them:

```bash
uv run practice import --modules "BASS SONGS.csv" --modules "BASS SLAP.csv" \
                       --day-log "BASS.csv"
```

The file name gives the module — `BASS SONGS.csv` becomes the module `SONGS`
on the instrument `bass` — and the top-left cell gives its log group. Practice
counts, dates and speeds all come over as they are, so nothing in the schedule
shifts on the day you switch. Running it twice changes nothing, so you can
re-export and re-import as often as you like. Anything it cannot read is listed
at the end rather than dropped in silence.

## Keeping a copy

The spreadsheet gave you version history for free and a file on your disk does
not:

```bash
uv run practice db dump    # writes backups/practice.sql
```

(or `task db:dump`, which is the same thing)

That is plain text, one line per row, so it can live in a git repository and be
read in a diff.

---

# Part 2 — Building a practice track

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

After the one-off setup you only ever type one command.

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
