const Trigger = {
  _parseHourMinute: function (str) {
    var m = String(str).trim().match(/^([01]?\d|2[0-3])(?::([0-5]\d))?$/)
    if (!m) throw new Error('Invalid time format: ' + str)
    return { hour: Number(m[1]), minute: m[2] != null ? Number(m[2]) : null }
  },
  _parseAtTime: function (ctx, val, required) {
    if (val == null || val === '') {
      if (required) throw new Error('Missing at time value')
      return
    }
    if (val instanceof Date) {
      ctx.hour = val.getHours(); ctx.minute = val.getMinutes(); return
    }
    if (typeof val === 'number') {
      if (val < 0 || val > 23) throw new Error('Hour out of range 0-23')
      ctx.hour = val; return
    }
    var hm = this._parseHourMinute(val)
    ctx.hour = hm.hour; ctx.minute = hm.minute
  },
  _mapWeekday: function (dayStr) {
    var key = String(dayStr).trim().toUpperCase()
    var map = {
      MONDAY: ScriptApp.WeekDay.MONDAY,
      TUESDAY: ScriptApp.WeekDay.TUESDAY,
      WEDNESDAY: ScriptApp.WeekDay.WEDNESDAY,
      THURSDAY: ScriptApp.WeekDay.THURSDAY,
      FRIDAY: ScriptApp.WeekDay.FRIDAY,
      SATURDAY: ScriptApp.WeekDay.SATURDAY,
      SUNDAY: ScriptApp.WeekDay.SUNDAY
    }
    var v = map[key]
    if (!v) throw new Error('Invalid weekday: ' + dayStr)
    return v
  },
  _buildTriggerMeta: function (trigger, cfg) {
    return {
      eventType: String(trigger.getEventType()),
      triggerSource: String(trigger.getTriggerSource()),
      triggerSourceId: (typeof trigger.getTriggerSourceId === 'function') ? trigger.getTriggerSourceId() : null,
      handlerFunction: trigger.getHandlerFunction(),
      uniqueId: trigger.getUniqueId(),
      fnName: cfg.fnName || cfg.functionName || cfg.handlerFunction || null,
      type: cfg.type,
  // Use unified key everyOrDelay; retain legacy 'every' for backward compatibility
  everyOrDelay: (cfg.everyOrDelay != null) ? cfg.everyOrDelay : (cfg.every != null ? cfg.every : (cfg.delay != null ? cfg.delay : (cfg.delayMs != null ? cfg.delayMs : (cfg.after != null ? cfg.after : null)))),
  every: cfg.every == null ? null : cfg.every, // legacy field (may be removed later)
      at: cfg.at instanceof Date ? cfg.at.toISOString() : (typeof cfg.at === 'string' ? cfg.at : null),
      timeStamp: Util && Util.getCurrentTimeStamp ? Util.getCurrentTimeStamp() : new Date(),
      status: true
    }
  }
}