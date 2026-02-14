/**
 * @fileoverview A service for interacting with the WordPress API.
 * This module encapsulates all WordPress-related API calls.
 */
const WordPressService = {
  /** Searches for content using MissAV search endpoint. */
  missavSearch: function (moviecode) {
    const { wordpress } = Config;
    const { baseUrl, endpoints, wp_token } = wordpress;
    const headers = { Authorization: `Bearer ${wp_token}`, 'Content-Type': 'application/json' };
    return HttpService.post(`${baseUrl}${endpoints.missavsearch}`, { moviecode }, headers);
  },
  missavSearchAll: function (moviecodes, batchSize) {
    const { wordpress } = Config;
    const { baseUrl, endpoints, wp_token } = wordpress;
    const headers = { Authorization: `Bearer ${wp_token}`, 'Content-Type': 'application/json' };
    const url = `${baseUrl}${endpoints.missavsearch}`;
    const pairs = moviecodes.map(code => ({ url, payload: { moviecode: code } }));
    return HttpService.postAll(pairs, headers, batchSize);
  },

  /** Gets details for content using MissAV details endpoint. */
  missavDetails: function (url) {
    const { wordpress } = Config;
    const { baseUrl, endpoints, wp_token } = wordpress;
    const headers = {
      'Authorization': `Bearer ${wp_token}`,
      'Content-Type': 'application/json'
    };
    const payload = {
      url: url
    };
    const detailsUrl = `${baseUrl}${endpoints.missavdetails}`;
    Logger.log(detailsUrl)
    return HttpService.post(detailsUrl, payload, headers);
  },

  /** Gets details for content using MissAV details endpoint. */
  scoutMissAv: function (url) {
    const { wordpress } = Config;
    const { baseUrl, endpoints, wp_token } = wordpress;
    const headers = {
      'Authorization': `Bearer ${wp_token}`,
      'Content-Type': 'application/json'
    };
    const payload = {
      url: url
    };
    const scoutObj = `${baseUrl}${endpoints.missavscout}`;
    Logger.log(scoutObj)
    return HttpService.post(scoutObj, payload, headers);
  },

  /** Refreshes the WordPress authentication token. */
  refreshToken: function () {
    const { wordpress } = Config;
    const { baseUrl, endpoints, wp_token, wp_refreshToken } = wordpress;
    const headers = {
      'Authorization': `Bearer ${wp_token}`,
      'Content-Type': 'application/json'
    };
    const payload = {
      token: wp_refreshToken
    };
    const url = `${baseUrl}${endpoints.refreshToken}`;
    return HttpService.post(url, payload, headers);
  }
};
