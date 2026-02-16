"""WP REST API client for searching movie metadata."""

import logging
import time

import requests

from .metrics import API_REQUESTS_TOTAL, API_REQUEST_DURATION

logger = logging.getLogger(__name__)

# Unified search endpoint (backend handles provider selection)
# Note: base_url already includes /emby/v1, so just add /search
UNIFIED_SEARCH_ENDPOINT = '/search'


class MetadataClient:
    """Client for the emby-service WP REST API."""

    def __init__(self, base_url: str, token: str = '', search_order: list[str] | None = None,
                 token_manager=None):
        """Initialize metadata client.

        Args:
            base_url: WordPress API base URL
            token: Authorization token (static fallback)
            search_order: DEPRECATED - no longer used, backend handles provider selection
            token_manager: Optional TokenManager instance for auto-refreshing tokens
        """
        self.base_url = base_url.rstrip('/')
        self._static_token = token
        self._token_manager = token_manager
        # search_order kept for backwards compatibility but not used
        if search_order:
            logger.info('search_order parameter is deprecated - unified search handles provider selection')

    @property
    def token(self) -> str:
        """Get the current token (from token_manager if available, else static)."""
        if self._token_manager:
            return self._token_manager.get_token()
        return self._static_token

    def search(self, movie_code: str, fresh: bool = False) -> dict | None:
        """Search for movie metadata using unified endpoint.

        The backend handles provider fallback logic (missav → javguru).

        Args:
            movie_code: The movie code to search for
            fresh: If True, bypass cache and fetch fresh data from API

        Returns:
            Metadata dict on success, None on failure.
        """
        url = f'{self.base_url}{UNIFIED_SEARCH_ENDPOINT}'
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        payload = {'moviecode': movie_code}
        if fresh:
            payload['fresh'] = True

        try:
            fresh_text = ' (FORCE FRESH)' if fresh else ''
            logger.info('Searching metadata for %s via unified endpoint%s', movie_code, fresh_text)

            start = time.monotonic()
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
            )
            API_REQUEST_DURATION.labels(service='wordpress', operation='search').observe(time.monotonic() - start)

            # Handle 401 with token refresh + single retry
            if resp.status_code == 401 and self._token_manager:
                API_REQUESTS_TOTAL.labels(service='wordpress', status='401').inc()
                logger.warning('Got 401 for %s, attempting token refresh', movie_code)
                self._token_manager.handle_401()
                # Rebuild headers with new token
                headers['Authorization'] = f'Bearer {self.token}'
                start = time.monotonic()
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                API_REQUEST_DURATION.labels(service='wordpress', operation='search').observe(time.monotonic() - start)

            resp.raise_for_status()
            body = resp.json()

            API_REQUESTS_TOTAL.labels(service='wordpress', status='success').inc()

            if body.get('success') and body.get('data'):
                source = body.get('source', 'unknown')
                cache_status = ' [FRESH]' if fresh else ' [cached]'
                logger.info('Found metadata for %s via %s (unified search)%s', movie_code, source, cache_status)
                return body['data']

            logger.info('No metadata found for %s (unified search)', movie_code)
            return None

        except requests.RequestException as e:
            API_REQUESTS_TOTAL.labels(service='wordpress', status='error').inc()
            logger.warning('Unified search failed for %s: %s', movie_code, e)
            return None
