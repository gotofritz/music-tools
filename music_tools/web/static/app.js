// Cells are text until they are clicked (or tabbed to). The box that replaces
// the text lives in a <template> beside it, so it is the server's own markup,
// hx-patch and all; this only swaps the two and tells HTMX about the new one.

function openCell(cell) {
  const box = cell.querySelector("template").content.firstElementChild.cloneNode(true);
  box._cell = cell;
  cell.replaceWith(box);
  if (window.htmx) {
    window.htmx.process(box);
  }
  box.focus();
  const end = box.value.length;
  box.setSelectionRange(end, end);
  grow(box);
}

// A notes box is as tall as its text, and never shorter than its two rows.
function grow(box) {
  if (box.tagName !== "TEXTAREA") {
    return;
  }
  box.style.height = "auto";
  box.style.height = `${box.scrollHeight}px`;
}

document.addEventListener("input", (event) => grow(event.target));

document.addEventListener("focusin", (event) => {
  const cell = event.target.closest && event.target.closest(".cell-text");
  if (cell) {
    openCell(cell);
  }
});

// Left alone, a box goes back to being text. One that changed is saved by
// `change`, which fires first, and the redraw that follows replaces it anyway.
document.addEventListener("focusout", (event) => {
  const box = event.target;
  if (box._cell && box.isConnected && box.value === box.defaultValue) {
    box.replaceWith(box._cell);
  }
});

// Escape puts back what the box had and leaves it, so nothing is saved.
document.addEventListener("keydown", (event) => {
  const box = event.target;
  if (event.key !== "Escape" || !box._cell) {
    return;
  }
  box.value = box.defaultValue;
  box.blur();
});

// A save redraws the day, and the box Tab moved on to is redrawn as text with
// it. Open that cell again, so Tab goes on to the next one rather than out.
let openId = null;
document.addEventListener("htmx:beforeSwap", () => {
  const box = document.activeElement;
  openId = box && box._cell ? box.id : null;
});
document.addEventListener("htmx:afterSettle", () => {
  const id = openId;
  openId = null;
  if (!id || document.getElementById(id)) {
    return;
  }
  const cell = [...document.querySelectorAll(".cell-text")].find((candidate) =>
    candidate.querySelector("template").content.getElementById(id)
  );
  if (cell) {
    openCell(cell);
  }
});

// Earlier days are <details>, collapsed on every load. One button flips them
// all, and its label says what the next click does. Days that arrive by "load
// more" are put in whatever mode the button is in now. Nothing is remembered.
function daysToggle() {
  return document.getElementById("toggle-days");
}

function setDays(open) {
  document
    .querySelectorAll("#history details.day")
    .forEach((day) => {
      day.dataset.seen = "";
      day.open = open;
    });
}

document.addEventListener("click", (event) => {
  const button = event.target.closest && event.target.closest("#toggle-days");
  if (!button) {
    return;
  }
  const open = button.dataset.state === "collapsed";
  button.dataset.state = open ? "expanded" : "collapsed";
  button.textContent = open ? "collapse all" : "expand all";
  setDays(open);
});

// The swap that brings a page of days replaces the button it came from, so
// the new days are found by not having been seen yet rather than by target.
// Only expanded mode has anything to do: the server draws them collapsed.
document.addEventListener("htmx:afterSwap", () => {
  const button = daysToggle();
  if (!button) {
    return;
  }
  document
    .querySelectorAll("#history details.day:not([data-seen])")
    .forEach((day) => {
      day.dataset.seen = "";
      if (button.dataset.state === "expanded") {
        day.open = true;
      }
    });
});

// A row of the picker is a start. The button in its name cell is the real
// control (keyboard, and no JavaScript); a click anywhere else on the row
// presses it.
document.addEventListener("click", (event) => {
  const row = event.target.closest && event.target.closest("tr.pick-row");
  if (!row || event.target.closest("button")) {
    return;
  }
  row.querySelector("button.row-start").click();
});
