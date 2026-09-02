# Move rows between modules

**Issue #29**, not a phase of `docs/plans/00-practice-app.md` — the app it
describes is built, and this is one thing the catalogue could not do. Read
`docs/initial-context.md` first for the vocabulary (module, exercise, entry,
log group) and for the rule that the day log is a snapshot.

## Goal

A row is typed into the wrong module, or it grows out of the one it is in — a
tune drilled as TECHNIQUE becomes repertoire, a lick filed under SONGS is
really SLAP. Today the only way across is to retype it in the other module and
archive the original, which throws away its schedule (`practiced_count`,
`last_practiced`, `next_due`), leaves its media behind and puts a second name
in the day log for one piece of music.

**Move the row instead**, and move several at once: tick the ones that belong
elsewhere, pick the module, click move.

**Done when** a ticked row leaves the module page it was on and appears in the
target module's queue with its count, its dates, its media and its history
intact, and the same is available from the terminal.

## Decisions

- **A move is `exercise.module_id`, and nothing else.** Not delete-and-recreate:
  the row keeps its id, so its schedule, its `media_source` rows and every
  `practice_entry` pointing at it come with it for free. `module_id` is already
  in `EXERCISE_COLUMNS`, so **there is no migration** — this is the whole reason
  the feature is small.
- **The day log does not follow, and that is the existing rule.** An entry
  snapshots `description`, `speed`, `bpm` and `log_group` when it is started
  (Phase 4), so finished days keep reading exactly as they read before. A move
  changes what *future* entries subtotal into, which is the point when the two
  modules have different log groups. Same rule as renaming a row.
- **Names stay unique within a module.** `add_exercise` and `update_exercise`
  both refuse a name the module already uses live; moving is a third way to
  collide and is refused the same way, with the same `InUse` and the same 409.
  An *archived* row in the target does not block the move — `find_exercises` is
  live-only, and `restore_exercise` already owns the other side of that trade.
- **A bulk move is all-or-nothing.** One transaction, and the clash check runs
  over every row before any of them is written. Half a move is worse than none:
  the page that comes back cannot say which half went, and the fix is to hunt
  through two modules.
- **Archived rows are not moved.** They are not on the page, not in the queue,
  and `_exercise` already refuses them for every other edit. `restore` first.
- **The target module must be live.** Moving a queue into something archived is
  a way to lose rows quietly.
- **A row already in the target is a no-op, not an error.** It is what a stale
  page or a double click produces, and the state it asks for is the state it is
  already in.
- **The checkbox is the whole UI, for one row and for twenty.** The issue asks
  for a move and then for a bulk move; ticking one box is the single-row case,
  so a per-row module dropdown would be a second control doing the same job on
  a row that is already wide. Nothing ticked is a quiet no-op — a mis-click is
  not worth an error page.
- **The checkboxes are associated to the move form by `form="move"`.** The move
  bar cannot wrap the table: every row already carries its own `<form>` for
  edit, start, stop and archive, and a nested form is dropped by the browser.
  The HTML5 `form` attribute puts the boxes in the right form from inside the
  cells — `new FormData(form)` and a plain browser submit both collect them, so
  it degrades with the JavaScript off like everything else here.
- **The answer to a move is the whole queue, not a row.** Every other write in
  the app swaps one `#exercise-{id}` back; a move takes rows *off* the page, so
  the fragment is the tbody (`_queue_rows.html`), targeted `innerHTML`.
- **The module the rows leave is in the path: `POST /modules/{slug}/move`.** It
  is the page answering, so it addresses the page. `POST /exercises/move` was
  the first shape and is wrong twice over: `/exercises/{exercise_id}` is
  declared above it and reads `move` as an id (422 before the handler is
  reached), and the source module then has to travel as a hidden field.
- **The CLI keeps parity**, as it has for every catalogue verb:
  `practice move EXERCISE... --to MODULE`. Exercises are variadic and `--to` is
  a named option, because `move A B C` cannot say which of the three is the
  module — and `MODULE/NAME` is already the way `_resolve` disambiguates a name
  that lives in two modules.

## Shape

```
music_tools/
    domain/catalogue.py                 + move_exercises
    web/routes/modules.py               + POST /exercises/move
    web/templates/_queue_rows.html      new: the tbody, and the empty queue
    web/templates/_queue_head.html      + the tick column
    web/templates/_exercise_row.html    + the tick box
    web/templates/module.html           + the move bar
    web/static/app.css                  + the move bar and the tick column
    cli.py                              + practice move
tests/
    test_catalogue.py                   the domain rules
    test_web.py                         the route and the markup
    test_cli.py                         the command
```

### The domain function

```python
def move_exercises(
    conn: sqlite3.Connection, exercise_ids: Sequence[int], *, module_id: int
) -> list[Exercise]:
    """Move rows to another module, keeping their schedule and their history."""
```

Returns every requested row as it now reads, in the order asked for, so a
caller can report what it did without a second read. Raises `NotFound` for an
unknown or archived row and for an unknown or archived module, and `InUse`
naming the first row whose name is taken in the target.

### The route

`POST /modules/{slug}/move` — `slug` is the module the rows leave, and the
body is form-encoded:

| field | | |
| --- | --- | --- |
| `module_id` | select | where the ticked rows go |
| `exercise_id` | checkbox, repeated | which rows move |

404 for an unknown module or row, 409 for a name clash, and otherwise the
source module's queue re-rendered — the moved rows are gone from it.

## Steps

TDD throughout (`red → green → refactor`), one commit a step.

1. **`move_exercises` in `domain/catalogue.py`.** Tests in `test_catalogue.py`:
   the schedule and the media survive; the day log keeps its snapshot; a clash
   in the target is refused and *nothing* moves; an archived row and an
   archived target are `NotFound`; a row already in the target is a no-op.
2. **`POST /modules/{slug}/move`.** Tests in `test_web.py`: ticking two rows empties
   them out of the answering queue and puts them in the other module; the
   response is the tbody; nothing ticked changes nothing; a clash is 409 and
   leaves both queues alone; a plain form post (no `HX-Request`) redirects back.
3. **The page.** The tick column in `_queue_head.html` and `_exercise_row.html`,
   the `_queue_rows.html` fragment (module page and move response render the
   same thing), the move bar in `module.html` — hidden when there is nowhere to
   move to — and the CSS.
4. **`practice move`.** Tests in `test_cli.py`: one row, several rows, an
   unknown module, a clash reported as a message rather than a traceback.
5. **Docs.** `docs/initial-context.md` (the catalogue paragraph, and the layout
   for the new template), `README.md` and `docs/user-guide.md`, then archive
   this plan.

## Out of scope

- **Moving a whole module's queue in one go.** `module delete --force` is the
  only bulk verb the catalogue has, and "move everything" is `archive` with
  extra steps until something asks for it.
- **Reordering rows within a module.** The queue is ordered by due date; there
  is no manual order to drag.
- **Moving media between exercises.** A move takes the material with the row,
  which is the case this issue is about.
- **Rewriting history to match the move.** Entries are snapshots; see above.
