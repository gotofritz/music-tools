# Practising with music-tools — a user guide

This guide is for playing, not programming. It assumes you can open a
Terminal window and type into it, and nothing else.

There are two tools, and they are heading towards being one:

- **`practice`** keeps track of *what* to play — every exercise, how fast you
  are playing it, when you last did it, and when it comes back. It is the
  spreadsheet, as a program. It has two doors into the same file: the commands
  below, and a page in your browser (`practice serve`, further down).
- **`loop`** builds the practice track itself: a passage over and over with
  bits of it replaced by silence.

Part 1 below is `practice`. Part 2 is `loop`. Read whichever you need.

Ask a developer to do the one-off setup in [README.md](../README.md#setup)
first.

---

# Part 1 — Keeping track of what to practise

**The module is the unit.** A module is a practice area — `SLAP`, `SONGS`,
`TECHNIQUE` — one per sheet, back when this was a spreadsheet. Each one holds
its own list of rows, ordered by the date each row is next due, and the modules
never affect each other: a row is scheduled against the module it is in, and
you ask one module at a time what to play.

- A **row** (an **exercise**) belongs to exactly one module: a tune or a study,
  with the speed you play it at, how many times you have practised it, and the
  date it is next due.
- The **day log** is what you actually did, in blocks of a day, with a subtotal
  per **log group** (`TECHNIQUE`, `REPERTOIRE`) and a total for the day. The log
  group is a property of the module, which is how a day's practice adds up
  across several of them.

Everything lives in one file: `~/.local/share/music-tools/practice.db`. Set
`MUSIC_TOOLS_DB` to keep it somewhere else, or pass `--db` to any command.

## A practice session

```bash
uv run practice start                # start the clock, or restart it
uv run practice next SONGS           # what that module wants, most overdue first
uv run practice done "le freak"      # played it — schedule it and log the time
uv run practice log                  # today's block, with subtotals
```

`next MODULE` prints that module's rows, the most overdue first:

```
SONGS (REPERTOIRE) — 1 due of 4 rows
  2026-12-03   3 days overdue   le freak      87.8 BPM (66%)   x12
  2027-01-05   in 33 days       espresso      70%              x13
```

— the heading says how many of its rows are actually due today or earlier, then
one line per row: the date it was due, how late that is, what speed you are
playing it at, and how many times you have practised it.

Bare `next` does the same for every module, one block each, because that is what
modules are: separate lists that happen to live in the same file.

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

## Practising from a browser page

Everything above has a page, if you would rather click than type:

```bash
uv run practice serve
```

That opens a browser on `http://127.0.0.1:8765/`. It runs on your own machine
and nowhere else: nothing is uploaded, nothing is fetched, and it works with
the wifi off. Leave the Terminal window open while you practise, and press
`ctrl-c` in it when you are done.

`--port 9000` moves it if something else is on that port, and `--no-browser`
starts it without opening a window.

**The first page is today.**

- **Log** is today, line by line, with the entry that is running now counting
  up. **Totals** underneath is the subtotal per log group and the total for the
  day — the same numbers as `practice log`.
- **Earlier** is the five days before it, newest first, each with what you
  played, its subtotals and its total. **load more** adds the next five. There
  is no date picker and no search: it is a log, and you read it backwards.
- **edit**, beside a day, puts boxes round that day's lines — and only that
  day's. Change the times, what you played, the speed, the group or the notes,
  press **save**, and the day redraws with its totals worked out again. Fix as
  many lines as you like; **done** puts the day back to plain reading. Use it
  for the clock you left running through supper, or a name typed in a hurry.
- What is **due** is not here — it lives on the module pages, one click away in
  the bar at the top, because a queue belongs to the module it is scheduled
  in.
- The line that is **running** gets no boxes even in edit mode: that one is
  the clock, and **done** and **stop the clock** are what move it. It becomes
  editable once it is closed, like every other line.
- The clock in the top corner says whether time is being counted, and
  **stop the clock** ends the session. The stretch since the last thing you
  marked done is not logged: nobody said what it was, so it is not practice
  time. It is the same rule as `practice start`, from the other end.

If there is no day open yet, the page offers a **start a day** button instead
of a log.

**Each module has its own page**, reached from the links at the top: the whole
queue, most overdue first, and every field editable in place. **done** is the
button at the end of each row — the same thing as `practice done`. The
drop-down beside it is the choice the flags give you on the command line:
`normal`, `short` (this one is not sticking), `long` (this one is solid),
`rotate` (to the back of the module's queue), `hold` (to the front). Click it
and the row, today's log and the totals all update where they are; the page
does not reload.

Change the name, the speed, the target or the notes and press **save** — the row re-reads itself
with the speed worked out, so typing `85%` shows you `113 BPM (85%)` as you go.
A row with no target is flagged in red, because a percentage of nothing cannot
be resolved and cannot move the schedule; filling those in as you meet them is
the tidiest way to close the gap the import leaves.

At the bottom of a module page is **add a row**. Anything added there is due
straight away, so it is at the top of that module's queue rather than waiting
for a date you have to type.

Editing a row never rewrites the day log, here or on the command line — what
you played last Tuesday is still called what it was called last Tuesday. The
log is corrected on its own, line by line, in the pages above.

Two things editing the log will not do. A line stays on the day it happened
on, so a session logged against the wrong evening cannot be dragged to another
one. And nothing is deleted: a line you no longer want can be emptied, but the
day it belongs to keeps its place in the history.

The page and the commands are two doors into one file, so you can use both in
the same session: mark something done in the browser and `practice log` in the
Terminal shows it.

## Coming back after a break

Following on from the last thing is right most of the time and wrong after a
break: the coffee, the phone call and the walk round the block would all be
logged against whatever you play next. So when you sit down again:

```bash
uv run practice start
```

```
clock running from 23:40 — 00:37 of break not logged
```

The clock now runs from this moment, and the gap is gone — it was not practice,
so it is not in the log and not in the day's total. Nothing that was already
logged is touched.

`start` also opens the day if there is not one yet, so on an ordinary evening
it does the same job as `day new` and you can use either.

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

## Looking after the modules

```bash
uv run practice module list                    # every module: how many rows, how many due
uv run practice module show SONGS              # one module in full, due or not
uv run practice module add SLAP --log-group TECHNIQUE
uv run practice module rename SLAP "BASS SLAP"
uv run practice module edit SLAP --log-group TECHNIQUE --position 1
```

`module list` is the "where am I?" command — run it before deciding which module
to sit down with:

```
SONGS          REPERTOIRE   4 rows     1 due   next 2026-11-14
SLAP           TECHNIQUE    9 rows     3 due   next 2026-08-12
```

One line per module: its name, the day-log bucket its time counts towards, how
many rows are in it, how many of those are due today or earlier, and the date
the next one falls due. A `—` in the last column means nothing in that module
has a date yet. Archived modules are left out; `module list --archived` shows
them too.

`module show MODULE` then prints that module's rows in full, however many there
are — `next` stops at ten. `module show SLAP --archived` includes the rows you
have archived.

`--position` is the order the modules are listed in. `--log-group` is which
bucket the module's time subtotals into in the day log.

## Adding and changing rows

```bash
uv run practice add SLAP "Stomp!" --speed 80% --target-bpm 133 --due 2026-09-01
uv run practice edit "Stomp!" --name "Stomp! (Godsmack)" --speed 85% --count 4
uv run practice speed "Stomp!" 85%             # shorthand for edit --speed
```

Editing a row never rewrites the day log. What you played last Tuesday was
called what it was called last Tuesday.

## Putting things away

Two ways, and the difference matters:

```bash
uv run practice archive "Stomp!"        # out of the module, still in the log
uv run practice restore "Stomp!"
uv run practice module archive SLAP     # the module and all its rows at once
uv run practice module restore SLAP

uv run practice delete "Stomp!"         # gone, and only for mistakes
uv run practice module delete SLAP [--force]
```

**Archiving is the normal move.** The row leaves the module's list and stops
turning up in `next`, and everything it did is still in the day log and still
adds up. Archiving a module takes all of its rows out in one go.

**Deleting is for mistakes** — the module you named wrong five minutes ago. It
is refused for anything the day log points at, and tells you to archive it
instead; a log with a hole in it is worse than a module you have stopped using.
`module delete --force` takes the rows with it, and is refused just the same
once any of them has been practised.

## Bringing the spreadsheet over

Export each sheet from Google Sheets (**File → Download → Tab-separated
values**) and point the importer at them:

```bash
uv run practice import \
  --modules 'SONGS:~/Downloads/Bass Practice - SONGS.tsv' \
  --modules 'SLAP:~/Downloads/Bass Practice - SLAP.tsv' \
  --day-log ~/Downloads/BASS.csv
```

**Say which module each file is**, in front of the path and separated by a
colon. Google names a single-sheet download after the document and *then* the
sheet — `Bass Practice - SONGS.tsv` — so left to guess, the importer would
create a module called `Practice - SONGS`.

Quote the whole argument, because those file names have spaces in them. The
`~` still works inside the quotes; the importer expands it.

A plain path with no `NAME:` in front of it still works, and the module is
guessed from the file name less its first word — which is right for the old
`BASS SONGS.csv` exports and wrong for anything Google names today.

The top-left cell of the sheet gives the module's log group. Practice counts,
dates and speeds all come over as they are, so nothing in the schedule shifts
on the day you switch. Running it twice changes nothing — the second run
updates the rows it matched, keyed on the module name you gave and the row's
own name — so you can re-export and re-import as often as you like. Anything it
cannot read is listed at the end rather than dropped in silence.

Get the name wrong and you get a second module: `practice module list` shows
it, `practice module delete <name>` removes it as long as nothing in the day
log points at it, and then you can import again.

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
