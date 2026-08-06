# A local editor for loop configs

## Context

`loop.py` generates rhythm-training audio from a YAML config: a snippet, a
marker file exported from Transcribe!, and sections that each play a pattern
some number of times. Patterns can now address bars, beats and text blocks
directly (`[1.1][UP1][UP2]`), which makes the format expressive but also makes
hand-editing fiddly — you have to hold the bar numbering in your head while
counting characters in `"1111 1111 1111 11xx"`.

The goal is a small local app to edit these configs instead.

Three decisions shape it:

- **Audio preview comes later.** Build the editor first; playback afterwards.
- **`loop.yml` only.** The `rearrange` configs under `music_tools/configs/` stay
  out of scope. Unifying all the scripts into one app is wanted eventually, but
  is explicitly YAGNI for now.
- **Configs move out of this repo.** Each tune keeps its own config next to its
  audio, somewhere under the user's scores directory. A database may replace
  files later; files first.

That last point is load-bearing: configs are scattered across the filesystem, so
the app must open and save arbitrary paths. A browser file picker hands you a
file with no path, so you could neither read the sibling marker file nor write
back — there has to be a server side regardless.

## General plan

**FastAPI serving a JSON API, plus one hand-written HTML page. No build step, no
Node.** Run it the way the repo already runs things:

```
uv run loop-editor          # serves localhost, opens a browser
```

Why this rather than the alternatives:

- **Not a desktop app.** A localhost Python process already has full filesystem
  access and already launches Transcribe! at the end of `main`. Tauri or
  Electron buys a native file dialog and a distributable binary, at the cost of
  a Rust or Node toolchain, for one user on one Mac.
- **Not Svelte, yet.** There is no JavaScript anywhere in this repo — one
  `uv.lock`, everything `uv run`. A bundler and a second dependency tree is a
  lot of new surface for what is a clickable table. Svelte can go in front of
  the same API later without touching the backend.
- **Not Streamlit** — the closest call, and faster for this v1, since sections
  are rows and `st.data_editor` gives add/delete/edit nearly free. Two things
  decide against it: the rerun-on-every-click model gets awkward exactly where
  this is headed (a grid you click repeatedly, then audio you scrub), and it is
  a dead end at the "unify all the scripts" step — a Streamlit app cannot be
  grown into a general one, only rewritten.

The split that makes this safe: **the FastAPI layer is the durable piece**, the
backend a unified app would need anyway. The HTML page is deliberately cheap and
replaceable.

### Shape

```
music_tools/loop.py              # model + parsing + CLI, moved from ./loop.py
music_tools/editor/app.py        # FastAPI app + uvicorn launcher
music_tools/editor/library.py    # finding configs on disk
music_tools/editor/models.py     # pydantic views over config + score
music_tools/editor/static/       # index.html, app.js, app.css
tests/                           # pytest
```

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/configs` | Configs found under the scan root |
| `GET` | `/api/config?path=` | One config, plus its resolved score |
| `PUT` | `/api/config?path=` | Save, after validation |
| `POST` | `/api/config` | Create from a template next to a chosen snippet |
| `POST` | `/api/validate` | Validate one pattern, return resolved spans |
| `POST` | `/api/generate?path=` | Run generation, return the output path |
| `GET` | `/api/browse?dir=` | List directories and audio/marker files |

`GET /api/config` returning **the score alongside the config** is what makes the
UI cheap: bar names, beat counts, labels and text-block names all come from
`Score`, so the page renders a labelled grid without parsing anything itself.
`POST /api/validate` is the other half — it returns resolved spans or the error,
so a `markers:` field can show live feedback as you type:

```
[1.1][UP1][UP2]
0.000-0.545  0.545-0.872  0.872-2.760
```

`describe(score)` already renders a score as the addresses a pattern can use —
every bar and beat with its time, text blocks under the bar they fall in — which
the CLI prints on any failure. The editor wants the same data as JSON rather
than text, so `/api/config` returning the score is that same view by another
route.

### Where configs live

Adopt a `*.loop.yml` suffix, each config beside the audio it drives:

```
~/Documents/MuseScore4/Scores/TUNES/I/I want you Back - Jacksons 5/
    I Want You Back - Jackson 5 - loop 1.wav
    I Want You Back - Jackson 5 - loop 1.txt
    practice.loop.yml
```

Discovery needs no registry and no state file: glob `**/*.loop.yml` under a
configurable scan root (default `~/Documents/MuseScore4/Scores/TUNES`), plus
open-by-path for anything outside it. When a database replaces files, only
`list_configs()` changes.

Supporting changes: **default `root:` to the config file's own directory** so a
config next to its audio needs no absolute paths, and **remove `loop.yml` from
the repo** — it currently holds a personal config with an absolute
`/Users/fritz/...` path and eleven sections. It moves to the Jackson 5 directory
as `practice.loop.yml`, leaving a short `config/example_loop.yml` beside the
existing `config/example_config.yml`.

### Known duplication, deliberately left alone

`music_tools/markers.py` has its own `MarkerFile.load` that ignores beat
markers, lowercases labels and reads text blocks as `x4` repeat counts;
`music_tools/main.py` has a third copy of `parse_timestamp`. Consolidating them
belongs to the unify step — `Score` and `MarkerFile` answer different questions,
and merging them now would mean changing `rearrange` for no gain.

---

## Steps

Each step is red/green: write the failing test, then the smallest change that
passes it. Every step leaves the repo working, so stopping after any of them is
fine.

**Two honest caveats.** Steps 1–2 are *characterisation* tests, not true red —
the behaviour already exists and the tests are red only because there is no test
suite yet. Their job is to fail loudly if the later refactors break something.
And steps 11–12 are UI; there is no JavaScript test framework here and adding
one is YAGNI, so those are verified by hand.

No binary fixtures: marker files are text, and audio comes from
`AudioSegment.silent(duration=…)` in a fixture.

### Step 1 — Test harness, and `loop.py` becomes importable

`loop.py` is a PEP 723 single-file script with inline dependencies, so nothing
can import `Score`, `parse_markers` or `parse_pattern` from it.

**Red.** Add `pytest` as a dev dependency. `tests/test_score.py` opens with
`from music_tools.loop import Score, parse_markers` → `ModuleNotFoundError`.
Cover, using `tests/fixtures/d51.txt` and `tests/fixtures/jackson5.txt`:

- `parse_markers` on the D51 file yields four bars `D51`–`D54` of four beats
  each, beats `b1`/`b2` labelled in the first bar, one text block `JOHN`.
- A trailing bar marker with no beats under it closes the last bar instead of
  opening one, using the Two Way Pak E Way file that ends on a bare `93`, which
  is addressable as the end of the score but never played.
- A marker labelled `end` truncates the score there and everything after it is
  dropped — undocumented behaviour that predates the pattern grammar, and the
  reason nothing can shadow the reserved `END`.
- `parse_markers` on the Jackson 5 file yields `A1`–`A4`, with five beats in `A3`.
- `Marker (auto)` counts as a beat, not something to skip: Transcribe! writes it
  for beats it worked out itself, and a file mixing `auto` and `beat` markers
  must give every bar the same beat count. A kind that is neither bar nor beat
  is counted into `score.ignored` and reported rather than dropped in silence.
- `Score.build` shifts the first marker to `0.0`; the last bar ends at the
  snippet duration. That anchoring is why audio before the first marker cannot
  be addressed — a loop starting on an upbeat must mark that upbeat.
- A first bar shorter than the bars after it is a pickup: `score.pickup` is set,
  positional addressing starts at `[0]`, and `[1]` is the first full bar. A loop
  with square edges keeps 1-based numbering and has no `[0]`.
- The odd-beat-count warning covers interior bars only, since a snippet cut from
  a recording is expected to be partial at both edges. A short bar in the middle
  still warns; a short first or last bar does not.
- `modal_beats` breaks a tie toward the longer count, so a `2+4+4+2` loop reads
  as two full bars between two partial ones. Breaking it the other way blames
  the two correct interior bars, which is what `Counter.most_common` does on its
  own — the same trap that made the warning name the wrong bar on a `1+4` file.
- Bars tile the snippet with no gaps or overlaps, and so do beats.
- Markers longer than the snippet raise, with the "belong to this snippet"
  message.

**Green.** Move the module to `music_tools/loop.py`, drop the inline dependency
block (`click`, `pyyaml` and `pydub` are already project dependencies), register
`loop = "music_tools.loop:main"` under `[project.scripts]` following the
existing `rearrange` entry, delete root `loop.py`. Invocation becomes
`uv run loop config.yml`; update the docstring examples.

### Step 2 — Pattern resolution locked down

**Red.** `tests/test_patterns.py`, parametrised over every span form against the
D51 score: `[1][2][3][4x]` tiling the snippet bar by bar; `[D51]…` matching it
by label; `[1.1][1.2][1.3][1.4x][2]`; `[b1][b2]`; `[JOHN]` alone running to the
end; the ranges `[1-3]`, `[1.4-3]`, `[JOHN-3.2]`, `[JOHN-D53]`, `[1.1-JOHN]`,
`[1-3x]`; repeats and out-of-order runs written with explicit ends. The
neighbour rule specifically: `[1]` alone is the whole snippet, `[1][3]` is bars
1–2 then 3 to the end, and `[1][2]` matches `[1-2]` only because 2 follows.
On the Two Way file, `[92-93]` naming the end marker as an end, equal to a bare
`[92]` but usable anywhere in a pattern, and equal again to `[92-END]`. Errors: `[nope]`, `[JOHN-nope]`, `[]`,
`[9]`, `[1.9]`, the backwards span `[JOHN-b2]`, the empty `[1][1]`, `[3][1]` and
`[93]`, `{JOHN}` pointing at square brackets, and `[1]junk[2]`. Plus a third fixture containing a bar genuinely labelled
`D51x`, asserting `[D51x]` plays it rather than silencing `D51`.

**Green.** Nothing — these should pass on arrival. If any fails, step 1 broke
something.

### Step 3 — `root:` defaults to the config's directory

**Red.** Write a config into `tmp_path` with no `root:` and a relative
`snippet:` beside it, then load it from a different working directory. Currently
resolves against the process cwd and raises "Snippet not found". Assert it
resolves next to the config instead.

**Green.** In `main`, use the config's parent as the root when the key is
absent, rather than `Path("")`.

### Step 4 — Generation split from I/O

`main` currently loads, builds, exports and launches Transcribe! inline, so
generation cannot be tested without shelling out to a macOS-only binary.

**Red.** Assert `build_output(cfg, score, snippet) -> AudioSegment` exists and
that for `bars: "1x"` over a two-bar score the result is one snippet long, with
the second half silent (`max_dBFS == -inf` over that slice) and the first half
not. Assert the section summary it returns matches what the CLI prints.

**Green.** Extract `build_output` from `main`, leaving `main` as load → build →
export → open. Put the Transcribe! launch behind `--open/--no-open` (default
on) so no test ever shells out.

### Step 5 — Finding configs on disk

**Red.** `tests/test_library.py`: build a tmp tree with `a/one.loop.yml`,
`b/c/two.loop.yml`, `b/other.yml` and `b/notes.txt`. Assert
`list_configs(root)` returns the two `.loop.yml` paths, sorted, and excludes the
others. Assert a missing root returns `[]` rather than raising.

**Green.** `music_tools/editor/library.py`.

### Step 6 — Describing a config for the UI

**Red.** Assert `describe(path)` returns the config fields plus a score summary
— bar names with beat counts, beat labels, text-block names — and that the
result survives a `json.dumps`/`loads` round-trip (no `Path` or `float('inf')`
leaking through).

**Green.** Pydantic models in `music_tools/editor/models.py`, following the
style already in `music_tools/config.py`.

### Step 7 — Pattern validation as a service

`Score.parse_pattern` raises `ClickException`, which is CLI-shaped and wrong to
catch in a web handler.

**Red.** Assert `validate_pattern(score, mode, text)` returns a result object —
`ok` plus spans, or `ok=False` plus the message — and that it never raises, for
both a valid pattern and `[nope]`.

**Green.** Introduce a `PatternError` in `music_tools/loop.py`, raise that from
the parsing code, and have `main` convert it to `ClickException` so the CLI's
output is unchanged. `validate_pattern` catches `PatternError`.

### Step 8 — Read endpoints

**Red.** `tests/test_api.py` with `fastapi.testclient.TestClient` — the app does
not exist. Then, against a tmp scan root: `GET /api/configs` lists the fixtures;
`GET /api/config?path=` returns 200 with config and score; an unknown path
returns 404; `POST /api/validate` returns spans for a valid pattern and the
message for an invalid one.

**Green.** `music_tools/editor/app.py`. Add `fastapi` and `uvicorn[standard]` as
dependencies, and `httpx` as a dev dependency (`TestClient` needs it).

### Step 9 — Write endpoints

**Red.** `GET` then `PUT` the same body leaves the file YAML-equal. A `PUT` with
an invalid pattern returns 422 with the message **and leaves the file unchanged
on disk**. `POST /api/config` creates a config from a template next to a chosen
snippet, and refuses to overwrite an existing file.

**Green.** Implement, validating through step 7 before writing.

### Step 10 — Generate endpoint

**Red.** `POST /api/generate?path=` returns 200 and the output path; the file
exists; its duration matches the sum of the resolved spans. No Transcribe!
launch during tests.

**Green.** Wire to `build_output` from step 4 with `open=False`.

### Step 11 — Read-only page

**Red.** `GET /` serves HTML referencing `app.js`, and the static assets return
200.

**Green.** `index.html` + `app.js` + `app.css`: configs listed on the left
grouped by directory, the open config on the right, sections rendered as cards
with a grid labelled from the score (`A1`, `A2`… / `D51`, `b1`, `b2`…). No
editing yet. Verified by hand.

### Step 12 — Editing

Clicking a grid cell toggles `1`↔`x`; sections can be added, duplicated, deleted
and reordered; save; create from template; generate with the summary the CLI
prints. For `markers:` mode the pattern is a text field validated against
`/api/validate` on each keystroke, showing resolved spans underneath. Covered by
the API tests from steps 8–10; the interactions themselves are verified by hand.

Keep the page under a few hundred lines. If it stops being tolerable, that is
the signal to put Svelte in front of the same API.

### Step 13 — Later: audio preview

A `/api/preview` endpoint returning a wav for one section or the whole routine,
and an `<audio>` element. Deferred by decision; the browser choice is what keeps
it cheap when it arrives.

---

## Verification

Beyond the suite, on the real files:

1. `uv run loop "~/…/Jacksons 5/practice.loop.yml"` produces what it does today,
   confirming steps 1–4 changed nothing.
2. `uv run loop-editor`, open that config, toggle a bar off in the grid, save,
   and confirm the YAML diff is the single character expected.
3. Generate from the app and from the CLI; confirm both write the same file.

Note that `pydub` needs ffmpeg for mp3, and the Transcribe! launch is
macOS-only — both bound where the suite can run.

## Out of scope

Recorded so they don't creep in: the `rearrange` configs and their nested step
DSL; unifying `Score` with `MarkerFile`; a database behind `list_configs()`;
audio preview (step 13); and any JavaScript framework.
