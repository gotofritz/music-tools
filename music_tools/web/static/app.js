// Escape in an in-place cell puts back what it had and leaves it, so nothing
// is saved: `change` only fires when the value differs from the one it had.
document.addEventListener("keydown", (event) => {
  const cell = event.target;
  if (event.key !== "Escape" || !cell.classList || !cell.classList.contains("cell")) {
    return;
  }
  cell.value = cell.defaultValue;
  cell.blur();
});
