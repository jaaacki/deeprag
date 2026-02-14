const Util = {
  convertBase64FromUrl: function (url) {
    if (typeof url !== 'string' || !url.trim()) return ''

    const res = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      followRedirects: true,
      headers: {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'image/*,*/*;q=0.8'
      }
    })

    const blob = res.getBlob()
    const ct = blob.getContentType()

    if (!ct || !/^image\//i.test(ct)) {
      throw new Error(`Invalid image URL. Got ${ct || 'unknown'} from ${url}`)
    }

    // Return a clean base64 string (no prefix)
    return Utilities.base64Encode(blob.getBytes())
  },
  convertBase64FromUrlW800: function (url) {
    if (typeof url !== 'string' || !url.trim()) return ''

    // Split base and query
    const [base, query] = url.split('?')
    let params = {}

    if (query) {
      query.split('&').forEach(pair => {
        const [k, v] = pair.split('=')
        params[decodeURIComponent(k)] = decodeURIComponent(v || '')
      })
    }

    // Adjust params
    params.w = '800'
    delete params.horizontal

    // Build new URL
    const newUrl = base + '?' + Object.keys(params)
      .map(k => encodeURIComponent(k) + '=' + encodeURIComponent(params[k]))
      .join('&')

    const res = UrlFetchApp.fetch(newUrl, {
      muteHttpExceptions: true,
      followRedirects: true,
      headers: {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'image/*,*/*;q=0.8'
      }
    })

    const blob = res.getBlob()
    const ct = blob.getContentType()
    if (!ct || !/^image\//i.test(ct)) {
      throw new Error(`Fetch failed (${res.getResponseCode()}) - ${res.getContentText().slice(0, 200)}`)
    }

    return Utilities.base64Encode(blob.getBytes())
  },
  arrayToString: function (arr) {
    return Array.isArray(arr)
      ? arr.filter(v => v != null && v !== '').map(v => String(v).trim()).join(', ')
      : ''
  },
  stringToArray: function (str) {
    return typeof str === 'string' && str.trim() !== ''
      ? str.split(',').map(v => v.trim()).filter(v => v !== '')
      : []
  },
  stringToNameObjects: function (str) {
    return typeof str === 'string' && str.trim() !== ''
      ? str.split(',')
        .map(v => v.trim())
        .filter(v => v !== '')
        .map(v => ({ Name: v }))
      : []
  },
  // stringToActorObjects: function (str) {
  //   return typeof str === 'string' && str.trim() !== ''
  //     ? str.split(',')
  //       .map(v => v.trim())
  //       .filter(v => v !== '')
  //       .map(v => ({ Name: v, Type: 'Actor' }))
  //     : []
  // },
  stringToActorObjects: function (str) {
    if (typeof str !== 'string' || str.trim() === '') return []
    const items = []
    let buf = ''
    let depth = 0
    for (const ch of str) {
      if (ch === '(') depth++
      else if (ch === ')' && depth > 0) depth--
      if (ch === ',' && depth === 0) {
        const t = buf.trim()
        if (t) items.push(t)
        buf = ''
      } else {
        buf += ch
      }
    }
    const last = buf.trim()
    if (last) items.push(last)
    return items.map(v => ({ Name: v, Type: 'Actor' }))
  },
  getNameFromPath: function (path) {
    if (typeof path !== 'string') return ''
    return path.replace(/^.*\//, '').replace(/\.[^/.]+$/, '')
  },
  getYearFromDate: function (dateVal) {
    if (dateVal instanceof Date && !isNaN(dateVal)) {
      return String(dateVal.getFullYear())
    }
    if (typeof dateVal === 'string' && dateVal.trim() !== '') {
      return dateVal.trim().slice(0, 4)
    }
    return ''
  },
  dateToString: function (val) {
    let dateObj = null

    if (val instanceof Date && !isNaN(val)) {
      dateObj = val
    } else if (typeof val === 'string' && val.trim() !== '') {
      const parsed = new Date(val)
      if (!isNaN(parsed)) dateObj = parsed
    } else if (typeof val === 'number') {
      const parsed = new Date(val)
      if (!isNaN(parsed)) dateObj = parsed
    }

    if (!dateObj) return ''

    const year = dateObj.getFullYear()
    const month = String(dateObj.getMonth() + 1).padStart(2, '0')
    const day = String(dateObj.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  },
  extractMovieCodeFromPath: function (val) {
    if (typeof val !== 'string' || !val.trim()) return ''
    const m = val.match(/\b([A-Za-z]+-\d+)\b/)
    return m ? m[1] : ''
  },
  extractParentNameFromPath: function (val) {
    if (typeof val !== 'string' || !val.trim()) return '';
    const parts = val.split('/');
    if (parts.length > 4) {
      return parts[4];
    }
    return '';
  },
  createTimeStampId: function (isoString) {
    if (typeof isoString !== 'string' || !isoString.trim()) return '';
    return isoString
      .replace(/^20/, '')   // remove leading '20' from year
      .replace(/[-:TZ]/g, '') // remove -, :, T, Z
      .replace(/\./g, '');    // remove dot if exists
  },
  getParentNameFromParentId: function (parentId) {
    const parent = Me.ParentFolders.where(row => row.Id == Number(parentId) || row.Id == String(parentId)).first()
    if (parent) {
      return parent.Name
    }
    return ''
  },
  getRowNumberFromId: function (itemId) {
    const rows = Me.Items
      .where(row => row.Id === String(itemId) || row.Id === Number(itemId))
      .all();
    return rows.map(r => r.row_);
  },
  deleteRow: function (sheetName, rows) {
    if (!sheetName) throw new Error('Invalid sheet name');
    const sheet = SheetById.getSheetByName(sheetName);
    if (!sheet) throw new Error(`Sheet "${sheetName}" not found`);

    const list = Array.isArray(rows) ? rows : [rows];
    const max = sheet.getMaxRows();
    const vals = [...new Set(list.map(n => Math.floor(Number(n))))].filter(n => Number.isFinite(n) && n >= 1 && n <= max);
    if (!vals.length) return 0;

    vals.sort((a, b) => a - b);
    const ranges = [];
    let start = vals[0], prev = vals[0], count = 1;
    for (let i = 1; i < vals.length; i++) {
      if (vals[i] === prev + 1) { count++; prev = vals[i]; }
      else { ranges.push([start, count]); start = prev = vals[i]; count = 1; }
    }
    ranges.push([start, count]);
    ranges.sort((a, b) => b[0] - a[0]).forEach(([s, c]) => sheet.deleteRows(s, c));
    return vals.length;
  },
  hasJpv: function (path) {
    return /\/jpv\//i.test(path);
  },
  log: function (...args) {
    if (Config.debug && Config.debug.level === 1) {
      Logger.log(...args)
    }
  },
  getCurrentTimeStamp: function () {
    // Return a Date object representing current time in GMT+8 regardless of script execution timezone
    var now = new Date();
    var currentOffsetMin = now.getTimezoneOffset(); // minutes difference from UTC (e.g., UTC+8 => -480)
    var targetOffsetMin = -8 * 60; // GMT+8
    var diffMin = targetOffsetMin - currentOffsetMin; // minutes to add
    return new Date(now.getTime() + diffMin * 60000);
  },
  checkMissAvToProcess: function () {
    const toProcessRows = Me.Items.where(row => row.Id !== '' && row.MovieCode !== '' && (row.missAv_status === '' || row.missAv_status === 'error')).all();
    if (toProcessRows && toProcessRows.length > 0) {
      return true
    } else {
      return false
    }
  },
  checkIfTriggerExist: function (fnName, type) {
    const fnExistRows = Me.Triggers.where(row => {
      if (row.uniqueId === '' || row.handlerFunction !== fnName || row.status !== true) {
        return false
      }
      if (type && type !== '') {
        return row.type === type
      }
      return true
    }).all()

    return fnExistRows && fnExistRows.length > 0
  },
  checkUpdateToItem: function () {
    const toUpdateRows = Me.Items.where(row => row.Id !== '' && row.Processed === true && row.missAv_status === 'completed').all()
    if (toUpdateRows && toUpdateRows.length > 0) {
      return true
    } else {
      return false
    }
  },
  checkParentFoldersHealth: function () {
    const sh = SpreadsheetApp.getActive().getSheetByName('parentFolders');
    if (!sh) throw new Error('Sheet not found: parentFolders');
    const lastRow = sh.getLastRow();
    if (lastRow < 2) return true;
    const vals = sh.getRange(2, 4, lastRow - 1, 1).getDisplayValues();
    return !vals.some(r => String(r[0]).trim().toUpperCase() === 'ERROR');
  },
  pickItemsFromObject: function (array, key) {
    // Safety check: return empty array if input is not an array
    if (!Array.isArray(array)) return [];

    return array.map(function (item) {
      // Return undefined if the item itself is null/undefined
      return item ? item[key] : undefined;
    });
  },
  generateId: function () {
    const now = new Date();

    // 1. Generate YYMMDD
    const yy = now.getFullYear().toString().slice(-2);
    const mm = (now.getMonth() + 1).toString().padStart(2, '0'); // Months are 0-indexed
    const dd = now.getDate().toString().padStart(2, '0');
    const datePrefix = yy + mm + dd;

    // 2. Generate XXXX (4 random chars)
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    let randomSuffix = '';
    for (let i = 0; i < 4; i++) {
      randomSuffix += chars.charAt(Math.floor(Math.random() * chars.length));
    }

    return datePrefix + randomSuffix;
  }
}