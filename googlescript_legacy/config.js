const Config = {
  emby: {
    baseUrl: "https://emby.familyhub.id",
    endpoints: {
      items: "/Items",
      itemDetails: "/Users/b3c8122bfc00466fa4e171f2bf388fe1/Items/",
      updateItem: "/Items/",
    },
  },
  missAv: {
    baseUrl: "https://missav.ws",
    searchPage: "/en/search",
  },
  secrets: {
    embyToken:
      PropertiesService.getScriptProperties().getProperty("X-Emby-Token"),
  },
  wordpress: {
    baseUrl: "https://wp.familyhub.id",
    endpoints: {
      missavsearch: "/wp-json/emby/v1/missavsearch/",
      missavdetails: "/wp-json/emby/v1/missavdetails/",
      missavscout: "/wp-json/emby/v1/missavscout",
      refreshToken: "/wp-json/api-bearer-auth/v1/tokens/refresh",
    },
    wp_refreshToken: PropertiesService.getScriptProperties().getProperty("wp_refreshToken"),
    wp_token: PropertiesService.getScriptProperties().getProperty("wp_token"),
  },
  debug: {
    level: 0
  }
};

const SheetById = SpreadsheetApp.openById("12N4UiSQeltvt_181hgiYS8sFUn7dtEA68J59NnHMUcc");
const ScriptBaseUrl = 'https://script.google.com/macros/s/AKfycbyqi_T-iJUgooUEHvzzuvAFipPir0CN7ULUZPZUFNH2lmcN8I0liAl2F0uPQQYH6ZdJ/exec'

/** Tamotsu */
class Me {
  static get ParentFolders() {
    return this._getTamotsuTable('parentFolders', 'Id', 0);
  }
  static get Items() {
    return this._getTamotsuTable('items', 'Id', 0);
  }
  static get ActressAlias() {
    return this._getTamotsuTable('actressAlias', 'name', 0);
  }
  static get WebEvents() {
    return this._getTamotsuTable('webEvents', 'eventId', 0);
  }
  static get Triggers() {
    return this._getTamotsuTable('triggers', 'uniqueId', 0);
  }
  static get FetchMissAvRemote() {
    return this._getTamotsuTable('fetchMissAvRemote', 'detailsUrl', 0);
  }
  static get ScoutList() {
    return this._getTamotsuTable('scoutLists', 'id', 0);
  }

  static _getTamotsuTable(sheetName, idColumn, rowShift) {
    Tamotsu.initialize(SheetById);
    return Tamotsu.Table.define({
      sheetName: sheetName,
      idColumn: idColumn,
      rowShift: rowShift
    });
  }
}
