"""Emby server API client for triggering library scans."""

import logging
import requests

logger = logging.getLogger(__name__)


class EmbyClient:
    """Client for Emby server API operations."""

    def __init__(self, base_url: str, api_key: str):
        """Initialize Emby client.

        Args:
            base_url: Emby server URL (e.g., 'https://emby.familyhub.id' or 'http://emby:8096')
            api_key: Emby API token
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def trigger_library_scan(self, path: str | None = None) -> bool:
        """Trigger Emby to scan the library.

        Args:
            path: Optional specific path to scan. If None, scans all libraries.

        Returns:
            True if scan was triggered successfully, False otherwise.
        """
        url = f'{self.base_url}/Library/Refresh'
        headers = {'X-Emby-Token': self.api_key}
        params = {}

        if path:
            params['path'] = path

        try:
            resp = requests.post(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            logger.info('Emby library scan triggered successfully')
            return True
        except requests.RequestException as e:
            logger.warning('Failed to trigger Emby library scan: %s', e)
            return False

    def get_libraries(self) -> list[dict] | None:
        """Get list of all media libraries.

        Returns:
            List of library dicts with 'Name' and 'Id', or None on error.
        """
        url = f'{self.base_url}/Library/VirtualFolders'
        headers = {'X-Emby-Token': self.api_key}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            libraries = resp.json()
            logger.info('Found %d Emby libraries', len(libraries))
            return libraries
        except requests.RequestException as e:
            logger.warning('Failed to get Emby libraries: %s', e)
            return None

    def scan_library_by_id(self, library_id: str) -> bool:
        """Trigger scan for a specific library by ID.

        Args:
            library_id: The library ID to scan

        Returns:
            True if scan was triggered successfully, False otherwise.
        """
        url = f'{self.base_url}/Items/{library_id}/Refresh'
        headers = {'X-Emby-Token': self.api_key}
        params = {'Recursive': 'true', 'ImageRefreshMode': 'Default', 'MetadataRefreshMode': 'Default'}

        try:
            resp = requests.post(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            logger.info('Emby library %s scan triggered successfully', library_id)
            return True
        except requests.RequestException as e:
            logger.warning('Failed to trigger Emby library %s scan: %s', library_id, e)
            return False
