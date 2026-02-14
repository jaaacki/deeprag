const Sheet = {
  /**
   * Writes an array of objects to a specific Google Sheet.
   * * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet - The spreadsheet object (e.g., SpreadsheetApp.getActiveSpreadsheet())
   * @param {string} sheetName - The name of the tab/sheet to write to.
   * @param {Array<Object>} data - Array of objects (key-value pairs) to write.
   * @param {string} mode - 'append' (adds to bottom) or 'overwrite' (clears sheet first). Defaults to 'append'.
   */
  writeToSheet: function (sheetName, data, mode = 'append', spreadsheet = SheetById) {
    if (!data || data.length === 0) {
      console.log("No data to write.");
      return;
    }

    let sheet = spreadsheet.getSheetByName(sheetName);
    if (!sheet) {
      sheet = spreadsheet.insertSheet(sheetName);
    }

    let headers = [];
    const lastRowBefore = sheet.getLastRow();
    const lastColBefore = sheet.getLastColumn();
    const hasExistingHeaders = lastRowBefore > 0 && lastColBefore > 0;

    if (mode === 'overwrite') {
      if (hasExistingHeaders) {
        headers = sheet.getRange(1, 1, 1, lastColBefore).getValues()[0];
        const maxRows = sheet.getMaxRows();
        if (maxRows > 1 && lastColBefore > 0) {
          sheet.getRange(2, 1, maxRows - 1, lastColBefore).clearContent();
        }
      } else {
        const allKeys = new Set();
        data.forEach(obj => Object.keys(obj).forEach(k => allKeys.add(k)));
        headers = Array.from(allKeys);
        if (headers.length > 0) {
          sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
        }
      }
    } else {
      const lastRow = sheet.getLastRow();
      if (lastRow === 0) {
        const allKeys = new Set();
        data.forEach(obj => Object.keys(obj).forEach(k => allKeys.add(k)));
        headers = Array.from(allKeys);
        if (headers.length > 0) {
          sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
        }
      } else {
        const lastCol = sheet.getLastColumn();
        if (lastCol > 0) {
          headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
        }
      }
    }

    if (headers.length === 0) {
      console.error("Could not determine headers.");
      return;
    }

    const rows = data.map(rowObj => {
      return headers.map(header => {
        return rowObj[header] !== undefined ? rowObj[header] : "";
      });
    });

    if (rows.length > 0) {
      const targetRow = (mode === 'overwrite') ? 2 : sheet.getLastRow() + 1;
      sheet.getRange(targetRow, 1, rows.length, headers.length).setValues(rows);
    }

    SpreadsheetApp.flush();
    console.log(`Successfully wrote ${rows.length} rows to ${sheetName} in ${mode} mode.`);
  },
  writeToSheet_V2: function (sheetName, data, mode = 'append', spreadsheet = SheetById) {
    if (!data || data.length === 0) {
      console.log("No data to write.");
      return;
    }

    let sheet = spreadsheet.getSheetByName(sheetName);
    if (!sheet) {
      sheet = spreadsheet.insertSheet(sheetName);
    }

    // --- NEW "DELTA" MODE BLOCK ---
    if (mode === 'update') {
      const dataRange = sheet.getDataRange();
      const sheetValues = dataRange.getValues();

      // If sheet is empty or only has headers, we can't update rows
      if (sheetValues.length < 2) {
        console.log("Sheet is empty or missing headers, cannot perform delta update.");
        return;
      }

      const sheetHeaders = sheetValues[0];
      const headerMap = {};

      // Create a quick lookup map for column indices
      sheetHeaders.forEach((h, i) => {
        if (h) headerMap[h.toString().trim()] = i;
      });

      let updateCount = 0;

      // Modify the data in memory
      data.forEach(obj => {
        // Skip if row_ is missing
        if (!obj.hasOwnProperty('row_')) return;

        const rowIndex = obj.row_ - 1; // Convert 1-based row_ to 0-based array index

        // Ensure the row actually exists in the sheet bounds
        if (rowIndex > 0 && rowIndex < sheetValues.length) {
          let rowModified = false;

          Object.keys(obj).forEach(key => {
            // Update only if the key matches a valid column header
            if (key !== 'row_' && headerMap.hasOwnProperty(key)) {
              const colIndex = headerMap[key];
              sheetValues[rowIndex][colIndex] = obj[key];
              rowModified = true;
            }
          });
          if (rowModified) updateCount++;
        }
      });

      // Write the entire updated grid back in one go (FAST)
      if (updateCount > 0) {
        dataRange.setValues(sheetValues);
        console.log(`Successfully updated ${updateCount} rows in 'delta' update mode.`);
      } else {
        console.log("No matching rows found to update.");
      }

      SpreadsheetApp.flush();
      return; // EXIT FUNCTION HERE for delta mode
    }
    // --- END "DELTA" MODE BLOCK ---

    // ... Original Logic for 'overwrite' and 'append' continues below ...

    let headers = [];
    const lastRowBefore = sheet.getLastRow();
    const lastColBefore = sheet.getLastColumn();
    const hasExistingHeaders = lastRowBefore > 0 && lastColBefore > 0;

    if (mode === 'overwrite') {
      if (hasExistingHeaders) {
        headers = sheet.getRange(1, 1, 1, lastColBefore).getValues()[0];
        const maxRows = sheet.getMaxRows();
        // Ensure we don't error if there are no rows to clear
        if (maxRows > 1 && lastColBefore > 0) {
          // Only clear if there is content to clear
          try {
            sheet.getRange(2, 1, maxRows - 1, lastColBefore).clearContent();
          } catch (e) {
            // Ignore range errors if sheet is technically empty
          }
        }
      } else {
        const allKeys = new Set();
        data.forEach(obj => Object.keys(obj).forEach(k => allKeys.add(k)));
        headers = Array.from(allKeys);
        if (headers.length > 0) {
          sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
        }
      }
    } else { // Append mode
      const lastRow = sheet.getLastRow();
      if (lastRow === 0) {
        const allKeys = new Set();
        data.forEach(obj => Object.keys(obj).forEach(k => allKeys.add(k)));
        headers = Array.from(allKeys);
        if (headers.length > 0) {
          sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
        }
      } else {
        const lastCol = sheet.getLastColumn();
        if (lastCol > 0) {
          headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
        }
      }
    }

    if (headers.length === 0) {
      console.error("Could not determine headers.");
      return;
    }

    const rows = data.map(rowObj => {
      return headers.map(header => {
        return rowObj[header] !== undefined ? rowObj[header] : "";
      });
    });

    if (rows.length > 0) {
      const targetRow = (mode === 'overwrite') ? 2 : sheet.getLastRow() + 1;
      sheet.getRange(targetRow, 1, rows.length, headers.length).setValues(rows);
    }

    SpreadsheetApp.flush();
    console.log(`Successfully wrote ${rows.length} rows to ${sheetName} in ${mode} mode.`);
  },
  /**
 * Retrieves data from a specific sheet, converts to objects, and adds the specific row number.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet - The spreadsheet object.
 * @param {string} sheetName - The name of the sheet to read.
 * @return {Array<Object>} Array of objects with headers as keys plus a "row_" key.
 */
  getSheetObjects: function (sheetName, spreadsheet = SheetById) {
    const sheet = spreadsheet.getSheetByName(sheetName);

    if (!sheet) {
      console.error(`Sheet "${sheetName}" not found.`);
      return [];
    }

    const values = sheet.getDataRange().getValues();

    if (values.length < 2) return [];

    const headers = values.shift(); // Removes Row 1 (Headers)

    // Map remaining rows
    return values.map((row, index) => {
      const obj = {};

      // Map headers to values
      headers.forEach((header, colIndex) => {
        if (header) {
          obj[header.toString().trim()] = row[colIndex];
        }
      });

      // Add the Sheet Row Number
      // index 0 = Row 2 (because we shifted Row 1 out)
      obj['row_'] = index + 2;

      return obj;
    });
  },
  processRowsForIds: function (sheet, range) {
    const startRow = range.getRow();
    const numRows = range.getNumRows();

    // We explicitly get the range for Col A (1) and Col B (2) for the rows edited.
    // getRange(row, column, numRows, numColumns)
    const targetRange = sheet.getRange(startRow, 1, numRows, 2);
    const values = targetRange.getValues();

    let isModified = false;

    // Loop through the values (handles single edits and bulk copy-pastes)
    for (let i = 0; i < values.length; i++) {
      const idVal = values[i][0];   // Column A
      const dataVal = values[i][1]; // Column B

      // Logic: If ID is empty AND Data (Col B) is NOT empty
      if (idVal === "" && dataVal !== "") {
        values[i][0] = Util.generateId();
        isModified = true;
      }
    }

    // Write back only if we generated new IDs
    if (isModified) {
      // Map out just the first column (IDs) to write back to Col A
      const idsToWrite = values.map(row => [row[0]]);
      sheet.getRange(startRow, 1, numRows, 1).setValues(idsToWrite);
    }
  }
}