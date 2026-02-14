function getParentFolders() {
  /** Scan Library First */
  EmbyService.scanLibrary(4)
  Utilities.sleep(2000)
  EmbyService.generateVideoPreview()
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
      // Clear existing content but preserve formatting
      sheet.clearContents();
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
    Logger.log(`Successfully populated parentFolders sheet with ${rows.length} items`);
    return `Success: ${rows.length} parent folders added to sheet`;
  } catch (error) {
    Logger.log(`Error in getParentFolders: ${error.toString()}`);
    throw new Error(`Failed to get parent folders: ${error.toString()}`);
  }
}

function wrapperGetParentChildFoldersFast() {
  getParentChildFoldersFast(120)
}
function wrapperGetChildItems() {
  getChildItems()
  populateItemDetailsFromStart()
}


function getParentChildFoldersFast(batchSize = 60) {
  /** Scan Library First */
  EmbyService.scanLibrary(4)
  Utilities.sleep(2000)
  EmbyService.generateVideoPreview()
  try {
    const sheet = SheetById.getSheetByName('parentFolders');
    if (!sheet) throw new Error('parentFolders sheet not found. Please run getParentFolders() first.');
    const lastRow = sheet.getLastRow();
    if (lastRow <= 1) throw new Error('No data found in parentFolders sheet.');
    const data = sheet.getRange(2, 1, lastRow - 1, 5).getValues();
    const parentIds = data.map(r => r[1]).map(x => (x || '').toString().trim());
    const idxMap = {};
    parentIds.forEach((id, i) => { if (id) idxMap[id] = i; });
    const ids = parentIds.filter(Boolean);
    if (!ids.length) return 'Nothing to fetch';
    const results = EmbyService.getItemsAllByParentIds(ids, 'Recursive=true&SortBy=Id&IsFolder=false', batchSize || 40);
    const outD = new Array(data.length).fill(['']);
    const outE = new Array(data.length).fill([0]);
    results.forEach(r => {
      const i = idxMap[r.parentId];
      if (i == null) return;
      if (r.success && r.data && r.data.Items) {
        const items = r.data.Items || [];
        const idsStr = items.map(it => it.Id).filter(Boolean).join(',');
        const total = Number(r.data.TotalRecordCount) || items.length;
        outD[i] = [idsStr];
        outE[i] = [total];
      } else {
        outD[i] = ['ERROR'];
        outE[i] = [0];
      }
    });
    sheet.getRange(2, 4, outD.length, 1).setValues(outD);
    sheet.getRange(2, 5, outE.length, 1).setValues(outE);
    return `Success: Updated child data for ${ids.length} parent folders`;
  } catch (e) {
    Logger.log(`Error in getParentChildFoldersFast: ${e}`);
    throw new Error(`Failed: ${e}`);
  }
}

function populateItemDetails_2() {
  const items = Me.Items.where(row => row.Id !== '' && row.Name === '').all()
  Logger.log(items.length)
  items.forEach((item, i) => {
    try {
      const emby = EmbyService.getItemDetails(item.Id).data
      const data = mapEmbyToItem(emby)
      Object.keys(data).forEach(k => item[k] = data[k])
      item.save()
    } catch (err) {
      Logger.log(`Error on item ${i} (${item?.Id}): ${err}`)
    }
  })
}

function mapEmbyToItem(emby) {
  const out = {
    Name: emby.Name || '',
    MovieCode: Util.extractMovieCodeFromPath(emby.Path || ''),
    Path: emby.Path || '',
    OriginalTitle: emby.OriginalTitle || '',
    SortName: emby.SortName || '',
    ProductionYear: emby.ProductionYear || '',
    PremiereDate: emby.PremiereDate || '',
    PreferredMetadataLanguage: emby.PreferredMetadataLanguage || '',
    PreferredMetadataCountryCode: emby.PreferredMetadataCountryCode || '',
    LockData: emby.LockData || ''
  }
  if (Array.isArray(emby.People) && emby.People.length) {
    const p = emby.People[0]
    out['People1.Id'] = p.Id || ''
    out['People1.Name'] = p.Name || ''
    out['People1.Type'] = p.Type || ''
    out['People1.PrimaryImageTag'] = p.PrimaryImageTag || ''
  }
  if (Array.isArray(emby.Studios) && emby.Studios.length) {
    const s = emby.Studios[0]
    out['Studio.Id'] = s.Id || ''
    out['Studio.Name'] = s.Name || ''
  }
  return out
}

function getMissAvData() {
  const maxMinutes = 29.5
  const deadline = Date.now() + maxMinutes * 60 * 1000

  const items = Me.Items.where(
    row => row.Id !== '' &&
      row.MovieCode !== '' &&
      row.MovieCode !== '-' &&
      (row.missAv_status === '' || row.missAv_status === 'error')
  ).all()

  Logger.log(items.length)

  for (var i = 0; i < items.length; i++) {
    // stop if deadline reached
    if (Date.now() >= deadline) {
      Logger.log(`Stopping early at item ${i}, time limit reached`)
      break
    }
    try {
      const item = items[i]
      item.url = '';
      const searchResult = searchMissAv(item.MovieCode)

      if (searchResult) {
        item.missAv_status = searchResult.status
        item.missAv_movie_code = searchResult.data.movie_code
        item.missAv_title = searchResult.data.title
        item.missAv_raw_image_url = searchResult.data.raw_image_url
        item.missAv_image_cropped = searchResult.data.image_cropped
        item.missAv_overview = searchResult.data.overview
        item.missAv_release_date = searchResult.data.release_date
        item.missAv_original_title = searchResult.data.original_title
        item.missAv_actress = Util.arrayToString(searchResult.data.actress)
        item.missAv_genre = Util.arrayToString(searchResult.data.genre)
        item.missAv_series = searchResult.data.series
        item.missAv_maker = searchResult.data.maker
        item.missAv_label = searchResult.data.label
        item.missAv_source_url = searchResult.data.source_url
        if (searchResult.status === 'completed') {
          item.Processed = true
        }
        item.save()
      }
    } catch (err) {
      Logger.log(`Error on item ${i} (${items[i]?.Id}): ${err}`)
    }
  }
  Logger.log("Finished run, either completed or timed out.")
}


function getMissAvDataReverseOrder() {
  const maxMinutes = 29.5
  const deadline = Date.now() + maxMinutes * 60 * 1000

  const items = Me.Items.where(
    row => row.Id !== '' &&
      row.MovieCode !== '' &&
      row.MovieCode !== '-' &&
      (row.missAv_status === '' || row.missAv_status === 'error')
  ).all()

  Logger.log(items.length)

  for (let i = items.length - 1; i >= 0; i--) {
    // stop if deadline reached
    if (Date.now() >= deadline) {
      Logger.log(`Stopping early at item ${i}, time limit reached`)
      break
    }
    try {
      const item = items[i]
      item.url = ''
      const searchResult = searchMissAv(item.MovieCode)
      Logger.log(searchResult)

      if (searchResult) {
        item.missAv_status = searchResult.status
        item.missAv_movie_code = searchResult.data.movie_code
        item.missAv_title = searchResult.data.title
        item.missAv_raw_image_url = searchResult.data.raw_image_url
        item.missAv_image_cropped = searchResult.data.image_cropped
        item.missAv_overview = searchResult.data.overview
        item.missAv_release_date = searchResult.data.release_date
        item.missAv_original_title = searchResult.data.original_title
        item.missAv_actress = Util.arrayToString(searchResult.data.actress)
        item.missAv_genre = Util.arrayToString(searchResult.data.genre)
        item.missAv_series = searchResult.data.series
        item.missAv_maker = searchResult.data.maker
        item.missAv_label = searchResult.data.label
        item.missAv_source_url = searchResult.data.source_url
        if (searchResult.status === 'completed') {
          item.Processed = true
        }
        item.save()
      }
    } catch (err) {
      Logger.log(`Error on item ${i} (${items[i]?.Id}): ${err}`)
    }
  }
  Logger.log("Finished run, either completed or timed out.")
}

function updateEmbyItems() {
  const maxMinutes = 29.5
  const deadline = Date.now() + maxMinutes * 60 * 1000
  const toProcess = Me.Items.where(row => row.Processed === true).all()
  for (var i = 0; i < toProcess.length; i++) {
    // stop if deadline reached
    if (Date.now() >= deadline) {
      Logger.log(`Stopping early at item ${i}, time limit reached`)
      break
    }
    const item = toProcess[i];
    item.url = ''
    Logger.log("Processing Item: " + item.Id)
    /** Not valid Item */
    if (item.Id === '' || item.Id === null) {
      item.Processed = ''
      item.save();
    }

    /** With MissAv Data */
    if (item.Id !== '' && item.missAv_status == 'completed') {
      updateEmbyItemWithMissAv(item)
    }

    /** With Internal Data Only */
    if (item.Id !== '' && item.missAv_status !== 'completed') {
      updateEmbyItemWithMissAv(item)
    }
  }
  /** Generate Video Preview - Run Task */
  EmbyService.generateVideoPreview()
  Logger.log("Finished run, either completed or timed out.")
}

function updateEmbyItemsReverse() {
  const maxMinutes = 29.5
  const deadline = Date.now() + maxMinutes * 60 * 1000
  const toProcess = Me.Items.where(row => row.Processed === true).all()
  for (var i = toProcess.length - 1; i >= 0; i--) {
    // stop if deadline reached
    if (Date.now() >= deadline) {
      Logger.log(`Stopping early at item ${i}, time limit reached`)
      break
    }
    const item = toProcess[i];
    item.url = ''
    Logger.log("Processing Item: " + item.Id)
    /** Not valid Item */
    if (item.Id === '' || item.Id === null) {
      item.Processed = ''
      item.save();
      continue
    }

    /** With MissAv Data */
    if (item.missAv_status == 'completed') {
      updateEmbyItemWithMissAv(item)
      continue
    }

    /** With Internal Data Only */
    if (item.missAv_status !== 'completed') {
      updateEmbyItemWithMissAv(item)
    }
  }
  /** Generate Video Preview - Run Task */
  EmbyService.generateVideoPreview()
  Logger.log("Finished run, either completed or timed out.")
}

function updateEmbyItemWithMissAv(obj) {
  if (!obj || !obj.Id) return;

  Logger.log('Updating Item: ' + obj.Id);

  let embyRaw;
  try {
    embyRaw = EmbyService.getItemDetails(obj.Id);
  } catch (e) {
    Logger.log('getItemDetails error: ' + e);
    return;
  }

  const embyItem = embyRaw && embyRaw.data ? embyRaw.data : {};
  if (!embyItem || !embyItem.Id) return;

  embyItem.Name = Util.getNameFromPath(obj.Path || '');
  embyItem.OriginalTitle = obj.missAv_original_title || '';
  embyItem.SortName = Util.getNameFromPath(obj.Path || '');
  embyItem.ForcedSortName = Util.getNameFromPath(obj.Path || '');
  embyItem.Overview = obj.missAv_overview || '';
  embyItem.ProductionYear = Number(Util.getYearFromDate(obj.missAv_release_date || '')) || '';
  embyItem.PremiereDate = Util.dateToString(obj.missAv_release_date || '');
  embyItem.PreferredMetadataLanguage = 'en';
  embyItem.PreferredMetadataCountryCode = 'JP';
  embyItem.Studios = Util.stringToNameObjects(obj.missAv_label || '');
  embyItem.ProviderIds = {};
  embyItem.ProductionLocations = ['Japan'];
  embyItem.GenreItems = Util.stringToNameObjects(obj.missAv_genre || '');
  embyItem.People = Util.stringToActorObjects(obj.missAv_actress || '');
  embyItem.LockData = true;

  try {
    EmbyService.updateItem(obj.Id, embyItem);
  } catch (e) {
    Logger.log('updateItem error: ' + e);
  }

  try {
    const fetchNew = EmbyService.getItemDetails(obj.Id);
    const fresh = fetchNew && fetchNew.data ? fetchNew.data : null;
    if (fresh) {
      const mapNew = mapEmbyToItem(fresh) || {};
      Object.keys(mapNew).forEach(k => (obj[k] = mapNew[k]));
      obj.Processed = '';
      obj.save();
    }
  } catch (e) {
    Logger.log('post-update refresh/save error: ' + e);
  }

  if (obj.missAv_image_cropped) {
    try {
      for (let i = 0; i <= 4; i++) EmbyService.deleteImage(obj.Id, 'Backdrop', i);
      EmbyService.deleteImage(obj.Id, 'Banner');
      EmbyService.deleteImage(obj.Id, 'Primary');
      EmbyService.deleteImage(obj.Id, 'Logo');
    } catch (e) {
      Logger.log('deleteImage error: ' + e);
    }

    let base64W = '', base64 = '';
    try { base64W = Util.convertBase64FromUrlW800(obj.missAv_image_cropped); } catch (e) { Logger.log('base64W error: ' + e); }
    try { base64 = Util.convertBase64FromUrl(obj.missAv_image_cropped); } catch (e) { Logger.log('base64 error: ' + e); }

    try { if (base64W) EmbyService.uploadImage(obj.Id, 'Banner', base64W); } catch (e) { Logger.log('upload Banner error: ' + e); }
    try { if (base64W) EmbyService.uploadImage(obj.Id, 'Backdrop', base64W); } catch (e) { Logger.log('upload Backdrop error: ' + e); }
    try { if (base64) EmbyService.uploadImage(obj.Id, 'Primary', base64); } catch (e) { Logger.log('upload Primary error: ' + e); }
  }
}


function updateEmbyItemWithInternal(obj) {
  const embyRaw = EmbyService.getItemDetails(obj.Id);
  const embyItem = embyRaw && embyRaw.data ? embyRaw.data : {}

  if (!embyItem || !embyItem.Id) return

  embyItem.Name = Util.getNameFromPath(obj.Path || '')
  embyItem.OriginalTitle = ''
  embyItem.SortName = Util.getNameFromPath(obj.Path || '')
  embyItem.ForcedSortName = Util.getNameFromPath(obj.Path || '')
  embyItem.Overview = ''
  embyItem.ProductionYear = obj.ProductionYear || ''
  embyItem.PremiereDate = obj.PremiereDate || ''
  embyItem.PreferredMetadataLanguage = "en"
  embyItem.PreferredMetadataCountryCode = 'JP'
  embyItem.Studios = Util.stringToNameObjects(obj['Studio.Name'] || '')
  embyItem.ProviderIds = {}
  embyItem.ProductionLocations = ['Japan']
  // embyItem.GenreItems = Util.stringToNameObjects(obj.missAv_genre || '')
  embyItem.People = Util.stringToActorObjects(obj['People1.Name'] || '')
  embyItem.LockData = true

  const updatedItem = EmbyService.updateItem(obj.Id, embyItem)
  obj.Processed = '';
  obj.save()
}

function mainPullProcessWrapper() {
  /** get All Parents Folder */
  getParentFolders()
  /** Populate Parent's Child Items*/
  getParentChildFoldersFast()
  /** Populate Child Items into Item Sheet */
  getChildItems()
  /** Pull Item Details from Emby */
  populateItemDetails()
  /** schedule MissAv Trigger */
  createImmediateMissAv()
  /** schedule Update Items Trigger */
  createImmediateUpdateItems()
}