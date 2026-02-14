function getParentFolders() {
  try {
    // Use EmbyService to fetch data from Emby API
    const params = 'ParentId=4&SortBy=Name&IsFolder=true&ExcludeItemIds=4';
    const response = EmbyService.getItems(params);

    if (!response.success) {
      throw new Error(`Failed to fetch data from Emby API: ${response.error}`);
    }

    const data = response.data;
    if (!data.Items || !Array.isArray(data.Items)) {
      throw new Error('Invalid response structure from Emby API');
    }

    // Get or create the spreadsheet
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

    // Check if "parentFolders" sheet exists, if not create it
    let sheet = spreadsheet.getSheetByName('parentFolders');
    if (!sheet) {
      sheet = spreadsheet.insertSheet('parentFolders');
    } else {
      // Clear existing content if sheet exists
      sheet.clear();
    }

    // Set headers
    const headers = ['Name', 'Id', 'Type', 'ChildIds', 'Count'];
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

    // Prepare data rows
    const rows = data.Items.map(item => [
      item.Name || '',
      item.Id || '',
      item.Type || '',
      '', // ChildIds - will be empty for now
      ''  // Count - will be empty for now
    ]);

    // Write data to sheet
    if (rows.length > 0) {
      sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
    }

    // Format the sheet
    sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sheet.autoResizeColumns(1, headers.length);

    Logger.log(`Successfully populated parentFolders sheet with ${rows.length} items`);
    return `Success: ${rows.length} parent folders added to sheet`;

  } catch (error) {
    Logger.log(`Error in getParentFolders: ${error.toString()}`);
    throw new Error(`Failed to get parent folders: ${error.toString()}`);
  }
}

function getParentChildFolders() {
  try {
    // Get the spreadsheet and parentFolders sheet
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = spreadsheet.getSheetByName('parentFolders');

    if (!sheet) {
      throw new Error('parentFolders sheet not found. Please run getParentFolders() first.');
    }

    // Get all data from the sheet
    const lastRow = sheet.getLastRow();
    if (lastRow <= 1) {
      throw new Error('No data found in parentFolders sheet.');
    }

    // Get the data range (skip header row)
    const dataRange = sheet.getRange(2, 1, lastRow - 1, 5);
    const data = dataRange.getValues();

    // Process each parent folder
    for (let i = 0; i < data.length; i++) {
      const parentId = data[i][1]; // Id column (column B, index 1)

      if (!parentId) {
        Logger.log(`Skipping row ${i + 2}: No parent ID found`);
        continue;
      }

      try {
        // Use EmbyService to fetch child folders for this parent
        const params = `ParentId=${parentId}&Recursive=true&SortBy=Id&IsFolder=false`;
        const response = EmbyService.getItems(params);

        if (!response.success) {
          throw new Error(`API request failed: ${response.error}`);
        }

        const childData = response.data;

        if (childData.Items && Array.isArray(childData.Items)) {
          // Extract all child IDs
          const childIds = childData.Items.map(item => item.Id).filter(id => id);
          const childIdsString = childIds.join(',');
          const totalCount = childData.TotalRecordCount || childIds.length;

          // Update the sheet row with child IDs and count
          sheet.getRange(i + 2, 4).setValue(childIdsString); // Column D (ChildIds)
          sheet.getRange(i + 2, 5).setValue(totalCount);     // Column E (Count)

          Logger.log(`Updated parent ${parentId}: ${childIds.length} children, total count: ${totalCount}`);
        } else {
          Logger.log(`No valid child data found for parent ${parentId}`);
          sheet.getRange(i + 2, 4).setValue(''); // Empty ChildIds
          sheet.getRange(i + 2, 5).setValue(0);  // Zero count
        }

        // Add a small delay to avoid hitting API rate limits
        Utilities.sleep(100);

      } catch (apiError) {
        Logger.log(`Error fetching children for parent ${parentId}: ${apiError.toString()}`);
        sheet.getRange(i + 2, 4).setValue('ERROR');
        sheet.getRange(i + 2, 5).setValue(0);
      }
    }

    // Auto-resize columns after updating
    sheet.autoResizeColumns(1, 5);

    Logger.log(`Successfully updated child folders data for ${data.length} parent folders`);
    return `Success: Updated child data for ${data.length} parent folders`;

  } catch (error) {
    Logger.log(`Error in getParentChildFolders: ${error.toString()}`);
    throw new Error(`Failed to get parent child folders: ${error.toString()}`);
  }
}

function getChildItems() {
  try {
    // Get the spreadsheet
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

    // Get parentFolders sheet
    const parentSheet = spreadsheet.getSheetByName('parentFolders');
    if (!parentSheet) {
      throw new Error('parentFolders sheet not found. Please run getParentFolders() and getParentChildFolders() first.');
    }

    // Check if "items" sheet exists, if not create it
    let itemsSheet = spreadsheet.getSheetByName('items');
    if (!itemsSheet) {
      itemsSheet = spreadsheet.insertSheet('items');
    }

    // Set headers for items sheet
    const headers = [
      'Processed', 'Url', 'Id', 'ParentId', 'ParentName', 'MovieCode', 'Name', 'Path',
      'OriginalTitle', 'SortName', 'ProductionYear', 'PremiereDate',
      'PreferredMetadataLanguage', 'PreferredMetadataCountryCode', 'LockData',
      'People1.Id', 'People1.Name', 'People1.Type', 'People1.PrimaryImageTag',
      'Studio.Id', 'Studio.Name', 'missAv_status', 'missAv_movie_code', 'missAv_title',
      'missAv_raw_image_url', 'missAv_image_cropped', 'missAv_overview', 'missAv_release_date',
      'missAv_original_title', 'missAv_actress', 'missAv_genre', 'missAv_series', 'missAv_maker', 'missAv_label'
    ];

    // Set headers if this is a fresh sheet
    if (itemsSheet.getLastRow() === 0) {
      itemsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      itemsSheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    }

    // Get existing items to avoid duplicates
    const existingItemIds = new Set();
    if (itemsSheet.getLastRow() > 1) {
      const existingData = itemsSheet.getRange(2, 3, itemsSheet.getLastRow() - 1, 1).getValues();
      existingData.forEach(row => {
        if (row[0] && row[0].toString().trim()) {
          existingItemIds.add(row[0].toString().trim());
        }
      });
    }

    Logger.log(`Found ${existingItemIds.size} existing items in sheet`);

    // Get all data from parentFolders sheet
    const lastRow = parentSheet.getLastRow();
    if (lastRow <= 1) {
      throw new Error('No data found in parentFolders sheet.');
    }

    const parentData = parentSheet.getRange(2, 1, lastRow - 1, 5).getValues();
    const newItems = [];
    let totalNewItems = 0;

    // Collect all valid child IDs from parentFolders sheet
    const allValidChildIds = new Set();
    
    // First pass: collect all valid child IDs
    for (let i = 0; i < parentData.length; i++) {
      const childIdsString = parentData[i][3]; // ChildIds column
      if (childIdsString && childIdsString !== 'ERROR') {
        const childIds = childIdsString.split(',').map(id => id.trim()).filter(id => id);
        childIds.forEach(id => allValidChildIds.add(id.toString().trim()));
      }
    }

    // Remove items that no longer exist in parentFolders childIds
    if (itemsSheet.getLastRow() > 1) {
      const itemsData = itemsSheet.getRange(2, 1, itemsSheet.getLastRow() - 1, itemsSheet.getLastColumn()).getValues();
      const rowsToDelete = [];
      
      for (let i = 0; i < itemsData.length; i++) {
        const itemId = itemsData[i][2]; // Id column (index 2)
        if (itemId && !allValidChildIds.has(itemId.toString().trim())) {
          rowsToDelete.push(i + 2); // Actual row number (adding 2 for header and 0-based index)
        }
      }
      
      // Delete rows in reverse order to maintain correct row numbers
      if (rowsToDelete.length > 0) {
        rowsToDelete.reverse().forEach(rowNum => {
          itemsSheet.deleteRow(rowNum);
        });
        Logger.log(`Removed ${rowsToDelete.length} items that no longer exist in parentFolders`);
        
        // Refresh existing item IDs after deletion
        existingItemIds.clear();
        if (itemsSheet.getLastRow() > 1) {
          const refreshedData = itemsSheet.getRange(2, 3, itemsSheet.getLastRow() - 1, 1).getValues();
          refreshedData.forEach(row => {
            if (row[0] && row[0].toString().trim()) {
              existingItemIds.add(row[0].toString().trim());
            }
          });
        }
      }
    }

    // Process each parent folder
    for (let i = 0; i < parentData.length; i++) {
      const parentName = parentData[i][0]; // Name column
      const parentId = parentData[i][1];   // Id column
      const childIdsString = parentData[i][3]; // ChildIds column

      if (!childIdsString || childIdsString === 'ERROR' || !parentId) {
        continue;
      }

      // Split child IDs by comma
      const childIds = childIdsString.split(',').map(id => id.trim()).filter(id => id);

      // Process each child ID
      for (const childId of childIds) {
        // Skip if this ID already exists (ensure string comparison)
        if (existingItemIds.has(childId.toString().trim())) {
          continue;
        }

        // Create URL for this item
        // const itemUrl = `https://emby.familyhub.id/web/index.html#!/item?serverId=ede55745c07b412c8e2e55b0737d4c9e&id=${childId}`;
        const itemUrl = '';
        
        // Create new item row
        const newItem = [
          false,        // Processed (checkbox - default empty/false)
          itemUrl,      // Url
          childId,      // Id
          parentId,     // ParentId
          parentName,   // ParentName
          '',           // Movie Code (blank for now)
          '',           // Name (blank for now)
          '',           // Path (blank for now)
          '',           // OriginalTitle (blank for now)
          '',           // SortName (blank for now)
          '',           // ProductionYear (blank for now)
          '',           // PremiereDate (blank for now)
          '',           // PreferredMetadataLanguage (blank for now)
          '',           // PreferredMetadataCountryCode (blank for now)
          '',           // LockData (blank for now)
          '',           // People1.Id (blank for now)
          '',           // People1.Name (blank for now)
          '',           // People1.Type (blank for now)
          '',           // People1.PrimaryImageTag (blank for now)
          '',           // Studio.Id (blank for now)
          '',           // Studio.Name (blank for now)
          '',           // missAv_status (blank for now)
          '',           // missAv_movie_code (blank for now)
          '',           // missAv_title (blank for now)
          '',           // missAv_raw_image_url (blank for now)
          '',           // missAv_image_cropped (blank for now)
          '',           // missAv_overview (blank for now)
          '',           // missAv_release_date (blank for now)
          '',           // missAv_original_title (blank for now)
          '',           // missAv_actress (blank for now)
          '',           // missAv_genre (blank for now)
          '',           // missAv_series (blank for now)
          '',           // missAv_maker (blank for now)
          ''            // missAv_label (blank for now)
        ];

        newItems.push(newItem);
        existingItemIds.add(childId.toString().trim()); // Add to set to prevent duplicates
        totalNewItems++;
      }
    }

    // Add new items to sheet if any
    if (newItems.length > 0) {
      // Sort new items by Id (ascending)
      newItems.sort((a, b) => a[2].localeCompare(b[2]));

      const startRow = itemsSheet.getLastRow() + 1;
      itemsSheet.getRange(startRow, 1, newItems.length, headers.length).setValues(newItems);

      // Set checkbox formatting for Processed column
      const processedRange = itemsSheet.getRange(startRow, 1, newItems.length, 1);
      processedRange.insertCheckboxes();

      // Auto-resize columns
      // itemsSheet.autoResizeColumns(1, headers.length);

      // Sort entire data by Id column (ascending)
      if (itemsSheet.getLastRow() > 2) {
        const dataRange = itemsSheet.getRange(2, 1, itemsSheet.getLastRow() - 1, headers.length);
        dataRange.sort(3); // Sort by column 3 (Id)
      }
    }

    Logger.log(`Successfully populated items sheet with ${totalNewItems} new items`);
    return `Success: ${totalNewItems} new items added to sheet (duplicates ignored)`;

  } catch (error) {
    Logger.log(`Error in getChildItems: ${error.toString()}`);
    throw new Error(`Failed to get child items: ${error.toString()}`);
  }
}

function getChildItems_V2(parentData) {
  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    
    // --- SETUP SHEETS ---
    let itemsSheet = spreadsheet.getSheetByName('items');
    if (!itemsSheet) {
      itemsSheet = spreadsheet.insertSheet('items');
    }

    // Set headers
    const headers = [
      'Processed', 'Url', 'Id', 'ParentId', 'ParentName', 'MovieCode', 'Name', 'Path',
      'OriginalTitle', 'SortName', 'ProductionYear', 'PremiereDate',
      'PreferredMetadataLanguage', 'PreferredMetadataCountryCode', 'LockData',
      'People1.Id', 'People1.Name', 'People1.Type', 'People1.PrimaryImageTag',
      'Studio.Id', 'Studio.Name', 'missAv_status', 'missAv_movie_code', 'missAv_title',
      'missAv_raw_image_url', 'missAv_image_cropped', 'missAv_overview', 'missAv_release_date',
      'missAv_original_title', 'missAv_actress', 'missAv_genre', 'missAv_series', 'missAv_maker', 'missAv_label'
    ];

    if (itemsSheet.getLastRow() === 0) {
      itemsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      itemsSheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    }

    // --- PRUNING LOGIC ---
    // Collect all valid child IDs from the passed parentData
    const allValidChildIds = new Set();
    parentData.forEach(parent => {
      parent.childIds.forEach(id => allValidChildIds.add(id.toString().trim()));
    });

    // Remove items that no longer exist in parentData
    if (itemsSheet.getLastRow() > 1) {
      const itemsData = itemsSheet.getRange(2, 1, itemsSheet.getLastRow() - 1, itemsSheet.getLastColumn()).getValues();
      const rowsToDelete = [];
      
      for (let i = 0; i < itemsData.length; i++) {
        const itemId = itemsData[i][2]; // Id column (index 2)
        if (itemId && !allValidChildIds.has(itemId.toString().trim())) {
          rowsToDelete.push(i + 2); 
        }
      }
      
      // Delete in reverse order
      if (rowsToDelete.length > 0) {
        rowsToDelete.reverse().forEach(rowNum => itemsSheet.deleteRow(rowNum));
        Logger.log(`Removed ${rowsToDelete.length} orphaned items`);
      }
    }

    // --- DUPLICATE CHECK ---
    const existingItemIds = new Set();
    if (itemsSheet.getLastRow() > 1) {
      const existingData = itemsSheet.getRange(2, 3, itemsSheet.getLastRow() - 1, 1).getValues();
      existingData.forEach(row => {
        if (row[0]) existingItemIds.add(row[0].toString().trim());
      });
    }

    // --- ADDITION LOGIC ---
    const newItems = [];
    
    // Iterate through the PASSED parentData parameter
    for (const parent of parentData) {
      for (const childId of parent.childIds) {
        
        // Skip existing
        if (existingItemIds.has(childId.toString().trim())) {
          continue;
        }

        const itemUrl = '';
        
        const newItem = [
          false,        // Processed
          itemUrl,      // Url
          childId,      // Id
          parent.id,    // ParentId (from passed object)
          parent.name,  // ParentName (from passed object)
          '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '' 
        ];

        newItems.push(newItem);
        existingItemIds.add(childId.toString().trim());
      }
    }

    // --- WRITE TO SHEET ---
    if (newItems.length > 0) {
      newItems.sort((a, b) => a[2].localeCompare(b[2]));

      const startRow = itemsSheet.getLastRow() + 1;
      itemsSheet.getRange(startRow, 1, newItems.length, headers.length).setValues(newItems);
      itemsSheet.getRange(startRow, 1, newItems.length, 1).insertCheckboxes();

      if (itemsSheet.getLastRow() > 2) {
        itemsSheet.getRange(2, 1, itemsSheet.getLastRow() - 1, headers.length).sort(3); 
      }
    }

    Logger.log(`Successfully added ${newItems.length} new items`);
    return `Success: ${newItems.length} new items added`;

  } catch (error) {
    Logger.log(`Error in getChildItems: ${error.toString()}`);
    throw new Error(`Failed to get child items: ${error.toString()}`);
  }
}

function populateItemDetails(opts) {
  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const itemsSheet = spreadsheet.getSheetByName('items');
    if (!itemsSheet) throw new Error('items sheet not found. Please run getChildItems() first.');

    const lastRow = itemsSheet.getLastRow();
    if (lastRow <= 1) throw new Error('No data found in items sheet.');

    const headers = itemsSheet.getRange(1, 1, 1, itemsSheet.getLastColumn()).getValues()[0];
    const columnMap = {};
    headers.forEach((header, index) => { columnMap[header] = index + 1; });

    const itemsData = itemsSheet.getRange(2, 1, lastRow - 1, itemsSheet.getLastColumn()).getValues();

    const direction = (opts && String(opts.direction).toLowerCase() === 'backward') ? 'backward' : 'forward';
    if (Config?.debug?.level > 0) Logger.log('populateItemDetails() start | direction=' + direction + ' | totalRows=' + itemsData.length);

    let processedCount = 0;
    let errorCount = 0;

    for (let k = 0; k < itemsData.length; k++) {
      const i = direction === 'forward' ? k : (itemsData.length - 1 - k);
      const rowIndex = i + 2;
      const row = itemsData[i];

      const itemId = row[columnMap['Id'] - 1];
      const currentName = row[columnMap['Name'] - 1];
      const currentPath = row[columnMap['Path'] - 1];

      if (currentName && currentPath) continue;
      if (!itemId) { Logger.log('Skipping row ' + rowIndex + ': No item ID found'); continue; }

      if (Config?.debug?.level > 1) Logger.log('Processing idx=' + i + ' row=' + rowIndex + ' itemId=' + itemId);

      try {
        const response = EmbyService.getItemDetails(itemId);
        if (!response.success) throw new Error('API request failed: ' + response.error);

        const itemData = response.data;
        const updates = [];

        if (itemData.Name && columnMap['Name']) updates.push([rowIndex, columnMap['Name'], itemData.Name]);
        if (itemData.Path && columnMap['Path']) updates.push([rowIndex, columnMap['Path'], itemData.Path]);
        if (itemData.Path && columnMap['MovieCode']) {
          const movieCode = extractMovieCodeFromPath(itemData.Path);
          if (movieCode) updates.push([rowIndex, columnMap['MovieCode'], movieCode]);
        }
        if (itemData.OriginalTitle && columnMap['OriginalTitle']) updates.push([rowIndex, columnMap['OriginalTitle'], itemData.OriginalTitle]);
        if (itemData.SortName && columnMap['SortName']) updates.push([rowIndex, columnMap['SortName'], itemData.SortName]);
        if (itemData.ProductionYear && columnMap['ProductionYear']) updates.push([rowIndex, columnMap['ProductionYear'], itemData.ProductionYear]);
        if (itemData.PremiereDate && columnMap['PremiereDate']) updates.push([rowIndex, columnMap['PremiereDate'], itemData.PremiereDate]);
        if (itemData.PreferredMetadataLanguage && columnMap['PreferredMetadataLanguage']) updates.push([rowIndex, columnMap['PreferredMetadataLanguage'], itemData.PreferredMetadataLanguage]);
        if (itemData.PreferredMetadataCountryCode && columnMap['PreferredMetadataCountryCode']) updates.push([rowIndex, columnMap['PreferredMetadataCountryCode'], itemData.PreferredMetadataCountryCode]);
        if (itemData.LockData !== undefined && columnMap['LockData']) updates.push([rowIndex, columnMap['LockData'], itemData.LockData]);

        if (itemData.People && itemData.People.length > 0) {
          const firstPerson = itemData.People[0];
          if (firstPerson.Id && columnMap['People1.Id']) updates.push([rowIndex, columnMap['People1.Id'], firstPerson.Id]);
          if (firstPerson.Name && columnMap['People1.Name']) updates.push([rowIndex, columnMap['People1.Name'], firstPerson.Name]);
          if (firstPerson.Type && columnMap['People1.Type']) updates.push([rowIndex, columnMap['People1.Type'], firstPerson.Type]);
          if (firstPerson.PrimaryImageTag && columnMap['People1.PrimaryImageTag']) updates.push([rowIndex, columnMap['People1.PrimaryImageTag'], firstPerson.PrimaryImageTag]);
        }

        if (itemData.Studios && itemData.Studios.length > 0) {
          const firstStudio = itemData.Studios[0];
          if (firstStudio.Id && columnMap['Studio.Id']) updates.push([rowIndex, columnMap['Studio.Id'], firstStudio.Id]);
          if (firstStudio.Name && columnMap['Studio.Name']) updates.push([rowIndex, columnMap['Studio.Name'], firstStudio.Name]);
        }

        updates.forEach(([r, c, v]) => itemsSheet.getRange(r, c).setValue(v));
        SpreadsheetApp.flush();

        processedCount++;
        if (Config?.debug?.level > 0) Logger.log('Updated item ' + itemId + ' (row ' + rowIndex + ') with ' + updates.length + ' fields');
        Utilities.sleep(100);
      } catch (apiError) {
        Logger.log('Error fetching details for item ' + itemId + ' (row ' + rowIndex + '): ' + apiError.toString());
        errorCount++;
      }
    }

    if (Config?.debug?.level > 0) Logger.log('Successfully processed ' + processedCount + ' items, ' + errorCount + ' errors');
    return 'Success: Updated ' + processedCount + ' items with details (' + errorCount + ' errors)';
  } catch (error) {
    Logger.log('Error in populateItemDetails: ' + error.toString());
    throw new Error('Failed to populate item details: ' + error.toString());
  }
}


function populateItemDetailsFromStart() {
  return populateItemDetails({ direction: 'forward' });
}

function populateItemDetailsFromEnd() {
  return populateItemDetails({ direction: 'backward' });
}


/**
 * Helper function to extract movie code from file path
 * Extracts movie code using regex pattern: 3-6 chars followed by '-' then 2-5 numbers
 * @param {string} path - The file path string
 * @returns {string} - The extracted movie code or empty string if not found
 */
function extractMovieCodeFromPath(path) {
  if (!path || typeof path !== 'string') {
    return '';
  }

  try {
    // Regex pattern: 3-6 alphanumeric characters, followed by '-', then 2-5 digits
    const movieCodePattern = /[A-Za-z]{2,6}-\d{2,5}/;
    
    const match = path.match(movieCodePattern);
    
    if (match) {
      return match[0];
    }
    
    return '-';

  } catch (error) {
    Logger.log(`Error extracting movie code from path: ${error.toString()}`);
    return '';
  }
}

/** Webhook to trigger schedule task - Generate Preview */
function embyGeneratePreviewHook() {
  EmbyService.generateVideoPreview()
}