# Phase 10 — Today as the main interface

**Depends on Phases 4 and 5a** (start/stop on rows, media on the card, the
waveform player). Independent of 5b and 6–8, but it re-houses the card that
5b's mixer and Phase 6's markers will live in, so it should land before them.
Wishlist stage: direction now, red/green detail when the phase starts.

## Goal

A practice session is run from the **Today** page alone: finish what is
playing, pick the next thing from a module, edit what is playing, listen, and
glance at earlier days — without opening a module tab. The module tabs stay,
but become the place where the catalogue is *configured* (adding, moving,
archiving, bulk edits), not where a session is run.

**Done when** a whole session — start, practise with the player, edit the
row's name/speed/target/notes/media in place, finish with any of the five
stops, pick the next tune, repeat — never leaves `/`; and the page stays
usable after weeks of history because earlier days are collapsed.

## Decisions (agreed)

- **START does not open a line.** It reveals the module picker only. A log
  line opens when a row is clicked in the picker, so a false start leaves
  nothing behind. (The untitled "from now, for anything" line, and ad-hoc
  typed practice, are dropped from this page; `practice` CLI keeps
  `start_ad_hoc`.)
- **Any stop is a start for the next one.** Clicking one of the five stop
  buttons (normal / short / long / rotate / hold) on the current exercise
  finishes it exactly as today and then shows the picker, the same state as
  after START. Discard stays, and also lands on the picker.
- **Picker = one button per module tab, then that tab's list.** Clicking a
  module button opens a scrolling panel just below the row of buttons with
  the module's name at the top and its live rows in the tab's own order
  (overdue first, then by due date). It is the tab's table minus: the move
  checkbox, the module column, start, stop (and archive). Cells are not
  editable. Clicking a row **starts it** — same call as the tab's start
  button — and closes the picker. Clicking the active module button again, or
  the picker's close control, hides the list.
- **The current-exercise area is the tab row, plus its media.** It shows the
  exercise (name, speed, target BPM, notes), its media, the stop column (the
  five buttons, in place of today's pulldown + `done`), and discard. The text
  cells are editable in place with the existing click-to-edit cells.
- **Media is fully editable inline** — everything the media page does: labels,
  order, remove, mix state, add-to-set, and the attach forms (file path,
  YouTube, score, text). The media page itself stays (config-style access, and
  the no-JS path).
- **Earlier days are collapsed.** Each earlier day is one heading line (date,
  total, per-group totals) that toggles its entries. One button at the top of
  *Earlier* flips between **collapse all** and **expand all** (label tracks
  the state). Today's log is always expanded and is not collapsible. Collapse
  state is not remembered: every load starts collapsed. Days that arrive via
  **load more** start in whatever mode the button is currently in.
- **Server-rendered, HTMX, no new framework (A1).** Reuse the routes and
  fragments that exist; new fragments for the picker and the collapsible day.

## Shape

```
templates/today.html            # the page: now-playing, picker slot, log, earlier
templates/_now_playing.html     # exercise row (editable) + media + stop column + discard
templates/_picker.html          # the row of module buttons (+ the open list slot)
templates/_picker_list.html     # one module's read-only list, click row = start
templates/_day_block.html       # <details> heading + entries, collapsed by default
static/app.js                   # collapse-all/expand-all toggle, picker open/close
web/routes/practice.py          # GET /picker, GET /picker/{module}; redraws include picker
web/views.py                    # picker context, "nothing running" state
```

## Steps

1. **Earlier days collapse.** `_day_block.html` becomes a `<details>` whose
   `<summary>` is the heading line; today's block is unchanged. `/days`
   fragments and `/days/{day}` still render. Collapse-all/expand-all button
   with a changing label; **load more** respects the current mode. Red: day
   blocks carry `<details>` and no `open`; today's log has none.
2. **Picker fragments.** `GET /picker` (module buttons only) and
   `GET /picker/{slug}` (the read-only list: module name on top, no
   checkbox/module/start/stop/archive cells, no editable cells; a row posts the
   existing `/exercises/{id}/start`). 404 for an unknown or archived module.
3. **START and the idle state.** With nothing running the now-playing area is
   START → picker; starting a row swaps in the running state and clears the
   picker. Replace the bare `POST /entries` START path (keep the route for the
   CLI-less/no-JS fallback until nothing links to it, then remove it).
4. **Stop column on the current exercise.** The five buttons replace the
   pulldown + `done`; each posts the algorithm; the answer is the redraw with
   the picker open. Discard likewise. `POST /entries/{id}/done` keeps working
   (same redraw) for the day-log "done" on a finished line's route.
5. **The current exercise, editable.** Render the tab-row cells (name, speed,
   target BPM, notes) inside the now-playing card. Their `PATCH`
   (`/exercises/{id}`) must answer for *this* target, not the tab's `<tr>`:
   route on `HX-Target`. **A text edit must not rebuild the player** — swap
   only the edited cells (out-of-band) so playback and the waveform keep
   going; only a change that alters the media or the exercise's identity
   redraws the card.
6. **Inline media editing.** Embed the media list and the attach forms in the
   card. Their writes answer with the media block of the card; the player
   re-initialises only if its source set changed.
7. **Tabs demoted.** Nothing is removed. Link/wording/layout touch-ups so the
   module pages read as configuration (start/stop stay there, they are still
   useful). Update the user guide and `docs/initial-context.md`.

## Verification

Each step is red/green in `tests/test_web.py` (markup and routes). The
behaviour pytest cannot see is checked by hand in a browser — the known gap of
a no-Node repo — and re-run after any change to the card:

- Reload `/` with several days of history: every earlier day is collapsed,
  today open; the single button flips label and opens/closes them all, also
  after **load more**.
- START → module buttons only, no line in the log. Click a module → list
  scrolls in its own panel under the buttons; click a row → picker gone, row
  running above, one log line.
- Stop with each of normal/short/long/rotate/hold → the entry is logged, the
  schedule moves as the tab's stop does, the picker appears.
- While audio plays, edit the notes and the speed: playback does not
  restart, the waveform does not redraw.
- Rename, retarget, attach a file, reorder, remove, add a stem to a set — all
  from `/`, without opening the media page.

## Open assumptions (change if wrong)

- The picker also lists **only live (non-archived) rows**, in all modules, one
  button per non-archived module, in tab order.
- **Discard** from the picker state does not exist (nothing running to
  discard); picker state has a close control instead.
- While something **is** running the picker is hidden; to switch, finish or
  discard first (or use the tab's start, which still closes the running line).
  Say if you want the picker available during a run.
- The log's per-line **done**-style editing and `practice` CLI are unchanged.

## Out of scope

- Redesigning the tabs into a settings area beyond the touch-ups in step 7.
- 5b (multitrack transport), markers, segments, the loop editor.
- Remembering collapse state across reloads; keyboard shortcuts; mobile
  layout.
