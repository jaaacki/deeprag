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

        logger.info('Metadata: actress=%s, title=%s', actress, title)

        # Step 5: Build new filename
        extension = path.suffix
        new_filename = build_filename(actress, subtitle, api_code, title, extension)

        # Step 6: Move to destination
        destination_dir = self.config.get('destination_dir', '/destination')
        try:
            new_path = move_file(file_path, destination_dir, actress, new_filename)
            logger.info('Success: %s -> %s', filename, new_path)

            # Step 7: Trigger Emby library scan
            if self.emby_client and self.trigger_scan:
                emby_config = self.config.get('emby', {})
                library_id = emby_config.get('library_id', '')

                if library_id:
                    logger.info('Triggering Emby scan for library %s', library_id)
                    self.emby_client.scan_library_by_id(library_id)
                else:
                    logger.info('Triggering Emby library scan')
                    self.emby_client.trigger_library_scan()

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
