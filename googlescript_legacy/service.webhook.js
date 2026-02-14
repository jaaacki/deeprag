const WebHook = {
  saveEvent: function (obj) {
    obj.Item.eventDate = obj.Date
    obj.Item.eventType = obj.Event
    Me.WebEvents.createOrUpdate(
      obj.Item
    )
  },
  saveItem: function (itemObj) {
    itemObj.Url = 'https://emby.familyhub.id/web/index.html#!/item?serverId=c8c799e46ba44eaea1add913697ca2a8&id=' + itemObj.Id
    // itemObj.ParentName = Util.getParentNameFromParentId(itemObj.ParentId)
    itemObj.MovieCode = Util.extractMovieCodeFromPath(itemObj.Path)
    itemObj.ParentName = Util.extractParentNameFromPath(itemObj.Path)
    Me.Items.createOrUpdate(
      itemObj
    )
  },
}