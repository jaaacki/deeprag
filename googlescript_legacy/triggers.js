function createImmediateMissAv() {
  createTrigger({ fnName: 'getMissAvData', type: 'immediate', everyOrDelay: 1000 })
}
function createImmediateUpdateItems() {
  createTrigger({ fnName: 'updateEmbyItems', type: 'immediate', everyOrDelay: 120000 })
}
function createGetWebEventsAndPopulate() {
  createTrigger({ fnName: 'getWebEventsAndPopulate', type: 'immediate', everyOrDelay: 3000 })
}

function getWebEventsAndPopulate(Id) {
  Logger.log(Id)
  const webEvents = Me.WebEvents.where(row => (String(row.Id) === String(Id) || Number(row.Id) === Number(Id)) && row.eventType === 'library.new').first()
  Logger.log(webEvents)
  const items = Me.Items.where(row => row.Id === Id).all()
  const base = ScriptBaseUrl;

  if (items && items.length <= 0) {
    Me.Items.createOrUpdate(
      {
        Url: 'https://emby.familyhub.id/web/index.html#!/item?serverId=c8c799e46ba44eaea1add913697ca2a8&id=' + webEvents.Id,
        Id: webEvents.Id,
        ParentId: webEvents.ParentId,
        ParentName: Util.extractParentNameFromPath(webEvents.Path),
        MovieCode: Util.extractMovieCodeFromPath(webEvents.Path),
        Name: Util.getNameFromPath(webEvents.Path),
        Path: webEvents.Path
      }
    )
  } else {
    return
  }
  UrlFetchApp.fetch(base + '?run=createImmediateMissAv', { followRedirects: false });
  UrlFetchApp.fetch(base + '?run=createImmediateUpdateItems', { followRedirects: false });
}

function activateOrDeleteTriggers() {
  const toGetMissAv = Util.checkMissAvToProcess()
  const toUpdateItem = Util.checkUpdateToItem()
  const getMissAvFnName = 'getMissAvData'
  const updateItemFnName = 'updateEmbyItems'
  const getWebEventsAndPopulateFnName = 'getWebEventsAndPopulate'
  const fnGetMissAvExist = Util.checkIfTriggerExist(getMissAvFnName, 'minute')
  const fnUpdateItemsExist = Util.checkIfTriggerExist(updateItemFnName, 'minute')
  Logger.log('Row to getMissAv? ' + toGetMissAv)
  Logger.log('Is getMissAvData activated? ' + fnGetMissAvExist);
  Logger.log('Row to update? ' + toUpdateItem)
  Logger.log('Is updateItems activated? ' + fnUpdateItemsExist);

  /** remove getMissAv Triggers */
  const fnGetMissAvExistImmediate = Util.checkIfTriggerExist(getMissAvFnName)
  Logger.log('Have Immediate MissAv ' + fnGetMissAvExistImmediate)
  const fnUpdateItemsExistImmediate = Util.checkIfTriggerExist(updateItemFnName)
  Logger.log('Have Update MissAv ' + fnUpdateItemsExistImmediate)
  const fnGetWebEventsAndPopulateImmediate = Util.checkIfTriggerExist(getWebEventsAndPopulateFnName)
  Logger.log('Have Grab MissAv ' + fnGetWebEventsAndPopulateImmediate)
  if (fnGetMissAvExistImmediate === true) {
    // Only consider immediate triggers for removal as requested
    const getMissAvTriggers = Me.Triggers.where(row => row.handlerFunction === getMissAvFnName && row.status === true && row.type === 'immediate').all()
    Logger.log(getMissAvTriggers)
    for (var i = 0; i < getMissAvTriggers.length; i++) {
      var t = getMissAvTriggers[i]
      try {
        var ts = t.timeStamp
        var tsDate = (ts instanceof Date) ? ts : new Date(ts)
        var delay = Number(t.everyOrDelay || t.delay || t.delayMs || t.after || 0)
        // Regardless of whether the trigger already fired, delete it to fully clean up
        if (isNaN(tsDate.getTime()) || !Number.isFinite(delay) || delay < 0) {
          Logger.log('Deleting malformed immediate trigger ' + t.uniqueId)
        }
        deleteTrigger(t.uniqueId)
      } catch (e) {
        Logger.log('Error evaluating immediate getMissAv trigger removal: ' + e)
        deleteTrigger(t.uniqueId)
      }
    }
  }
  /** remove updateItems Triggers */
  if (fnUpdateItemsExistImmediate === true) {
    const updateItemTriggers = Me.Triggers.where(row => row.handlerFunction === updateItemFnName && row.status === true).all()
    Logger.log(updateItemTriggers)
    for (var i = 0; i < updateItemTriggers.length; i++) {
      var ut = updateItemTriggers[i]
      if (ut.type === 'minute') {
        deleteTrigger(ut.uniqueId)
        continue
      }
      if (ut.type === 'immediate') {
        try {
          var uts = ut.timeStamp
          var utsDate = (uts instanceof Date) ? uts : new Date(uts)
          var udelay = Number(ut.everyOrDelay || ut.delay || ut.delayMs || ut.after || 0)
          // Always delete immediate triggers when update processing disabled
          if (isNaN(utsDate.getTime()) || !Number.isFinite(udelay) || udelay < 0) {
            Logger.log('Deleting malformed immediate updateItem trigger ' + ut.uniqueId)
          }
          deleteTrigger(ut.uniqueId)
        } catch (e2) {
          Logger.log('Error evaluating immediate updateItem trigger removal: ' + e2)
          deleteTrigger(ut.uniqueId)
        }
      }
    }
  }
  /** remove getWebEventsAndPopulate Triggers */
  if (fnGetWebEventsAndPopulateImmediate === true) {
    const populateItemTriggers = Me.Triggers.where(row => row.handlerFunction === getWebEventsAndPopulateFnName && row.status === true).all()
    Logger.log(populateItemTriggers)
    for (var i = 0; i < populateItemTriggers.length; i++) {
      var ut = populateItemTriggers[i]
      if (ut.type === 'minute') {
        deleteTrigger(ut.uniqueId)
        continue
      }
      if (ut.type === 'immediate') {
        try {
          var uts = ut.timeStamp
          var utsDate = (uts instanceof Date) ? uts : new Date(uts)
          var udelay = Number(ut.everyOrDelay || ut.delay || ut.delayMs || ut.after || 0)
          // Always delete immediate triggers when update processing disabled
          if (isNaN(utsDate.getTime()) || !Number.isFinite(udelay) || udelay < 0) {
            Logger.log('Deleting malformed immediate updateItem trigger ' + ut.uniqueId)
          }
          deleteTrigger(ut.uniqueId)
        } catch (e2) {
          Logger.log('Error evaluating immediate updateItem trigger removal: ' + e2)
          deleteTrigger(ut.uniqueId)
        }
      }
    }
  }

  if (toGetMissAv === true && fnGetMissAvExist === false) {
    /** activate getMissAvData */
    const result = createTrigger({ fnName: getMissAvFnName, type: 'minute', everyOrDelay: 30 })
    /** activate updateItem */
    if (fnUpdateItemsExist === false) {
      const activateUpdateResult = createTrigger({ fnName: updateItemFnName, type: 'minute', everyOrDelay: 30 })
    }
  }
  /** add updateItems Triggers */
  if (toUpdateItem === true && fnUpdateItemsExist === false) {
    const activateUpdateResult = createTrigger({ fnName: updateItemFnName, type: 'minute', everyOrDelay: 30 })
  }
}

/**
 *  createTrigger({ fnName:'jobMin', type:'minute', everyOrDelay:5 })
 *  createTrigger({ fnName:'jobHr', type:'hour', everyOrDelay:4 })
 *  createTrigger({ fnName:'jobDay', type:'day', at:'02:30' })
 *  createTrigger({ fnName:'jobWeek', type:'week', everyOrDelay:'monday', at:9 })
 *  createTrigger({ fnName:'jobMonth', type:'month', everyOrDelay:15, at:'10:05' })
 *  createTrigger({ fnName:'oneOff', type:'specific', at:new Date() })
 *  createTrigger({ fnName:'runSoon', type:'immediate' }) // runs once ~1s from now (default 1000ms)
 *  createTrigger({ fnName:'runSoon', type:'immediate', everyOrDelay:5000 }) // runs once ~5s from now
 *  // Backward compat: accepts prior keys every (for non-immediate) or delay/delayMs/after (immediate)
 */

function createTrigger(cfg) {
  if (!cfg || typeof cfg !== 'object') throw new Error('Config object required')
  if (!cfg.fnName || typeof cfg.fnName !== 'string') throw new Error('fnName (string) is required')
  var fn = cfg.fnName
  var type = (cfg.type || '').toLowerCase()
  var tb = ScriptApp.newTrigger(fn).timeBased()

  // Ensure Trigger service helpers exist
  if (!(Trigger && typeof Trigger._parseAtTime === 'function' && typeof Trigger._buildTriggerMeta === 'function')) {
    throw new Error('Trigger service not loaded or missing required helpers')
  }

  var parsed = { hour: null, minute: null, weekday: null, monthDay: null }

  // Backward compatibility shim: allow old 'every' for legacy callers
  if (cfg.everyOrDelay == null && cfg.every != null) cfg.everyOrDelay = cfg.every

  switch (type) {
    case 'minute': {
      var allowedM = [5, 10, 15, 30]
      if (allowedM.indexOf(cfg.everyOrDelay) === -1) throw new Error('Minute everyOrDelay must be one of ' + allowedM.join(','))
      tb = tb.everyMinutes(cfg.everyOrDelay)
      break
    }
    case 'hour': {
      var allowedH = [2, 4, 6, 8, 12]
      if (allowedH.indexOf(cfg.everyOrDelay) === -1) throw new Error('Hour everyOrDelay must be one of ' + allowedH.join(','))
      tb = tb.everyHours(cfg.everyOrDelay)
      break
    }
    case 'day': {
      Trigger._parseAtTime(parsed, cfg.at, true)
      tb = tb.atHour(parsed.hour).everyDays(1)
      if (parsed.minute != null) tb = tb.nearMinute(parsed.minute)
      break
    }
    case 'week': {
      if (!cfg.everyOrDelay) throw new Error('Week requires weekday name in everyOrDelay')
      parsed.weekday = String(cfg.everyOrDelay).toLowerCase().trim()
      Trigger._parseAtTime(parsed, cfg.at, false)
      if (parsed.hour == null) parsed.hour = 0
      var weekday = Trigger._mapWeekday(parsed.weekday)
      tb = tb.atHour(parsed.hour).onWeekDay(weekday).everyWeeks(1)
      if (parsed.minute != null) tb = tb.nearMinute(parsed.minute)
      break
    }
    case 'month': {
      if (cfg.everyOrDelay == null) throw new Error('Month requires day-of-month in everyOrDelay')
      var md = Number(cfg.everyOrDelay)
      if (!Number.isFinite(md) || md < 1 || md > 31) throw new Error('Month day out of range 1-31')
      parsed.monthDay = md
      Trigger._parseAtTime(parsed, cfg.at, false)
      if (parsed.hour == null) parsed.hour = 0
      tb = tb.atHour(parsed.hour).onMonthDay(parsed.monthDay).everyMonths(1)
      if (parsed.minute != null) tb = tb.nearMinute(parsed.minute)
      break
    }
    case 'immediate': {
      // One-off trigger that fires after a short delay (default 1000ms)
      var delay = null
      if (cfg.everyOrDelay != null) delay = Number(cfg.everyOrDelay)
      else if (cfg.delay != null) delay = Number(cfg.delay)
      else if (cfg.delayMs != null) delay = Number(cfg.delayMs)
      else if (cfg.after != null) delay = Number(cfg.after) // legacy alias
      else delay = 1000
      if (!Number.isFinite(delay) || delay < 1) throw new Error('immediate everyOrDelay/delay must be a positive number (ms)')
      tb = tb.after(delay)
      break
    }
    case 'specific': {
      var date
      if (cfg.at instanceof Date) date = cfg.at
      else if (cfg.date) {
        var d = cfg.date
        date = new Date(d.year, (d.month - 1), d.day, d.hour || 0, d.minute || 0, 0, 0)
      }
      else if (typeof cfg.at === 'string') {
        var parsedDate = new Date(cfg.at)
        if (!isNaN(parsedDate)) date = parsedDate
      }
      if (!(date instanceof Date) || isNaN(date.getTime())) throw new Error('Specific trigger requires valid Date in at (Date or ISO) or date components')
      tb = tb.at(date)
      break
    }
    default:
      throw new Error('Unsupported type: ' + type)
  }

  var trigger = tb.create()
  var meta = Trigger._buildTriggerMeta(trigger, cfg)
  if (meta) {
    Me.Triggers.createOrUpdate(
      meta
    )
  }
  return meta
}

function deleteTrigger(uniqueId) {
  if (!uniqueId || typeof uniqueId !== 'string') throw new Error('uniqueId (string) required')
  var triggers = ScriptApp.getProjectTriggers()
  for (var i = 0; i < triggers.length; i++) {
    var t = triggers[i]
    if (t.getUniqueId && t.getUniqueId() === uniqueId) {
      var meta = {
        uniqueId: t.getUniqueId(),
        handlerFunction: t.getHandlerFunction ? t.getHandlerFunction() : null,
        eventType: t.getEventType ? String(t.getEventType()) : null,
        triggerSource: t.getTriggerSource ? String(t.getTriggerSource()) : null,
        triggerSourceId: (t.getTriggerSourceId && typeof t.getTriggerSourceId === 'function') ? t.getTriggerSourceId() : null,
        deleted: false
      }
      ScriptApp.deleteTrigger(t)
      meta.deleted = true
      // add fnName alias for consistency with createTrigger metadata
      meta.fnName = meta.handlerFunction
      /** save meta result on sheet */
      const triggerRow = Me.Triggers.where(row => row.uniqueId === meta.uniqueId).first()
      triggerRow.status = false
      triggerRow.save()
      return meta
    }
  }
  return null
}

// function tryCreateTrigger() {
//   const fnName = 'onOpen'
//   // const result = createTrigger({ fnName: fnName, type: 'minute', every: 5 });
//   const result = createTrigger({ fnName: fnName, type: 'immediate'});
//   Logger.log(result)
//   if (result) {
//     Me.Triggers.createOrUpdate(
//       result
//     )
//   }
// }
// function tryDeleteTrigger() {
//   const id = '-2474656929355713305'
//   const result = deleteTrigger(id);
//   Logger.log(result);
// }