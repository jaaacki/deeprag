const HttpService = (function() {
  function _parse(response) {
    const statusCode = response.getResponseCode();
    const text = response.getContentText() || '';
    if (statusCode >= 200 && statusCode < 300) {
      return { success: true, data: text ? JSON.parse(text) : null, statusCode };
    }
    return { success: false, error: `HTTP Error: ${statusCode}`, statusCode, message: text };
  }

  function _makeRequest(url, options) {
    try {
      const res = UrlFetchApp.fetch(url, options);
      return _parse(res);
    } catch (e) {
      return { success: false, error: `Request failed: ${e.message}`, statusCode: null };
    }
  }

  function _fetchAll(requests, batchSize) {
    const out = [];
    const bs = Math.max(1, batchSize || 50);
    for (let i = 0; i < requests.length; i += bs) {
      const chunk = requests.slice(i, i + bs).map(r => {
        const o = Object.assign({}, r.options || {});
        o.muteHttpExceptions = true;
        return Object.assign({ url: r.url }, o);
      });
      try {
        const resArr = UrlFetchApp.fetchAll(chunk);
        for (const res of resArr) out.push(_parse(res));
      } catch (e) {
        for (let j = 0; j < chunk.length; j++) out.push({ success: false, error: `Request failed: ${e.message}`, statusCode: null });
      }
    }
    return out;
  }

  return {
    get: function(url, headers = {}) {
      const options = { method: 'get', headers, muteHttpExceptions: true };
      return _makeRequest(url, options);
    },
    post: function(url, payload, headers = {}) {
      const options = { method: 'post', contentType: 'application/json', headers, payload: JSON.stringify(payload), muteHttpExceptions: true };
      return _makeRequest(url, options);
    },
    delete: function(url, headers = {}) {
      const options = { method: 'delete', headers, muteHttpExceptions: true };
      return _makeRequest(url, options);
    },
    fetchAll: function(requests, batchSize) {
      return _fetchAll(requests, batchSize);
    },
    getAll: function(urls, headers = {}, batchSize) {
      const reqs = urls.map(u => ({ url: u, options: { method: 'get', headers } }));
      return _fetchAll(reqs, batchSize);
    },
    postAll: function(pairs, headers = {}, batchSize) {
      const reqs = pairs.map(p => ({ url: p.url, options: { method: 'post', contentType: 'application/json', headers, payload: JSON.stringify(p.payload) } }));
      return _fetchAll(reqs, batchSize);
    },
    deleteAll: function(urls, headers = {}, batchSize) {
      const reqs = urls.map(u => ({ url: u, options: { method: 'delete', headers } }));
      return _fetchAll(reqs, batchSize);
    }
  };
})();
