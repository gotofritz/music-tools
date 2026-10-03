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
