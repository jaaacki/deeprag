/**
 * @fileoverview A service for interacting with the Emby API.
 * This module encapsulates all Emby-related API calls.
 */
const EmbyService = {
  /** Fetches items from the Emby server. */
  getItems: function (params) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const url = `${baseUrl}${endpoints.items}?${params}`;
    Logger.log(url)
    const response = HttpService.get(url, headers);
    Logger.log(response)
    return response;
  },
  getItemsAllByParentIds: function (parentIds, extra, batchSize) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const q = extra || 'Recursive=true&SortBy=Id&IsFolder=false';
    const urls = parentIds.map(id => `${baseUrl}${endpoints.items}?ParentId=${encodeURIComponent(id)}&${q}`);
    const res = HttpService.getAll(urls, headers, batchSize);
    return res.map((r, i) => ({ parentId: parentIds[i], ...r }));
  },
  /** Fetches all item IDs from Emby (with pagination support). */
  getAllItemIds: function () {
    Logger.log('EmbyService.getAllItemIds: Fetching all item IDs from Emby');
    const params = 'Recursive=true&IncludeItemTypes=Video&Fields=BasicSyncInfo';
    const response = this.getItems(params);

    if (!response.success) {
      Logger.log(`EmbyService.getAllItemIds: Failed to fetch items: ${response.error}`);
      return [];
    }

    const items = response.data.Items || [];
    const itemIds = items.map(item => item.Id);
    Logger.log(`EmbyService.getAllItemIds: Found ${itemIds.length} item IDs`);
    return itemIds;
  },
  /** Fetches details for a specific item. */
  getItemDetails: function (itemId) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const url = `${baseUrl}${endpoints.itemDetails}${itemId}`;
    return HttpService.get(url, headers);
  },
  getItemDetailsAll: function (itemIds, batchSize) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const urls = itemIds.map(id => `${baseUrl}${endpoints.itemDetails}${encodeURIComponent(id)}`);
    const res = HttpService.getAll(urls, headers, batchSize);
    return res.map((r, i) => ({ itemId: itemIds[i], ...r }));
  },
  updateItem: function (itemId, data) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const url = `${baseUrl}${endpoints.updateItem}${itemId}`;
    return HttpService.post(url, data, headers);
  },
  updateItemAll: function (pairs, batchSize) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const requests = pairs.map(p => ({
      url: `${baseUrl}${endpoints.updateItem}${encodeURIComponent(p.itemId)}`,
      payload: p.payload
    }));
    return HttpService.postAll(requests, headers, batchSize);
  },
  deleteImage: function (itemId, type, index = 0) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const url = `${baseUrl}${endpoints.items}/${itemId}/Images/${type}/${index}`;
    return HttpService.delete(url, headers);
  },
  deleteImageAll: function (reqs, batchSize) {
    const { emby, secrets } = Config;
    const { baseUrl, endpoints } = emby;
    const headers = { 'X-Emby-Token': secrets.embyToken, 'Content-Type': 'application/json' };
    const urls = reqs.map(r => `${baseUrl}${endpoints.items}/${encodeURIComponent(r.itemId)}/Images/${encodeURIComponent(r.type)}/${r.index || 0}`);
    return HttpService.deleteAll(urls, headers, batchSize);
  },
  uploadImage: function (itemId, type, base64Image, mime) {
    const { emby, secrets } = Config;
    const url = `${emby.baseUrl.replace(/\/+$/, '')}/Items/${itemId}/Images/${encodeURIComponent(type)}?api_key=${secrets.embyToken}`;
    const clean = String(base64Image).replace(/^data:image\/[^;]+;base64,/, '').replace(/\s/g, '');
    const res = UrlFetchApp.fetch(url, { method: 'post', contentType: mime || 'image/jpeg', payload: clean, muteHttpExceptions: true });
    return { success: res.getResponseCode() >= 200 && res.getResponseCode() < 300, statusCode: res.getResponseCode(), data: res.getContentText() ? JSON.parse(res.getContentText()) : null };
  },
  uploadImageAll: function (reqs, batchSize) {
    const { emby, secrets } = Config;
    const base = emby.baseUrl.replace(/\/+$/, '');
    const out = [];
    const bs = Math.max(1, batchSize || 20);

    for (let i = 0; i < reqs.length; i += bs) {
      const chunk = reqs.slice(i, i + bs).map(r => {
        const url = `${base}/Items/${r.itemId}/Images/${encodeURIComponent(r.type)}?api_key=${secrets.embyToken}`;
        const clean = String(r.base64).replace(/^data:image\/[^;]+;base64,/, '').replace(/\s/g, '');
        return {
          url,
          method: 'post',
          contentType: r.mime || 'image/jpeg',
          payload: clean,
          muteHttpExceptions: true
        };
      });

      try {
        const resArr = UrlFetchApp.fetchAll(chunk);
        resArr.forEach(res => {
          const code = res.getResponseCode();
          const txt = res.getContentText();
          let data = null;
          if (txt) { try { data = JSON.parse(txt); } catch (_) { } }
          out.push({ success: code >= 200 && code < 300, statusCode: code, data });
        });
      } catch (e) {
        for (let j = 0; j < chunk.length; j++) {
          out.push({ success: false, statusCode: null, error: String(e) });
        }
      }
    }
    return out;
  },
  scanLibrary: function (itemId) {
    const { emby, secrets } = Config;
    const { baseUrl } = emby;
    const headers = {
      'X-Emby-Token': secrets.embyToken,
      'Content-Type': 'application/json'
    };

    const url = `${baseUrl}/emby/Items/${itemId}/Refresh?Recursive=true`;
    return HttpService.post(url, {}, headers);
  },
  generateVideoPreview: function () {
    const { emby, secrets } = Config;
    const { baseUrl } = emby;
    const headers = {
      'X-Emby-Token': secrets.embyToken,
      'Content-Type': 'application/json'
    };
    const url = `${baseUrl}/emby/ScheduledTasks/Running/d15b3f9fc313609ffe7e49bd1c74f753`;
    const response = HttpService.post(url, {}, headers);
    return response
  }
};
