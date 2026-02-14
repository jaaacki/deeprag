function getParentFolders_V2() {
  try {
    const params = 'ParentId=4&SortBy=Name&IsFolder=true&ExcludeItemIds=4';
    const response = EmbyService.getItems(params);

    if (!response.success) {
      throw new Error(`Failed to fetch data from Emby API: ${response.error}`);
    }

    const data = response.data;
    if (!data.Items || !Array.isArray(data.Items)) {
      throw new Error('Invalid response structure from Emby API');
    }

    // Map the items to an array of Objects with specific keys
    const formattedData = data.Items.map(item => ({
      Name: item.Name || '',
      Id: item.Id || '',
      Type: item.Type || '',
      ChildIds: '', // Placeholder: Empty string as requested
      Count: ''     // Placeholder: Empty string as requested
    }));

    // Log to verify structure
    Logger.log(`Mapped ${formattedData.length} items.`);
    if (formattedData.length > 0) {
      Logger.log('First item sample: ' + JSON.stringify(formattedData[0]));
    }

    // Pass the array of objects (formattedData) instead of the raw 'data'
    Sheet.writeToSheet('parentFolders', formattedData, 'overwrite');

    Logger.log(`Success: ${formattedData.length} parent folders added to sheet`)
    return formattedData;

  } catch (error) {
    Logger.log(`Error in getParentFolders: ${error.toString()}`);
    throw new Error(`Failed to get parent folders: ${error.toString()}`);
  }
}

function fetchIds () {
  const parentFolders = Sheet.getSheetObjects('parentFolders')
  // Logger.log(parentFolders)

  const ids = Util.pickItemsFromObject(parentFolders, 'Id')
  Logger.log(ids)
}

function getParentChildFoldersFast_V2(ids = null, batchSize = 250) {
  /** Scan Library First */
  EmbyService.scanLibrary(4);
  Utilities.sleep(2000);
  EmbyService.generateVideoPreview();

  try {
    // 1. Fetch all parent objects from the sheet
    // This returns an array of objects, e.g., [{Id: 123, Name: 'Movie', ...}, ...]
    const parentFolders = Sheet.getSheetObjects('parentFolders');
    Logger.log(parentFolders)
    if (!parentFolders || parentFolders.length === 0) {
      throw new Error('No data found in parentFolders sheet.');
    }

    // 2. Determine which IDs to process
    let targetIds = [];

    if (ids) {
      // Use provided IDs
      if (!Array.isArray(ids)) {
        throw new Error('Input "ids" must be an array.');
      }
      targetIds = ids;
    } else {
      // Fetch on its own if not provided
      targetIds = Util.pickItemsFromObject(parentFolders, 'Id');
    }

    // 3. Validate that targetIds is an array of numbers
    // We allow strings that can be converted to valid numbers (e.g. "12345")
    const isValid = targetIds.every(id => {
      return id !== null && id !== '' && !isNaN(Number(id));
    });

    if (!isValid) {
      throw new Error('Validation Failed: "ids" must contain only numbers.');
    }

    if (targetIds.length === 0) return 'Nothing to fetch';

    // 4. Fetch data from Emby
    // Params: Recursive=true, SortBy=Id, IsFolder=false
    const results = EmbyService.getItemsAllByParentIds(targetIds, 'Recursive=true&SortBy=Id&IsFolder=false', batchSize);

    // Create a map for fast lookup: parentId -> { itemIds: [], total: 0 }
    const resultMap = {};
    results.forEach(r => {
      if (r.success && r.data && r.data.Items) {
        resultMap[r.parentId] = {
          items: r.data.Items.map(it => it.Id), // Array of Child IDs
          total: Number(r.data.TotalRecordCount) || r.data.Items.length
        };
      }
    });

    // 5. Form the childIds and push back into parentFolders
    // We also collect the raw child IDs to return at the end
    let allCollectedChildIds = [];

    parentFolders.forEach(folder => {
      const pId = String(folder.Id); // Ensure string comparison
      
      // We only update the folder if we have a fresh result for it.
      // If ids were filtered, we only touch those rows.
      if (resultMap[pId]) {
        const data = resultMap[pId];
        
        // 1. Update the object properties (assumes headers 'childIds' and 'childCount' exist)
        folder.ChildIds = data.items.join(','); 
        folder.Count = data.total; 

        // 2. Collect raw IDs for return
        allCollectedChildIds = allCollectedChildIds.concat(data.items);
      }
    });

    Logger.log(parentFolders)

    // 6. Write back to sheet
    // 'update' mode usually implies using the Id column to update rows
    Sheet.writeToSheet_V2('parentFolders', parentFolders, 'overwrite');

    // 7. Return the raw child IDs (Array, not string)
    return allCollectedChildIds;

  } catch (e) {
    Logger.log(`Error in getParentChildFoldersFast_V2: ${e}`);
    throw new Error(`Failed: ${e}`);
  }
}