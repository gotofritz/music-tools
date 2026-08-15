function findLastRowWithData(sh, fromCol, toCol, offset = 0) {
  var maxRows = sh.getMaxRows();
  
  for (var row = maxRows; row >= 1; row--) {
    var range = sh.getRange(row, fromCol, 1, toCol - fromCol + 1);
    var values = range.getValues()[0];
    
    // Check if any value in this row has content
    var hasContent = values.some(value => value !== "" && value != null);
    
    if (hasContent) {
      return row + offset;
    }
  }
  
  return -1; 
}

/**
 * 'empty cell' in GAS is not straightforward
 */
function isEmpty_(val) {
  return val == undefined || val === "";
}

function asDateString_(date) {
  date = new Date(date);
  return `${date.getFullYear()}-${pad_(date.getMonth() + 1)}-${pad_(date.getDate())} ${pad_(date.getHours())}:${pad_(date.getMinutes())}`
}

function pad_(str, maxLength=2) {
   return String(str).padStart(maxLength, "0");
}

function selectedCell() {
  let sh = SS.getActiveSheet();
  return sh.getActiveCell();
}

