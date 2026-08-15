// all zero-based
const BASS_ROW_FIRST = 1;

const BASS_COL_FIRST = 0;
const COL_DESC = 1;
const COL_MODULE = 2;
const COL_PRACTICED_COUNT = 3;
const COL_LAST_PRACTICED = 4;
const COL_NEXT_DUE = 5;
const COL_NOTES = 6;

const COL_BASS_DATE = 0;
const COL_BASS_TIME_FROM = 1;
const COL_BASS_TIME_TO = 2;
const COL_BASS_DURATION = 3;
const COL_BASS_BPM = 4;
const COL_BASS_DESC = 5;
const COL_BASS_MODULE = 6;
const COL_BASS_MODULE_DURATION = 7;
const COL_BASS_DAY_DURATION = 8;

function oneBased(n) {
  return n+1;
}

function getWorkingRange_(sh) {
  const r1 = oneBased(BASS_ROW_FIRST);
  const c1 = oneBased(BASS_COL_FIRST);
  return sh.getRange(r1, c1, sh.getLastRow() - BASS_ROW_FIRST, COL_NOTES - BASS_COL_FIRST + 5);
}

// FIX: was using getDisplayValues() (strings), so the sort `a - b` always
// returned NaN and nothing moved. Now uses getValues() for real Date objects.
// Empty rows (no description) are separated out and appended at the bottom
// so they don't get mixed into the sorted exercises.
function bassReorder() {
  let sh = SS.getActiveSheet();
  let workingRange = getWorkingRange_(sh);
  let gridOfCells = workingRange.getValues();

  let nonEmpty = gridOfCells.filter(row => !isEmpty_(row[COL_DESC]));
  let empty    = gridOfCells.filter(row =>  isEmpty_(row[COL_DESC]));

  nonEmpty.sort((a, b) => {
    let da = a[COL_NEXT_DUE] ? new Date(a[COL_NEXT_DUE]) : new Date('9999-12-31');
    let db = b[COL_NEXT_DUE] ? new Date(b[COL_NEXT_DUE]) : new Date('9999-12-31');
    return da - db;
  });

  workingRange.setValues([...nonEmpty, ...empty]);
  sh.getRange(oneBased(BASS_ROW_FIRST), oneBased(COL_NEXT_DUE), sh.getLastRow() - BASS_ROW_FIRST + 1, 1)
    .setNumberFormat("yyyy-mm-dd");
}

// Spaced-repetition algorithm: Fibonacci-based intervals with a small random
// jitter and a BPM-percentage scaling factor.
function addNextDue(row) {
  const seenCount = row[COL_PRACTICED_COUNT];
  // COL_LAST_PRACTICED was already set to new Date() by doneExercise_ before
  // this function is called, so it is always a valid Date here.
  const lastSeenDate = new Date(row[COL_LAST_PRACTICED]);

  const intervals = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120];

  let intervalDays = seenCount < intervals.length
    ? intervals[seenCount]
    : intervals[intervals.length - 1];

  const offset = Math.round(intervalDays * 0.05 * (Math.random() * 2 - 1));
  intervalDays = Math.max(1, intervalDays + offset);

  const tempo = row[BASS_COL_FIRST];
  const matches = /(^\d+)%$/.exec(String(tempo));
  if (matches) {
    intervalDays = intervalDays * 100 / Number(matches[1]);
  }

  const nextDue = new Date(lastSeenDate);
  nextDue.setDate(nextDue.getDate() + Math.round(intervalDays));
  row[COL_NEXT_DUE] = nextDue;
}

function addNextDueLong(row) {
  const seenCount = row[COL_PRACTICED_COUNT];
  // COL_LAST_PRACTICED was already set to new Date() by doneExercise_ before
  // this function is called, so it is always a valid Date here.
  const lastSeenDate = new Date(row[COL_LAST_PRACTICED]);

  const intervals = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120].map(i => Math.ceil(i * 1.5));

  let intervalDays = seenCount < intervals.length
    ? intervals[seenCount]
    : intervals[intervals.length - 1];

  const offset = Math.round(intervalDays * 0.05 * (Math.random() * 2 - 1));
  intervalDays = Math.max(1, intervalDays + offset);

  const tempo = row[BASS_COL_FIRST];
  const matches = /(^\d+)%$/.exec(String(tempo));
  if (matches) {
    intervalDays = intervalDays * 100 / Number(matches[1]);
  }

  const nextDue = new Date(lastSeenDate);
  nextDue.setDate(nextDue.getDate() + Math.round(intervalDays));
  row[COL_NEXT_DUE] = nextDue;
}

function addNextDueShort(row) {
  const seenCount = row[COL_PRACTICED_COUNT];
  // COL_LAST_PRACTICED was already set to new Date() by doneExercise_ before
  // this function is called, so it is always a valid Date here.
  const lastSeenDate = new Date(row[COL_LAST_PRACTICED]);

  const intervals = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 104, 108, 112, 120].map(i => Math.ceil(i * 0.5));

  let intervalDays = seenCount < intervals.length
    ? intervals[seenCount]
    : intervals[intervals.length - 1];

  const offset = Math.round(intervalDays * 0.05 * (Math.random() * 2 - 1));
  intervalDays = Math.max(1, intervalDays + offset);

  const tempo = row[BASS_COL_FIRST];
  const matches = /(^\d+)%$/.exec(String(tempo));
  if (matches) {
    intervalDays = intervalDays * 100 / Number(matches[1]);
  }

  const nextDue = new Date(lastSeenDate);
  nextDue.setDate(nextDue.getDate() + Math.round(intervalDays));
  row[COL_NEXT_DUE] = nextDue;
}

// Simple-rotate algorithm: put the exercise just after the current latest due
// date, with a random offset of -1 / 0 / +1 / +2 days.
function addNextDueRotate(row, maxDueDate) {
  const randomDays = Math.floor(Math.random() * 4) - 1; // -1, 0, 1, or 2
  const nextDue = new Date(maxDueDate);
  nextDue.setDate(nextDue.getDate() + randomDays);
  row[COL_NEXT_DUE] = nextDue;
}

// Normal spaced repetition (Fibonacci).
function doneExerciseNormal() {
  doneExercise_(addNextDue);
}

function doneExerciseLong() {
  doneExercise_(addNextDueLong);
}

function doneExerciseShort() {
  doneExercise_(addNextDueShort);
}

// Simple rotation: append to the end of the queue with a small random offset.
// FIX: this function was listed in the menu but never defined.
function doneExerciseRotate() {
  // Find the latest due date across all exercise rows before we start
  // mutating anything, so the result is based on the current state.
  let sh = SS.getActiveSheet();
  let workingRange = getWorkingRange_(sh);
  let allValues = workingRange.getValues();

  let maxDueDate = new Date(0);
  for (let row of allValues) {
    if (!isEmpty_(row[COL_NEXT_DUE])) {
      let d = new Date(row[COL_NEXT_DUE]);
      if (d > maxDueDate) maxDueDate = d;
    }
  }

  doneExercise_((row) => addNextDueRotate(row, maxDueDate));
}

function doneExerciseNoRotation() {
  let sh = SS.getActiveSheet();
  let currentRow = SS.getSelection().getActiveRange().getRow();
  let workingRange = getWorkingRange_(sh);
  let allValues = workingRange.getValues();
  let workingStartRow = oneBased(BASS_ROW_FIRST);

  let minDueDate = new Date('9999-12-31');
  for (let i = 0; i < allValues.length; i++) {
    if (workingStartRow + i === currentRow) continue;
    let row = allValues[i];
    if (!isEmpty_(row[COL_NEXT_DUE])) {
      let d = new Date(row[COL_NEXT_DUE]);
      if (d < minDueDate) minDueDate = d;
    }
  }

  doneExercise_((row) => {
    const candidate = new Date(minDueDate);
    candidate.setDate(candidate.getDate() - 1);

    const currentDue = row[COL_NEXT_DUE] ? new Date(row[COL_NEXT_DUE]) : new Date('9999-12-31');
    if (currentDue > candidate) {
      row[COL_NEXT_DUE] = candidate;
    }
  });
}

// Engine for "done exercise"; the scheduling algorithm is supplied as nextDueFn.
function doneExercise_(nextDueFn, shouldReorder = true) {
  let sh = SS.getActiveSheet();
  let currentRow = SS.getSelection().getActiveRange().getRow();

  // Read current row data.
  let exerciseRowData = sh.getRange(currentRow, oneBased(BASS_COL_FIRST), 1, 7).getValues()[0];

  // Increment the practice counter and stamp today's date.
  exerciseRowData[COL_PRACTICED_COUNT] = exerciseRowData[COL_PRACTICED_COUNT] + 1;
  exerciseRowData[COL_LAST_PRACTICED]  = new Date();

  // Compute the next due date — mutates exerciseRowData[COL_NEXT_DUE].
  nextDueFn(exerciseRowData);

  // Write everything (including the new due date) back in one batch call.
  sh.getRange(currentRow, oneBased(BASS_COL_FIRST), 1, 7).setValues([exerciseRowData]);
  sh.getRange(currentRow, oneBased(COL_LAST_PRACTICED), 1, 1).setNumberFormat("yyyy-mm-dd");
  sh.getRange(currentRow, oneBased(COL_NEXT_DUE),       1, 1).setNumberFormat("yyyy-mm-dd");

  // Update the BASS summary sheet (must happen BEFORE reordering).
  updateSummaryRow(currentRow, sh, exerciseRowData);

  // Reorder exercises by due date and refresh the summary totals.
  if (shouldReorder) {
    bassReorder();
  }
  updateSummaryFormulas();
}

// Walk upward from `rowIndex` within the BASS sheet until we hit the row
// that starts the current day's block (i.e. the nearest row at or above
// `rowIndex` whose date column, A, is non-empty). Row 1 (the header) is an
// absolute floor.
function findDayStartRow_(bassSh, rowIndex) {
  let r = rowIndex;
  while (r > 1 && isEmpty_(bassSh.getRange(r, oneBased(COL_BASS_DATE)).getValue())) {
    r -= 1;
  }
  return r;
}

// Walk upward from `rowIndex - 1`, but not past the start of the current
// day's block, to find the most recently written (non-blank) module value.
// Returns null if no module has been set yet in this block.
function findEffectiveModuleAbove_(bassSh, rowIndex) {
  let dayStart = findDayStartRow_(bassSh, rowIndex);
  for (let r = rowIndex - 1; r >= dayStart; r -= 1) {
    let v = bassSh.getRange(r, oneBased(COL_BASS_MODULE)).getValue();
    if (!isEmpty_(v)) return v;
  }
  return null;
}

/**
 * Add the exercise to the summary row.
 * Make sure this is called BEFORE reordering!
 * @param exerciseRow the row index of the exercise
 * @param sh the active sheet (the practice-area sheet the exercise was logged from)
 * @param exerciseRowData the data from the exercise row
 */
function updateSummaryRow(exerciseRow, sh, exerciseRowData) {
  let bassSh = SS.getSheetByName("BASS");
  let range = activeBassRange();
  let rowIndex = range.getRowIndex();

  let values   = range.getValues();
  let formulas = range.getFormulas();

  values[0][COL_BASS_TIME_TO] = HHmm();
  values[0][COL_BASS_BPM]     = exerciseRowData[BASS_COL_FIRST];
  values[0][COL_BASS_DESC]    = exerciseRowData[COL_DESC];

  let notes = exerciseRowData[COL_NOTES];
  if (notes) {
    values[0][COL_BASS_DESC] += ` (${notes})`;
  }

  // Module (column G) comes from cell A1 of the practice-area sheet this
  // exercise was logged from. The first row of a new day always gets it
  // written explicitly (so every day's block is self-contained for the
  // subtotal aggregation below). For later rows in the same day, it's only
  // written when it differs from the most recently set module earlier in
  // the day — otherwise it's left blank, same as the old manual convention.
  let moduleName = String(sh.getRange(1, 1).getValue()).trim();
  let isDayStart = !isEmpty_(values[0][COL_BASS_DATE]);
  let effectivePrevModule = isDayStart ? null : findEffectiveModuleAbove_(bassSh, rowIndex);
  if (moduleName && (isDayStart || moduleName !== effectivePrevModule)) {
    values[0][COL_BASS_MODULE] = moduleName;
  }

  range.setValues(values);

  // Restore any formulas that setValues() overwrote.
  for (let i = 0; i < formulas[0].length; i += 1) {
    let formula = formulas[0][i];
    if (!formula) continue;
    bassSh.getRange(rowIndex, oneBased(i)).setFormula(formula);
  }
  bassSh.getRange(rowIndex, oneBased(COL_BASS_DURATION)).setFormula(formulaDuration(rowIndex));
  bassSh.getRange(rowIndex + 1, oneBased(COL_BASS_TIME_FROM)).setValue(HHmm());
}

function HHmm(d = new Date()) {
  return pad_(d.getHours()) + ":" + pad_(d.getMinutes());
}

function formulaDayDuration(rowIndexStart, rowIndexEnd) {
  return `=TEXT(SUM(H${rowIndexStart}:H${rowIndexEnd}), "hh:mm")`;
}

function formulaDuration(rowIndex) {
  return `=IF(ISBLANK(C${rowIndex}), "", C${rowIndex}-B${rowIndex})`;
}

function activeBassRange(isNew=false) {
  let sh = SS.getSheetByName("BASS");
  let row = findLastRowWithData(sh, oneBased(COL_BASS_DATE), oneBased(COL_BASS_TIME_TO), (isNew ? 1 : 0));
  let range = sh.getRange(row, oneBased(BASS_COL_FIRST), 1, sh.getLastColumn() - BASS_COL_FIRST);
  return range;
}

function bassNewDay() {
  let range = activeBassRange(true);
  let row = range.getRowIndex();
  let values = Array(range.getWidth());
  values[BASS_COL_FIRST]           = new Date();
  values[COL_BASS_TIME_FROM]       = HHmm();
  values[COL_BASS_DURATION]        = formulaDuration(row);
  values[COL_BASS_MODULE_DURATION] = `=SUM(D${row})`;
  values[COL_BASS_DAY_DURATION]    = `=TEXT(SUM(H${row}:H${row + 2}), "hh:mm")`;
  range.setValues([values]);
}

// Turns a sorted list of BASS-sheet row numbers into a comma-separated list
// of A1-style ranges/cells for the given column letter, collapsing
// consecutive runs into "col#:col#" ranges.
// e.g. compressRowsToRanges_([5, 6, 7, 9], 'D') -> "D5:D7,D9"
function compressRowsToRanges_(rows, colLetter) {
  let parts = [];
  let i = 0;
  while (i < rows.length) {
    let start = rows[i];
    let end = start;
    while (i + 1 < rows.length && rows[i + 1] === end + 1) {
      end = rows[i + 1];
      i += 1;
    }
    parts.push(start === end ? `${colLetter}${start}` : `${colLetter}${start}:${colLetter}${end}`);
    i += 1;
  }
  return parts.join(',');
}

function updateSummaryFormulas() {
  let sh = SS.getSheetByName("BASS");

  let rowIndexStart = findLastRowWithData(sh, oneBased(COL_BASS_DATE),    oneBased(COL_BASS_DATE));
  let rowIndexEnd   = findLastRowWithData(sh, oneBased(COL_BASS_TIME_TO), oneBased(COL_BASS_TIME_TO));

  sh.getRange(rowIndexStart, oneBased(COL_BASS_DAY_DURATION))
    .setFormula(formulaDayDuration(rowIndexStart, rowIndexEnd));

  let blockHeight = rowIndexEnd - rowIndexStart + 1;
  let moduleRange = sh.getRange(rowIndexStart, oneBased(COL_BASS_MODULE), blockHeight, 1);
  let modules = moduleRange.getValues().map(r => r[0]);

  // Fill blanks forward with the most recent explicit module in the block,
  // so entries no longer need to be contiguous - you can mix and match
  // (e.g. one row from A, two from B, one from A, three from C...).
  let effectiveModules = [];
  let lastSeen = null;
  for (let v of modules) {
    if (!isEmpty_(v)) lastSeen = v;
    effectiveModules.push(lastSeen);
  }

  // Group row offsets (0-based within the block) by effective module, in
  // order of first appearance, so we know where to place each subtotal.
  let firstOffsetForModule = new Map();
  let offsetsForModule     = new Map();

  effectiveModules.forEach((mod, offset) => {
    if (mod === null) return; // nothing set yet - can't attribute this row
    if (!offsetsForModule.has(mod)) {
      offsetsForModule.set(mod, []);
      firstOffsetForModule.set(mod, offset);
    }
    offsetsForModule.get(mod).push(offset);
  });

  // One SUM formula per module, placed on its first occurrence in the
  // block and aggregating every row (contiguous or not) that belongs to
  // it; every other row in the block is left blank.
  let durationFormulas = new Array(blockHeight).fill('');
  for (let [mod, offsets] of offsetsForModule.entries()) {
    let firstOffset = firstOffsetForModule.get(mod);
    let rows = offsets.map(o => rowIndexStart + o);
    durationFormulas[firstOffset] = `=SUM(${compressRowsToRanges_(rows, 'D')})`;
  }

  let durationRange = sh.getRange(rowIndexStart, oneBased(COL_BASS_MODULE_DURATION), blockHeight, 1);
  durationRange.setFormulas(durationFormulas.map(f => [f]));
}

function setNow() {  
  selectedCell().setValue(HHmm());
}

