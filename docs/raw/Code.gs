const TOKEN_INVALID = 'INVALID';
const SS = SpreadsheetApp.getActiveSpreadsheet();
const END_OF_DAY_HOUR = 4;
const SLOT_INCREMENT = 18;
const NO_ESTIMATE = '00:00';

function onOpen() {
  const menuEntries = [];
  menuEntries.push(
    { name: "Bass: New Day", functionName: "bassNewDay" },
    { name: "Bass: Done exercise (Short)", functionName: "doneExerciseShort"},
    { name: "Bass: Done exercise (Normal)", functionName: "doneExerciseNormal"},
    { name: "Bass: Done exercise (Long)", functionName: "doneExerciseLong"},
    { name: "Bass: Done exercise (Simple Rotate)", functionName: "doneExerciseRotate"},
    { name: "Bass: Done exercise (No Rotation)", functionName: "doneExerciseNoRotation"},
    { name: "Insert HH:mm", functionName: "setNow"},
    { name: "Bass: Update summary totals", functionName: "updateSummaryFormulas"},
    { name: "Bass: reorder exercises", functionName: "bassReorder" },
    // null // a divider
  );
  SS.addMenu("FRITZ", menuEntries ); 
}

