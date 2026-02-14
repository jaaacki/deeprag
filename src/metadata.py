"""WP REST API client for searching movie metadata."""

import logging
import requests

logger = logging.getLogger(__name__)

# Endpoint paths per source
SEARCH_ENDPOINTS = {
    'missav': '/missav/search',
    'javguru': '/javguru/search',
}


class MetadataClient:
    """Client for the emby-service WP REST API."""

    def __init__(self, base_url: str, token: str = '', search_order: list[str] | None = None):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.search_order = search_order or ['missav', 'javguru']

    def search(self, movie_code: str) -> dict | None:
        """Search for movie metadata across configured sources.

        Tries each source in search_order. Returns the first successful
        result's data dict, or None if all sources fail.
        """
        for source in self.search_order:
            endpoint = SEARCH_ENDPOINTS.get(source)
            if not endpoint:
                logger.warning('Unknown search source: %s', source)
                continue

            url = f'{self.base_url}{endpoint}'
            result = self._post_search(url, movie_code, source)
            if result is not None:
                return result

        return None

    def _post_search(self, url: str, movie_code: str, source: str) -> dict | None:
        """POST a search request and return data dict on success."""
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        try:
            resp = requests.post(
                url,
                json={'moviecode': movie_code},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()

            if body.get('success') and body.get('data'):
                logger.info('Found metadata for %s via %s', movie_code, source)
                return body['data']

            logger.info('No result for %s via %s', movie_code, source)
            return None

        except requests.RequestException as e:
            logger.warning('API request failed for %s via %s: %s', movie_code, source, e)
            return None
