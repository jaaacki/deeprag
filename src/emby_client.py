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
            logger.info('Emby scan response: status=%s, body=%s', resp.status_code, resp.text[:200])
            resp.raise_for_status()
            logger.info('Emby library scan triggered successfully')
            return True
        except requests.RequestException as e:
            logger.error('Failed to trigger Emby library scan: %s', e)
            if hasattr(e, 'response') and e.response is not None:
                logger.error('Response status: %s, body: %s', e.response.status_code, e.response.text[:500])
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

    def get_item_by_path(self, file_path: str) -> dict | None:
        """Find Emby item by file path.

        Args:
            file_path: Full path to the video file

        Returns:
            Item dict with Id and other metadata, or None if not found.
        """
        url = f'{self.base_url}/Items'
        headers = {'X-Emby-Token': self.api_key}
        params = {
            'Recursive': 'true',
            'IncludeItemTypes': 'Movie',
            'Fields': 'Path',
            'Path': file_path,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('Items', [])

            if items:
                logger.info('Found Emby item for path %s: %s', file_path, items[0].get('Id'))
                return items[0]

            logger.warning('No Emby item found for path: %s', file_path)
            return None
        except requests.RequestException as e:
            logger.error('Failed to find Emby item by path: %s', e)
            return None

    def get_item_details(self, item_id: str) -> dict | None:
        """Get full details for an Emby item.

        Args:
            item_id: The Emby item ID

        Returns:
            Full item dict, or None on error.
        """
        url = f'{self.base_url}/Items/{item_id}'
        headers = {'X-Emby-Token': self.api_key}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            item = resp.json()
            logger.info('Retrieved Emby item details for %s', item_id)
            return item
        except requests.RequestException as e:
            logger.error('Failed to get Emby item details for %s: %s', item_id, e)
            return None

    def update_item_metadata(self, item_id: str, metadata: dict) -> bool:
        """Update Emby item metadata from WordPress API data.

        Args:
            item_id: The Emby item ID
            metadata: Metadata dict from WordPress API with fields like:
                - original_title, overview, release_date, actress (array),
                  genre (array/string), label, movie_code

        Returns:
            True if update succeeded, False otherwise.
        """
        # First, get the existing item
        emby_item = self.get_item_details(item_id)
        if not emby_item:
            logger.error('Cannot update metadata: item %s not found', item_id)
            return False

        # Build updated metadata
        emby_item['OriginalTitle'] = metadata.get('original_title', '')
        emby_item['Overview'] = metadata.get('overview', '')
        emby_item['PreferredMetadataLanguage'] = 'en'
        emby_item['PreferredMetadataCountryCode'] = 'JP'
        emby_item['ProductionLocations'] = ['Japan']
        emby_item['ProviderIds'] = {}

        # Handle release date and year
        release_date = metadata.get('release_date', '')
        if release_date:
            emby_item['PremiereDate'] = release_date
            # Extract year from date (format: YYYY-MM-DD)
            try:
                year = int(release_date.split('-')[0])
                emby_item['ProductionYear'] = year
            except (ValueError, IndexError):
                logger.warning('Could not parse year from release_date: %s', release_date)

        # Handle actress -> People
        actress_list = metadata.get('actress', [])
        if actress_list:
            emby_item['People'] = [
                {'Name': name.strip(), 'Type': 'Actor'}
                for name in actress_list
                if name.strip()
            ]

        # Handle genre -> GenreItems
        genre = metadata.get('genre', [])
        if isinstance(genre, str):
            # Split comma-separated string
            genre = [g.strip() for g in genre.split(',') if g.strip()]
        if genre:
            emby_item['GenreItems'] = [{'Name': g} for g in genre]

        # Handle label -> Studios
        label = metadata.get('label', '')
        if label:
            # Split comma-separated if needed
            labels = [l.strip() for l in label.split(',') if l.strip()]
            emby_item['Studios'] = [{'Name': l} for l in labels]

        # Lock data to prevent Emby from overwriting
        emby_item['LockData'] = True

        # POST the updated item back
        url = f'{self.base_url}/Items/{item_id}'
        headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json',
        }

        try:
            resp = requests.post(url, json=emby_item, headers=headers, timeout=30)
            logger.info('Emby update response: status=%s, body=%s', resp.status_code, resp.text[:200])
            resp.raise_for_status()
            logger.info('Successfully updated Emby item %s metadata', item_id)
            return True
        except requests.RequestException as e:
            logger.error('Failed to update Emby item %s: %s', item_id, e)
            if hasattr(e, 'response') and e.response is not None:
                logger.error('Response status: %s, body: %s', e.response.status_code, e.response.text[:500])
            return False
