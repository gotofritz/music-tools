# The loop editor, inside the practice app

> **Parked — pushed to the back of the queue (2026-08-16).** The CLI already
> covers the YAML workflow, and the plan now rebuilds the useful part — loop
> output built from markers, in the page — as Phase 7 (`07-segments.md`), with
> no YAML round trip in the middle. Steps 1–3 below (`root:` defaulting, the
> `build_output` split, `PatternError`) moved to Phase 7, where they are still
> wanted. The rest waits here, renumbered from Phase 4 to Phase 8, until
> hand-editing `*.loop.yml` becomes a bottleneck again — which it may never
> be. Phase references in the body below are the old numbering, left as
> written.

**Phase 8 of `docs/plans/00-practice-app.md`, parked.** Read that first: it sets the
stack (FastAPI + Jinja2 + HTMX, no Node), the storage (SQLite at
`~/.local/share/music-tools/practice.db`, hand-written SQL, numbered
migrations), and the domain (module → exercise → practice entry). This document
covers only the loop half, and assumes Phases 1–3 have landed.

## Context

`loop.py` generates rhythm-training audio from a YAML config: a snippet, a
marker file exported from Transcribe!, and sections that each play a pattern
some number of times. Patterns can address bars, beats and text blocks directly
(`[1.1][UP1][UP2]`), which makes the format expressive but also makes
hand-editing fiddly — you have to hold the bar numbering in your head while
counting characters in `"1111 1111 1111 11xx"`.

An earlier version of this plan proposed a standalone editor over `*.loop.yml`
files scattered under the scores directory, discovered by glob. That framing is
now superseded on one point: **the app already has a database and already knows
which tune you are practising**, so a loop hangs off an exercise rather than
being found by walking the filesystem. The rest of that plan — the API shape,
the score-alongside-config trick, live pattern validation, drill expansion —
survives intact and is what most of this document still is.

What changed, and why:

- **A loop belongs to an exercise.** The scenario is "SLAP says Stomp! is due,
  click loop". A file-glob library cannot answer "the loops for Stomp!" without
  a naming convention doing the work a foreign key should do.
- **The database is the source of truth; YAML is an export.** Every save also
  writes `*.loop.yml` beside the audio, so `uv run loop practice.loop.yml` keeps
  working, unchanged, on the same config the app just edited. Import runs the
  other way for the configs already written by hand. Neither format is a
  lock-in, and the CLI needs no changes at all.
- **Audio and marker files stay on disk**, referenced by absolute path. They are
  large, they already live beside the scores, and Transcribe! wants them there.
- **Still a browser page, still no desktop app, still no Svelte.** A localhost
  Python process already has full filesystem access and already launches
  Transcribe! at the end of `main`. Tauri or Electron buys a native file dialog
  and a distributable binary, at the cost of a Rust or Node toolchain, for one
  user on one Mac. Streamlit was the closest call for a standalone editor and is
  now firmly out: it cannot host the rest of the app.

Audio preview stays deferred to Phase 5 of the parent plan. The browser choice
is what keeps it cheap when it arrives.

## Shape

Adds to the tree in `00-practice-app.md`:

```
music_tools/
    loop.py                        # already moved here in Phase 1
    db/migrations/002_loops.sql
    domain/loops.py                # loop config ↔ pydantic ↔ YAML
    web/routes/loops.py
    web/templates/loops/…          # editor page + HTMX fragments
    web/static/loop_grid.js        # the one island of hand-written JS
```

### Schema

```sql
CREATE TABLE loop_config (
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  name TEXT NOT NULL,              -- "verse slap figure"
  snippet_path TEXT NOT NULL,      -- absolute
  marker_path TEXT,                -- absolute, null once Phase 6 lands
  output_path TEXT NOT NULL,
  yaml_path TEXT,                  -- where the export is written
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE loop_section (
  id INTEGER PRIMARY KEY,
  loop_config_id INTEGER NOT NULL REFERENCES loop_config(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT,
  repeat INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL,              -- sequence | bars | beats | markers | drill
  pattern TEXT NOT NULL,
  options TEXT                     -- JSON: steps, keep, cycle, reference
);
CREATE UNIQUE INDEX loop_section_order ON loop_section(loop_config_id, position);
```

`mode` mirrors the YAML key exactly, so a row round-trips to `bars: "1111"` or
`drill: "[START][M1.1]"` with `steps`/`keep`/`cycle` out of `options`. Drills are
stored **unexpanded** — expansion is a view, not a migration, and expanding on
save would destroy the thing that makes a drill worth writing.

### Routes

Server-rendered fragments, not a JSON API, per the parent plan's stack. The two
exceptions return JSON because JavaScript in the grid consumes them.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/exercises/{id}/loops` | The exercise's loops; the **loop** button target |
| `POST` | `/exercises/{id}/loops` | Create: name, snippet, marker upload |
| `GET` | `/loops/{id}` | The editor page |
| `PUT` | `/loops/{id}` | Save, after validation |
| `POST` | `/loops/{id}/sections` | Add / duplicate / delete / reorder |
| `POST` | `/loops/{id}/validate` | JSON: resolved spans, or the error |
| `POST` | `/loops/{id}/expand` | The sections a drill stands for |
| `POST` | `/loops/{id}/generate` | Run generation, return the output path |
| `GET` | `/loops/{id}/export.yml` | The YAML, also written on every save |
| `POST` | `/loops/import` | Adopt an existing `*.loop.yml` |
| `GET` | `/browse?dir=` | Directories and audio/marker files, for picking |

`GET /loops/{id}` renders **the score alongside the config**, which is what makes
the page cheap: bar names, beat counts, labels and text-block names all come
from `Score`, so the template draws a labelled grid without parsing anything
itself. `describe(score)` already renders exactly this as text for CLI errors —
the editor wants the same view by another route.

`POST /loops/{id}/validate` is the other half. As a `markers:` field is typed it
returns the resolved spans, or the message:

```
[1.1][UP1][UP2]
0.000-0.545  0.545-0.872  0.872-2.760
```

A `drill:` section stands for a run of sections that silence its regions in
turn, built from named steps (`each`, `head`, `tail`, `build`, `widen`, `solo`)
composing in order over a `cycle` of one or more passes. The CLI expands it
textually — no score needed — and `--expand` prints the result for pasting back.
The editor shows a drill as its expansion too, since a row that generates
eighteen others is otherwise opaque; the step names are the obvious thing to
offer as checkboxes, with the expansion previewed live.

**Path safety.** These routes take filesystem paths from the browser. Reads and
writes are confined to a configured set of roots (default
`~/Documents/MuseScore4/Scores/TUNES`, plus the app data directory); anything
resolving outside them is refused. The server binds `127.0.0.1`. Small app, one
user, but `/browse?dir=/` would still be a mistake worth not making.

### Where the files live

Unchanged from the earlier plan, minus the discovery-by-glob:

```
~/Documents/MuseScore4/Scores/TUNES/S/Stomp - Brothers Johnson/
    Stomp - loop 1.wav          # snippet
    Stomp - loop 1.txt          # markers, exported from Transcribe!
    Stomp - practice 1.wav      # generated output
    stomp.loop.yml              # export, regenerated on every save
```

Supporting changes carried over from the earlier plan:

- **Default `root:` to the config file's own directory**, so a config beside its
  audio needs no absolute paths.
- **Remove `loop.yml` from the repo root.** It holds a personal config with an
  absolute `/Users/fritz/…` path and eleven sections. It moves to the Jackson 5
  directory, and its content becomes the first imported loop; a short
  `config/example_loop.yml` stays beside the existing `config/example_config.yml`.

### Known duplication, deliberately left alone

`music_tools/markers.py` has its own `MarkerFile.load` that ignores beat markers,
lowercases labels and reads text blocks as `x4` repeat counts;
`music_tools/main.py` has a third copy of `parse_timestamp`. Consolidating them
belongs to the `rearrange` unification, which the parent plan puts out of scope —
`Score` and `MarkerFile` answer different questions, and merging them now would
mean changing `rearrange` for no gain.

---

## Steps

Each step is red/green: write the failing test, then the smallest change that
passes it. Every step leaves the repo working.

`loop.py`'s own behaviour — marker parsing, pattern resolution, drill expansion —
is pinned by the characterisation tests from `../archive/01-foundations.md`. This phase is
where that pinning earns its keep: steps 1–3 change `loop.py`, and those tests
are what says the change was safe.

Steps 10–11 are UI; there is no JavaScript test framework here and adding one is
YAGNI, so those are verified by hand.

No binary fixtures: marker files are text, and audio comes from
`AudioSegment.silent(duration=…)` in a fixture.

### Step 1 — `root:` defaults to the config's directory

**Red.** Write a config into `tmp_path` with no `root:` and a relative `snippet:`
beside it, then load it from a different working directory. Currently resolves
against the process cwd and raises "Snippet not found". Assert it resolves next
to the config instead.

**Green.** In `main`, use the config's parent as the root when the key is
absent, rather than `Path("")`.

### Step 2 — Generation split from I/O

`main` currently loads, builds, exports and launches Transcribe! inline, so
generation cannot be tested without shelling out to a macOS-only binary.

**Red.** Assert `build_output(cfg, score, snippet) -> AudioSegment` exists and
that for `bars: "1x"` over a two-bar score the result is one snippet long, with
the second half silent (`max_dBFS == -inf` over that slice) and the first half
not. Assert the section summary it returns matches what the CLI prints, and
that a `bars` pattern of the wrong length raises the mismatch error naming the
bar shape — inline in `main` until now, pinned here where the extraction puts
it.

**Green.** Extract `build_output` from `main`, leaving `main` as load → build →
export → open. Put the Transcribe! launch behind `--open/--no-open` (default on)
so no test ever shells out.

### Step 3 — Pattern validation as a service

`Score.parse_pattern` raises `ClickException`, which is CLI-shaped and wrong to
catch in a web handler.

**Red.** Assert `validate_pattern(score, mode, text)` returns a result object —
`ok` plus spans, or `ok=False` plus the message — and that it never raises, for
both a valid pattern and `[nope]`.

**Green.** Introduce a `PatternError` in `music_tools/loop.py`, raise that from
the parsing code, and have `main` convert it to `ClickException` so the CLI's
output is unchanged. `validate_pattern` catches `PatternError`.

### Step 4 — Loop configs in the database

**Red.** `tests/test_loops.py`: migration `002_loops.sql` creates the two
tables; `create_loop(exercise_id, name, snippet, markers)` returns a config with
no sections; `sections_for(config)` comes back in `position` order; deleting the
exercise cascades; deleting a section leaves the remaining positions contiguous.

**Green.** The migration plus `domain/loops.py` repository functions, pydantic
models following the style already in `music_tools/config.py`.

### Step 5 — YAML round-trip

The join between the database and the CLI, and the riskiest single piece — get
it wrong and the app and the CLI disagree about what a config means.

**Red.** Parametrised over a config of every `mode`: `to_yaml(config)` produces
a mapping `loop.py` accepts, with `root` set to the snippet's directory and
`snippet`/`marker_file`/`output` relative to it; `from_yaml` of that mapping
reproduces the config; a drill survives with its `steps`, `keep`, `cycle` and
`reference` intact and **unexpanded**. Then the end-to-end one: import
`loop.yml` from the repo root — eleven sections, mixed `bars` and `beats` — and
assert the export is YAML-equal to the original. Unknown top-level keys are
preserved rather than dropped, and the legacy top-level `markers:` spelling,
which the CLI still accepts with a nudge, imports as `marker_file`.

**Green.** `to_yaml` / `from_yaml` in `domain/loops.py`.

### Step 6 — Describing a config for the page

**Red.** Assert `describe_loop(config)` returns the config fields plus a score
summary — bar names with beat counts, beat labels, text-block names — and that
the result survives a `json.dumps`/`loads` round-trip (no `Path` or
`float('inf')` leaking through). Assert a config whose marker file has gone
missing describes cleanly with the score absent and an error attached, rather
than raising: the page must still open so the path can be fixed.

**Green.** Pydantic view models.

### Step 7 — Read routes

**Red.** `TestClient` against a temp database: `GET /exercises/{id}/loops` lists
them; `GET /loops/{id}` returns 200 with the config and the score; an unknown id
returns 404; `POST /loops/{id}/validate` returns spans for a valid pattern and
the message for an invalid one; `POST /loops/{id}/expand` returns the sections a
drill stands for. `GET /browse` refuses a directory outside the configured
roots with 403.

**Green.** `web/routes/loops.py`. `fastapi`, `uvicorn[standard]` and `jinja2` are
already dependencies from Phase 3; add `httpx` as a dev dependency if
`TestClient` has not already pulled it in, and `python-multipart` for the upload.

### Step 8 — Write routes

**Red.** `PUT /loops/{id}` with a valid body saves and rewrites the YAML export;
an invalid pattern returns 422 with the message **and leaves both the database
and the file unchanged**. `POST /exercises/{id}/loops` with an uploaded marker
file writes it beside the snippet and creates the config; a second upload of the
same name does not clobber the first. Section add / duplicate / delete /
reorder each leave positions contiguous.

**Green.** Implement, validating through step 3 before writing. A file write
cannot join a SQLite transaction, so the order stands in for one: validate,
write the export to a temp file, commit the rows, rename the temp into place —
a failure at any point leaves neither the database nor the previous export
changed.

### Step 9 — Generate

**Red.** `POST /loops/{id}/generate` returns 200 and the output path; the file
exists; its duration matches the sum of the resolved spans; no Transcribe!
launch during tests.

**Green.** Wire to `build_output` from step 2 with `open=False`.

### Step 10 — The editor page

**Green** (verified by hand). The exercise row in a module gets a **loop**
button. It opens the exercise's loops; a loop opens the editor: sections as
cards, each with a grid labelled from the score (`A1`, `A2`… / `D51`, `b1`,
`b2`…). Clicking a cell toggles `1`↔`x`. Sections can be added, duplicated,
deleted and reordered. `markers:` mode is a text field validated on each
keystroke against step 7, resolved spans shown underneath. A drill shows its
expansion, with the step names as checkboxes. Save, and generate with the
summary the CLI prints.

Everything except the grid is HTMX against fragments. The grid is one
`loop_grid.js` — toggling cells and posting the pattern — and should stay under
a couple of hundred lines. If it stops being tolerable, that is the signal to
put a real frontend in front of the same routes, and nothing on the server
changes when that happens.

### Step 11 — Creating a loop from the practice flow

**Green** (verified by hand). The scenario end to end: SLAP says Stomp! is due →
**loop** → no loops yet → the create form, pre-filled with the tune's directory
if one can be guessed from the exercise name, asking for the snippet and the
marker `.txt` → the editor, with the score already drawn.

Then the parent plan's Phase 5 adds play-in-place, and Phase 6 replaces the
`.txt` upload with marking in the browser.

---

## Verification

Beyond the suite, on the real files:

1. `uv run loop "~/…/Jacksons 5/practice.loop.yml"` produces what it does today,
   confirming steps 1–2 changed nothing.
2. Import that same config into the app, save it untouched, and confirm the
   rewritten YAML is data-equal to the original: key order may move, and the
   original's teaching comments are gone — `to_yaml` writes data, not
   commentary. (The comments live on in the CLI help and
   `config/example_loop.yml`.)
3. Toggle a bar off in the grid, save, and confirm the YAML diff is the single
   character expected.
4. Generate from the app and from the CLI; confirm both write the same file.

`pydub` needs ffmpeg for mp3, and the Transcribe! launch is macOS-only — both
bound where the suite can run, hence `--no-open` and silence-generated fixtures.

## Out of scope

- The `rearrange` configs and their nested step DSL.
- Unifying `Score` with `MarkerFile`.
- Audio preview (parent plan, Phase 5) and in-app markers (Phase 6).
- Any JavaScript framework.
