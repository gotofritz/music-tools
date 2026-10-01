# 09 — form fixes, a start button, and the running row on top

Issues #34, #35, #36, #37, #38. Small, mostly in `web/`; no migration.

## #35 — target BPM is validated

`_fields` calls `float()` on whatever was typed, so `---` is a 500.

- Server: an unreadable `target_bpm` is a 400 with the sentence in the problem
  slot (the existing `refused` handler), on edit and on add.
- Client: `inputmode="decimal"` and a `pattern` on the target BPM inputs.

## #36 — the target BPM can be cleared

`_fields` drops a blank `target_bpm`, so a value can never go back to null. On
edit a blank now means `NULL`; the repository already writes `None`.

## #34 — notes are a textarea

`<input name=notes>` becomes `<textarea>` in the exercise row, the add-a-row
form and the entry edit row.

## #37 — a start button when nothing is running

Ad-hoc entries already exist (`exercise_id` is nullable, `start_ad_hoc`,
`POST /entries`). `description` becomes optional there, defaulting to
`Practice`, and the "Nothing running" line in `_now_playing.html` becomes a
START form posting to it.

## #38 — the running exercise is first, and green

The queue is ordered by due date, so a started row stays where it was. The
module page and the queue fragment put the running exercise first, in the view
layer rather than the SQL, and the row gets `class="active"` with a pastel
lime background.

## Order

TDD per issue: failing test, fix, `task qa`. Update `docs/user-guide.md` where
the behaviour is visible. Archive this plan in the same PR.
