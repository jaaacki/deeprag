"""Emby server API client for triggering library scans and image management."""

import base64
import logging
import time
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

import requests

from .metrics import API_REQUESTS_TOTAL, API_REQUEST_DURATION

logger = logging.getLogger(__name__)

# Default retry schedule: exponential backoff 2s, 4s, 8s, 16s, 32s, 64s
DEFAULT_RETRY_DELAYS = [2, 4, 8, 16, 32, 64]

# Image types uploaded per item: Primary (original), Backdrop (W800), Banner (W800)
IMAGE_TYPES = ('Primary', 'Backdrop', 'Banner')


class EmbyClient:
    """Client for Emby server API operations."""

    def __init__(self, base_url: str, api_key: str, parent_folder_id: str = '',
                 user_id: str = '', wordpress_token: str = '', retry_delays: list[int] | None = None,
                 token_manager=None):
        """Initialize Emby client.

        Args:
            base_url: Emby server URL (e.g., 'https://emby.familyhub.id' or 'http://emby:8096')
            api_key: Emby API token
            parent_folder_id: Parent folder ID for the main video library (e.g., '4')
            user_id: Emby user ID for API calls (required for item access)
            wordpress_token: WordPress API token for downloading images (static fallback)
            retry_delays: List of delay seconds for retry attempts. Defaults to [2,4,8,16,32,64].
            token_manager: Optional TokenManager instance for auto-refreshing WordPress tokens
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.parent_folder_id = parent_folder_id
        self.user_id = user_id
        self._static_wordpress_token = wordpress_token
        self._token_manager = token_manager
        self.retry_delays = retry_delays if retry_delays is not None else DEFAULT_RETRY_DELAYS

    @property
    def wordpress_token(self) -> str:
        """Get the current WordPress token (from token_manager if available, else static)."""
        if self._token_manager:
            return self._token_manager.get_token()
        return self._static_wordpress_token

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
        """Trigger scan for a specific library/folder by ID.

        Uses the /emby/Items/{id}/Refresh?Recursive=true endpoint pattern
        matching the legacy Google Apps Script implementation.

        Args:
            library_id: The library or parent folder ID to scan

        Returns:
            True if scan was triggered successfully, False otherwise.
        """
        url = f'{self.base_url}/emby/Items/{library_id}/Refresh'
        headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json',
        }
        params = {'Recursive': 'true'}

        try:
            start = time.monotonic()
            resp = requests.post(url, headers=headers, params=params, timeout=30)
            API_REQUEST_DURATION.labels(service='emby', operation='scan_library').observe(time.monotonic() - start)
            resp.raise_for_status()
            API_REQUESTS_TOTAL.labels(service='emby', status='success').inc()
            logger.info('Emby library %s scan triggered successfully', library_id)
            return True
        except requests.RequestException as e:
            API_REQUESTS_TOTAL.labels(service='emby', status='error').inc()
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
            start = time.monotonic()
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            API_REQUEST_DURATION.labels(service='emby', operation='get_item_by_path').observe(time.monotonic() - start)
            resp.raise_for_status()
            API_REQUESTS_TOTAL.labels(service='emby', status='success').inc()
            data = resp.json()
            items = data.get('Items', [])

            if items:
                logger.info('Found Emby item for path %s: %s', file_path, items[0].get('Id'))
                return items[0]

            logger.warning('No Emby item found for path: %s', file_path)
            return None
        except requests.RequestException as e:
            API_REQUESTS_TOTAL.labels(service='emby', status='error').inc()
            logger.error('Failed to find Emby item by path: %s', e)
            return None

    def get_item_by_path_with_retry(self, file_path: str) -> dict | None:
        """Find Emby item by file path, retrying with exponential backoff.

        After a library scan, Emby takes time to index new files. This method
        polls with exponential backoff until the item appears or retries are
        exhausted. Falls back to find_item_by_filename if path search fails.

        Args:
            file_path: Full path to the video file

        Returns:
            Item dict with Id and other metadata, or None if not found after all retries.
        """
        # Try immediate lookup first (no delay)
        item = self.get_item_by_path(file_path)
        if item:
            return item

        # Retry with exponential backoff
        for i, delay in enumerate(self.retry_delays):
            logger.info(
                'Item not found yet, retry %d/%d in %ds for: %s',
                i + 1, len(self.retry_delays), delay, file_path,
            )
            time.sleep(delay)

            item = self.get_item_by_path(file_path)
            if item:
                logger.info('Found item after retry %d for: %s', i + 1, file_path)
                return item

        # Final fallback: search by filename
        from pathlib import Path
        filename = Path(file_path).name
        logger.info('Path search exhausted, trying filename fallback: %s', filename)
        item = self.find_item_by_filename(filename)
        if item:
            logger.info('Found item via filename fallback: %s', filename)
            return item

        logger.error(
            'Could not find Emby item after %d retries for: %s',
            len(self.retry_delays), file_path,
        )
        return None

    def find_item_by_filename(self, filename: str) -> dict | None:
        """Find Emby item by searching for filename within the parent folder.

        Uses the ParentId-based search matching the legacy Google Apps Script
        pattern (getItemsAllByParentIds with ParentId).

        Args:
            filename: The video filename to search for (e.g., 'ABC-123.mp4')

        Returns:
            Item dict with Id and other metadata, or None if not found.
        """
        url = f'{self.base_url}/Items'
        headers = {'X-Emby-Token': self.api_key}
        params = {
            'Recursive': 'true',
            'IncludeItemTypes': 'Video',
            'Fields': 'Path',
            'SearchTerm': filename,
        }

        # Scope search to parent folder if configured
        if self.parent_folder_id:
            params['ParentId'] = self.parent_folder_id

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('Items', [])

            # Match by filename in the Path field
            for item in items:
                item_path = item.get('Path', '')
                if item_path.endswith(filename):
                    logger.info('Found Emby item by filename %s: %s', filename, item.get('Id'))
                    return item

            # If no exact path match but we got results, return the first one
            if items:
                logger.info(
                    'No exact path match for %s, using first search result: %s',
                    filename, items[0].get('Id'),
                )
                return items[0]

            logger.warning('No Emby item found for filename: %s', filename)
            return None
        except requests.RequestException as e:
            logger.error('Failed to find Emby item by filename: %s', e)
            return None

    def get_item_details(self, item_id: str) -> dict | None:
        """Get full details for an Emby item.

        Args:
            item_id: The Emby item ID

        Returns:
            Full item dict, or None on error.
        """
        # Use Users endpoint for item access (required by Emby API)
        if self.user_id:
            url = f'{self.base_url}/Users/{self.user_id}/Items/{item_id}'
        else:
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
        # Name: Extract from file path (filename without extension), matching legacy behavior
        file_path = emby_item.get('Path', '')
        if file_path:
            # Extract filename without extension: /path/to/file.mp4 -> file
            filename = file_path.replace('\\', '/').split('/')[-1]  # Get last part
            name_without_ext = filename.rsplit('.', 1)[0]  # Remove extension
            emby_item['Name'] = name_without_ext
            emby_item['SortName'] = name_without_ext  # Same as Name
            emby_item['ForcedSortName'] = name_without_ext  # Same as Name

        emby_item['OriginalTitle'] = metadata.get('original_title', '')  # Japanese title
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
            start = time.monotonic()
            resp = requests.post(url, json=emby_item, headers=headers, timeout=30)
            API_REQUEST_DURATION.labels(service='emby', operation='update_metadata').observe(time.monotonic() - start)
            logger.info('Emby update response: status=%s, body=%s', resp.status_code, resp.text[:200])
            resp.raise_for_status()
            API_REQUESTS_TOTAL.labels(service='emby', status='success').inc()
        except requests.RequestException as e:
            API_REQUESTS_TOTAL.labels(service='emby', status='error').inc()
            logger.error('Failed to update Emby item %s: %s', item_id, e)
            if hasattr(e, 'response') and e.response is not None:
                logger.error('Response status: %s, body: %s', e.response.status_code, e.response.text[:500])
            return False

        # Verify the update was persisted by reading back from Emby
        time.sleep(1)  # Brief pause for Emby to persist
        verified = self.get_item_details(item_id)
        if not verified:
            logger.error('Verification failed: could not read back item %s', item_id)
            return False

        mismatches = []
        # Check Name
        expected_name = emby_item.get('Name', '')
        actual_name = verified.get('Name', '')
        if expected_name and actual_name != expected_name:
            mismatches.append(f'Name: expected={expected_name!r}, got={actual_name!r}')

        # Check OriginalTitle
        expected_ot = emby_item.get('OriginalTitle', '')
        actual_ot = verified.get('OriginalTitle', '')
        if expected_ot and actual_ot != expected_ot:
            mismatches.append(f'OriginalTitle: expected={expected_ot[:40]!r}, got={actual_ot[:40]!r}')

        # Check Overview
        expected_ov = emby_item.get('Overview', '')
        actual_ov = verified.get('Overview', '')
        if expected_ov and actual_ov != expected_ov:
            mismatches.append(f'Overview: expected len={len(expected_ov)}, got len={len(actual_ov)}')

        # Check LockData
        if not verified.get('LockData'):
            mismatches.append('LockData: not set')

        if mismatches:
            logger.error('Emby update verification FAILED for item %s: %s', item_id, '; '.join(mismatches))
            return False

        logger.info('Emby update verified for item %s', item_id)
        return True

    # ---- Image management methods ----

    def download_image(self, image_url: str) -> tuple[bytes, str] | None:
        """Download an image from a URL.

        Args:
            image_url: Full URL of the image to download.

        Returns:
            Tuple of (image_bytes, content_type) on success, None on failure.
        """
        if not image_url or not image_url.strip():
            logger.warning('Empty image URL, skipping download')
            return None

        try:
            # Build headers - add WordPress auth if URL is from WordPress
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'image/*,*/*;q=0.8',
            }

            # Add WordPress Bearer token if downloading from WordPress domain
            if self.wordpress_token and 'familyhub.id' in image_url:
                headers['Authorization'] = f'Bearer {self.wordpress_token}'

            resp = requests.get(
                image_url,
                headers=headers,
                timeout=30,
                allow_redirects=True,
            )

            # Handle 401 with token refresh + single retry (WordPress URLs only)
            if resp.status_code == 401 and self._token_manager and 'familyhub.id' in image_url:
                logger.warning('Got 401 downloading image, attempting token refresh')
                self._token_manager.handle_401()
                headers['Authorization'] = f'Bearer {self.wordpress_token}'
                resp = requests.get(
                    image_url,
                    headers=headers,
                    timeout=30,
                    allow_redirects=True,
                )

            # WordPress media-crop endpoints return image data but with 404 status
            # Accept response if we got valid image data, regardless of status code
            content_type = resp.headers.get('Content-Type', '')
            if content_type.startswith('image/') and len(resp.content) > 0:
                logger.info('Downloaded image (%d bytes) from %s (status=%d)',
                           len(resp.content), image_url, resp.status_code)
                return resp.content, content_type

            # If no valid image data, check status code and fail appropriately
            if resp.status_code >= 400:
                logger.warning('URL returned %d without image data: %s', resp.status_code, image_url)
                return None

            logger.warning('URL did not return an image (got %s): %s', content_type, image_url)
            return None
        except requests.RequestException as e:
            logger.error('Failed to download image from %s: %s', image_url, e)
            return None

    @staticmethod
    def _make_w800_url(image_url: str) -> str:
        """Transform an image URL to request a W800 variant.

        Adds or replaces the `w` query parameter with `800` and removes `horizontal`.
        Mirrors the legacy Util.convertBase64FromUrlW800 logic.

        Args:
            image_url: Original image URL.

        Returns:
            Modified URL with w=800.
        """
        parsed = urlparse(image_url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params['w'] = ['800']
        params.pop('horizontal', None)
        # Flatten single-value lists for clean URL
        flat_params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
        new_query = urlencode(flat_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    def download_image_w800(self, image_url: str) -> tuple[bytes, str] | None:
        """Download a W800-resized variant of an image.

        Used for Backdrop and Banner image types.

        Args:
            image_url: Original image URL (will be modified to add w=800).

        Returns:
            Tuple of (image_bytes, content_type) on success, None on failure.
        """
        w800_url = self._make_w800_url(image_url)
        return self.download_image(w800_url)

    def delete_image(self, item_id: str, image_type: str, index: int = 0) -> bool:
        """Delete an image from an Emby item.

        Args:
            item_id: The Emby item ID.
            image_type: Image type (e.g., 'Primary', 'Backdrop', 'Banner', 'Logo').
            index: Image index (used for types that support multiple images like Backdrop).

        Returns:
            True if deletion succeeded or image didn't exist, False on error.
        """
        url = f'{self.base_url}/Items/{item_id}/Images/{image_type}/{index}'
        headers = {'X-Emby-Token': self.api_key}

        try:
            resp = requests.delete(url, headers=headers, timeout=10)
            # 204 No Content = success, 404 = already gone (both are fine)
            if resp.status_code in (200, 204, 404):
                logger.info('Deleted image %s/%d from item %s (status=%s)',
                            image_type, index, item_id, resp.status_code)
                return True
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error('Failed to delete image %s/%d from item %s: %s',
                         image_type, index, item_id, e)
            return False

    def upload_image(self, item_id: str, image_type: str, image_data: bytes,
                     content_type: str = 'image/jpeg') -> bool:
        """Upload an image to an Emby item.

        Sends the image as base64-encoded body with the appropriate content type,
        matching the legacy EmbyService.uploadImage pattern.

        Args:
            item_id: The Emby item ID.
            image_type: Image type ('Primary', 'Backdrop', 'Banner').
            image_data: Raw image bytes.
            content_type: MIME type of the image (default: 'image/jpeg').

        Returns:
            True if upload succeeded, False otherwise.
        """
        url = f'{self.base_url}/Items/{item_id}/Images/{image_type}'
        params = {'api_key': self.api_key}
        encoded = base64.b64encode(image_data).decode('ascii')

        try:
            start = time.monotonic()
            resp = requests.post(
                url,
                params=params,
                data=encoded,
                headers={'Content-Type': content_type},
                timeout=60,
            )
            API_REQUEST_DURATION.labels(service='emby', operation='upload_image').observe(time.monotonic() - start)
            resp.raise_for_status()
            API_REQUESTS_TOTAL.labels(service='emby', status='success').inc()
            logger.info('Uploaded %s image to item %s', image_type, item_id)
            return True
        except requests.RequestException as e:
            API_REQUESTS_TOTAL.labels(service='emby', status='error').inc()
            logger.error('Failed to upload %s image to item %s: %s', image_type, item_id, e)
            return False

    def upload_item_images(self, item_id: str, image_url: str) -> bool:
        """Download and upload all image types for an Emby item.

        Follows the legacy flow:
        1. Delete existing Backdrop (indices 0-4), Banner, Primary, Logo images
        2. Download original image -> upload as Primary
        3. Download W800 variant -> upload as Backdrop and Banner

        Errors are logged but do not block the pipeline.

        Args:
            item_id: The Emby item ID.
            image_url: Source image URL (from WordPress metadata, e.g., image_cropped or raw_image_url).

        Returns:
            True if at least one image was uploaded, False if all failed.
        """
        if not image_url:
            logger.warning('No image URL provided for item %s, skipping image upload', item_id)
            return False

        # Step 1: Delete existing images (best-effort)
        for i in range(5):
            self.delete_image(item_id, 'Backdrop', i)
        self.delete_image(item_id, 'Banner')
        self.delete_image(item_id, 'Primary')
        self.delete_image(item_id, 'Logo')

        any_success = False

        # Step 2: Download and upload W800 variant for Backdrop and Banner
        w800_result = self.download_image_w800(image_url)
        if w800_result:
            w800_data, w800_ct = w800_result
            if self.upload_image(item_id, 'Backdrop', w800_data, w800_ct):
                any_success = True
            if self.upload_image(item_id, 'Banner', w800_data, w800_ct):
                any_success = True
        else:
            logger.warning('Could not download W800 image for item %s', item_id)

        # Step 3: Download and upload original for Primary
        original_result = self.download_image(image_url)
        if original_result:
            orig_data, orig_ct = original_result
            if self.upload_image(item_id, 'Primary', orig_data, orig_ct):
                any_success = True
        else:
            logger.warning('Could not download original image for item %s', item_id)

        if any_success:
            logger.info('Image upload completed for item %s', item_id)
        else:
            logger.error('All image uploads failed for item %s', item_id)

        return any_success

    def generate_video_preview(self) -> bool:
        """Trigger the Emby scheduled task that generates video preview/trickplay images.

        Returns:
            True if the task was triggered successfully, False otherwise.
        """
        task_id = 'd15b3f9fc313609ffe7e49bd1c74f753'
        url = f'{self.base_url}/emby/ScheduledTasks/Running/{task_id}'
        headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json',
        }
        try:
            resp = requests.post(url, headers=headers, timeout=15)
            if resp.status_code < 300:
                logger.info('Video preview generation task triggered')
                return True
            logger.warning('Failed to trigger video preview task: %s %s', resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error('Error triggering video preview task: %s', e)
            return False
