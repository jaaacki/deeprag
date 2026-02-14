// function entryPoint(e) {
//   /**
//    * forwarded from https://script.google.com/u/1/home/projects/1M9XJYmCUBE0ggLK5jzUcFA8uSfGllpioOjHioinpygu-RQTRE5czl5XE/edit
//    */

//   try {
//     const raw = e && e.postData && typeof e.postData.contents === 'string' ? e.postData.contents : ''
//     if (!raw) return ContentService.createTextOutput(JSON.stringify({ ok: false, error: 'Empty body' })).setMimeType(ContentService.MimeType.JSON)
//     const payload = JSON.parse(raw)
//     let trigger = ''
//     if (!payload || !payload.Date || !payload.Item) return ContentService.createTextOutput(JSON.stringify({ ok: false, error: 'Invalid payload' })).setMimeType(ContentService.MimeType.JSON)

//     const eventId = Util.createTimeStampId(payload.Date);
//     payload.Item.eventId = eventId;
//     WebHook.saveEvent(payload)

//     const isJpv = Util.hasJpv(payload.Item.Path)

//     if (payload.Event === 'library.new' && isJpv) {
//       WebHook.saveItem(payload.Item)
//       /** start immediate triggers */
//       trigger = true
//       UrlFetchApp.fetch(ScriptBaseUrl + '?run=createImmediateMissAv');
//       UrlFetchApp.fetch(ScriptBaseUrl + '?run=createImmediateUpdateItems');
//     }

//     const rowNumber = Util.getRowNumberFromId(payload.Item.Id)

//     if (payload.Event === 'library.deleted') {

//       if (rowNumber) {
//         Util.deleteRow('items', rowNumber)
//       }
//     }

//     return ContentService.createTextOutput(JSON.stringify({ ok: true, eventId, rowNumber, trigger })).setMimeType(ContentService.MimeType.JSON)
//   } catch (err) {
//     return ContentService.createTextOutput(JSON.stringify({ ok: false, error: String(err) })).setMimeType(ContentService.MimeType.JSON)
//   }
// }

function entryPoint(e) {
  const json = (obj) =>
    ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);

  try {
    const raw = e && e.postData && typeof e.postData.contents === 'string' ? e.postData.contents : '';
    if (!raw) return json({ ok: false, error: 'Empty body' });

    const payload = JSON.parse(raw);
    if (!payload || !payload.Date || !payload.Item) return json({ ok: false, error: 'Invalid payload' });

    const { Event, Item } = payload;
    const eventId = Util.createTimeStampId(payload.Date);
    Item.eventId = eventId;

    WebHook.saveEvent(payload);

    let trigger = false;

    if (Event === 'library.new') {
      // Only compute when needed
      const isJpv = Util.hasJpv(Item.Path);
      const Id = Item.Id
      const url = ScriptBaseUrl + '?run=createGetWebEventsAndPopulate&Id=' + Id;
      if (isJpv) {
        UrlFetchApp.fetch(url, { followRedirects: false });;
        trigger = true;
      }
      return json({ ok: true, eventId, rowNumber: '', trigger, url });
    }

    if (Event === 'library.deleted') {
      // Only compute when needed
      const rowNumber = Util.getRowNumberFromId(Item.Id);
      if (rowNumber) {
        Util.deleteRow('items', rowNumber);
      }
      return json({ ok: true, eventId, rowNumber, trigger });
    }

    // Other events: nothing extra to do (same as before)
    return json({ ok: true, eventId, rowNumber: '', trigger });
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err && err.message ? err.message : err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/*** expose functions as endpoint */
function doGet(e) {
  if (e.parameter.run === "getMissAvData") {
    getMissAvData();
  } else if (e.parameter.run === "updateEmbyItems") {
    updateEmbyItems();
  } else if (e.parameter.run === "createImmediateMissAv") {
    createImmediateMissAv();
  } else if (e.parameter.run === "createImmediateUpdateItems") {
    createImmediateUpdateItems();
  } else if (e.parameter.run === "createGetWebEventsAndPopulate") {
    var Id = e.parameter.Id;  // <-- grab the id from URL
    Logger.log(Id)
    createGetWebEventsAndPopulate(Id);
  }
}

// function testWebEvent() {
//   // `2508140837123299004 2508140849299582251 2508140849306638922` 
//   const eventId = '2508191640446876529'
//   const event = Me.WebEvents.where(row => row.eventId == eventId).first()
//   const path = event.Path
//   Logger.log(event)
//   Logger.log(path)

//   const isJpv = Util.hasJpv(path)

//   if (event.eventType === 'library.new' && isJpv) {
//     let itemObj = {};
//     itemObj.Id = event.Id
//     itemObj.Url = 'https://emby.familyhub.id/web/index.html#!/item?serverId=c8c799e46ba44eaea1add913697ca2a8&id=' + eventId
//     itemObj.ParentId = event.ParentId
//     itemObj.ParentName = Util.extractParentNameFromPath(event.Path)
//     itemObj.MovieCode = Util.extractMovieCodeFromPath(event.Path)
//     Me.Items.createOrUpdate(
//       itemObj
//     )
//   }
// }