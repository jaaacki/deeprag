"""Orchestrates the full processing pipeline for a single file."""

import logging
import shutil
from pathlib import Path

from .emby_client import EmbyClient
from .extractor import extract_movie_code, detect_subtitle
from .metadata import MetadataClient
from .renamer import build_filename, move_file

logger = logging.getLogger(__name__)


class Pipeline:
    """Process a video file: extract code, fetch metadata, rename, move."""

    def __init__(self, config: dict, metadata_client: MetadataClient, emby_client: EmbyClient | None = None):
        self.config = config
        self.client = metadata_client
        self.emby_client = emby_client
        self.error_dir = config.get('error_dir', '/watch/errors')
        self.trigger_scan = config.get('emby', {}).get('trigger_scan', True)

    def process(self, file_path: str) -> bool:
        """Run the full pipeline on a single file.

        Returns True on success, False on failure (file moved to error_dir).
        """
        path = Path(file_path)
        filename = path.name
        logger.info('Processing: %s', filename)

        # Step 1: Extract movie code
        movie_code = extract_movie_code(filename)
        if not movie_code:
            logger.warning('No movie code found in: %s', filename)
            self._move_to_errors(file_path)
            return False

        # Step 2: Detect subtitle
        subtitle = detect_subtitle(filename)
        logger.info('Extracted: code=%s, subtitle=%s', movie_code, subtitle)

        # Step 3: Fetch metadata
        metadata = self.client.search(movie_code)
        if metadata is None:
            # Retry once
            logger.info('Retrying metadata search for %s', movie_code)
            metadata = self.client.search(movie_code)

        if metadata is None:
            logger.warning('No metadata found for %s, moving to errors', movie_code)
            self._move_to_errors(file_path)
            return False

        # Step 4: Extract fields from metadata
        actress_list = metadata.get('actress', [])
        actress = actress_list[0] if actress_list else 'Unknown'
        title = metadata.get('title', '')
        # Use the API-returned movie code if available (properly formatted)
        api_code = metadata.get('movie_code', movie_code)

        # Proper-case actress name
        actress = actress.title()

        # Strip movie code from title if it's already there (avoid duplication)
        if title.upper().startswith(api_code.upper()):
            title = title[len(api_code):].strip()
            # Remove leading dash or space if present
            if title and title[0] in ['-', ' ']:
                title = title[1:].strip()

        # Apply proper title casing (first letter of each word capitalized)
        title = title.title()

        logger.info('Metadata: actress=%s, title=%s', actress, title)

        # Step 5: Build new filename
        extension = path.suffix
        new_filename = build_filename(actress, subtitle, api_code, title, extension)

        # Step 6: Move to destination
        destination_dir = self.config.get('destination_dir', '/destination')
        try:
            new_path = move_file(file_path, destination_dir, actress, new_filename)
            logger.info('Success: %s -> %s', filename, new_path)

            # Step 7: Trigger Emby library scan and update metadata
            if self.emby_client and self.trigger_scan:
                emby_config = self.config.get('emby', {})
                parent_folder_id = emby_config.get('parent_folder_id', '')

                # Trigger scan using parent folder ID (matches legacy /emby/Items/{id}/Refresh)
                if parent_folder_id:
                    logger.info('Triggering Emby scan for parent folder %s', parent_folder_id)
                    scan_success = self.emby_client.scan_library_by_id(parent_folder_id)
                else:
                    logger.info('Triggering Emby full library scan')
                    scan_success = self.emby_client.trigger_library_scan()

                if not scan_success:
                    logger.error('Emby scan failed, skipping metadata update')
                else:
                    # Poll for the item with exponential backoff retry
                    logger.info('Polling for Emby item with retry: %s', new_path)
                    emby_item = self.emby_client.get_item_by_path_with_retry(str(new_path))
                    if emby_item:
                        item_id = emby_item.get('Id')
                        logger.info('Found Emby item %s, updating metadata', item_id)

                        # Update metadata
                        update_success = self.emby_client.update_item_metadata(item_id, metadata)
                        if not update_success:
                            logger.error('Failed to update Emby metadata for item %s', item_id)
                        else:
                            logger.info('Successfully updated Emby metadata for item %s', item_id)

                        # Upload images (best-effort, don't block pipeline)
                        image_url = metadata.get('image_cropped') or metadata.get('raw_image_url', '')
                        if image_url:
                            try:
                                self.emby_client.upload_item_images(item_id, image_url)
                            except Exception as e:
                                logger.error('Image upload failed for item %s: %s', item_id, e)
                        else:
                            logger.info('No image URL in metadata for item %s, skipping image upload', item_id)
                    else:
                        logger.error('Could not find Emby item for path: %s', new_path)

            return True
        except OSError as e:
            logger.error('Failed to move %s: %s', filename, e)
            return False

    def _move_to_errors(self, file_path: str) -> None:
        """Move a file to the error directory."""
        error_dir = Path(self.error_dir)
        error_dir.mkdir(parents=True, exist_ok=True)

        dest = error_dir / Path(file_path).name
        try:
            shutil.move(file_path, str(dest))
            logger.info('Moved to errors: %s', dest)
        except OSError as e:
            logger.error('Failed to move %s to errors: %s', file_path, e)
