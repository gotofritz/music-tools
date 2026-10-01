# 10 — edit in place

Issue #39. Click a cell, change it, move away: it saves. No edit toggle, no
per-row save, no "done". Applies to the day log and every other editable field.

- Log rows: each finished line is a row of inputs, one `hx-patch` each on
  `change`; only the changed field is sent. The running line stays read-only.
- Exercise rows and media rows/set labels: the form saves on `change, submit`;
  the save buttons go.
- `PATCH /entries/{id}` and `PATCH /exercises/{id}` read the raw form so an
  emptied box clears the field. An emptied description changes nothing.
- Ids on every box so the cursor survives the redraw; Esc restores a cell.
- Removed: `_edit_toggle.html`, `GET /days/{day}/edit`, the `editing` flag.
- Cost, accepted: editing needs JavaScript.
- Docs: `initial-context.md` (editing, form-per-cell rule), `user-guide.md`.
