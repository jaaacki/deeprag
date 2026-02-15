"""WP REST API client for searching movie metadata."""

import logging
import requests

logger = logging.getLogger(__name__)

# Unified search endpoint (backend handles provider selection)
UNIFIED_SEARCH_ENDPOINT = '/emby/v1/search'


class MetadataClient:
    """Client for the emby-service WP REST API."""

    def __init__(self, base_url: str, token: str = '', search_order: list[str] | None = None):
        """Initialize metadata client.

        Args:
            base_url: WordPress API base URL
            token: Authorization token
            search_order: DEPRECATED - no longer used, backend handles provider selection
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        # search_order kept for backwards compatibility but not used
        if search_order:
            logger.info('search_order parameter is deprecated - unified search handles provider selection')

    def search(self, movie_code: str) -> dict | None:
        """Search for movie metadata using unified endpoint.

        The backend handles provider fallback logic (missav → javguru).
        Returns metadata dict on success, None on failure.
        """
        url = f'{self.base_url}{UNIFIED_SEARCH_ENDPOINT}'
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        try:
            logger.info('Searching metadata for %s via unified endpoint', movie_code)
            resp = requests.post(
                url,
                json={'moviecode': movie_code},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()

            if body.get('success') and body.get('data'):
                source = body.get('source', 'unknown')
                logger.info('Found metadata for %s via %s (unified search)', movie_code, source)
                return body['data']

            logger.info('No metadata found for %s (unified search)', movie_code)
            return None

        except requests.RequestException as e:
            logger.warning('Unified search failed for %s: %s', movie_code, e)
            return None
