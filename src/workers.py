"""Worker processes for the queue-based processing pipeline.

Workers poll the database for items in specific states and process them.
Each worker runs in its own thread and can be shut down gracefully.

Status flow: pending -> processing -> moved -> emby_pending -> completed
"""

import json
import logging
import signal
import threading
import time
from pathlib import Path
from typing import Optional

from .emby_client import EmbyClient
from .extractor import extract_movie_code, detect_subtitle
from .metadata import MetadataClient
from .queue import QueueDB
from .renamer import build_filename, move_file

logger = logging.getLogger(__name__)


class BaseWorker:
    """Base class for queue workers with common start/stop logic."""

    def __init__(self, queue_db: QueueDB, poll_interval: float = 5.0):
        self.queue_db = queue_db
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def start(self):
        """Start the worker in a daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name=self.name, daemon=True)
        self._thread.start()
        logger.info('%s started', self.name)

    def stop(self, timeout: float = 10.0):
        """Signal the worker to stop and wait for it to finish."""
        logger.info('%s stopping...', self.name)
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning('%s did not stop within %ss', self.name, timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        """Main loop: poll for work, process it, sleep if idle."""
        logger.info('%s loop started', self.name)
        while not self._stop_event.is_set():
            try:
                did_work = self.process_one()
                if not did_work:
                    self._stop_event.wait(timeout=self.poll_interval)
            except Exception:
                logger.exception('%s encountered an error in run loop', self.name)
                self._stop_event.wait(timeout=self.poll_interval)
        logger.info('%s loop ended', self.name)

    def process_one(self) -> bool:
        """Process a single item. Return True if work was done, False if idle."""
        raise NotImplementedError


class FileProcessorWorker(BaseWorker):
    """Picks pending items from the queue, processes the file (extract code,
    fetch metadata, rename, move), and marks them as 'moved'.
    """

    def __init__(
        self,
        queue_db: QueueDB,
        config: dict,
        metadata_client: MetadataClient,
        poll_interval: float = 5.0,
    ):
        super().__init__(queue_db, poll_interval)
        self.config = config
        self.metadata_client = metadata_client
        self.error_dir = config.get('error_dir', '/watch/errors')
        self.destination_dir = config.get('destination_dir', '/destination')

    def process_one(self) -> bool:
        item = self.queue_db.get_next_pending()
        if not item:
            return False

        item_id = item['id']
        file_path = item['file_path']
        filename = Path(file_path).name
        logger.info('[FileProcessor] Processing item %s: %s', item_id, filename)

        try:
            # Step 1: Extract movie code
            movie_code = extract_movie_code(filename)
            if not movie_code:
                logger.warning('[FileProcessor] No movie code in: %s', filename)
                self._move_to_errors(file_path)
                self.queue_db.update_status(
                    item_id, 'error',
                    error_message=f'No movie code found in filename: {filename}',
                )
                return True

            # Step 2: Detect subtitle
            subtitle = detect_subtitle(filename)
            logger.info('[FileProcessor] Extracted: code=%s subtitle=%s', movie_code, subtitle)

            # Step 3: Fetch metadata
            metadata = self.metadata_client.search(movie_code)
            if metadata is None:
                logger.info('[FileProcessor] Retrying metadata for %s', movie_code)
                metadata = self.metadata_client.search(movie_code)

            if metadata is None:
                logger.warning('[FileProcessor] No metadata for %s', movie_code)
                self._move_to_errors(file_path)
                self.queue_db.update_status(
                    item_id, 'error',
                    error_message=f'No metadata found for movie code: {movie_code}',
                )
                return True

            # Step 4: Extract fields from metadata
            actress_list = metadata.get('actress', [])
            actress = actress_list[0] if actress_list else 'Unknown'
            title = metadata.get('title', '')
            api_code = metadata.get('movie_code', movie_code)

            actress = actress.title()

            if title.upper().startswith(api_code.upper()):
                title = title[len(api_code):].strip()
                if title and title[0] in ['-', ' ']:
                    title = title[1:].strip()

            title = title.title()

            # Step 5: Build new filename and move
            extension = Path(file_path).suffix
            new_filename = build_filename(actress, subtitle, api_code, title, extension)

            new_path = move_file(file_path, self.destination_dir, actress, new_filename)
            logger.info('[FileProcessor] Moved: %s -> %s', filename, new_path)

            # Step 6: Update queue item
            self.queue_db.update_status(
                item_id, 'moved',
                new_path=new_path,
                metadata_json=metadata,
            )
            # Also update the extracted fields on the item
            conn = self.queue_db._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE processing_queue
                           SET movie_code = %s, actress = %s, subtitle = %s
                           WHERE id = %s""",
                        (api_code, actress, subtitle, item_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self.queue_db._put_conn(conn)

            return True

        except Exception as e:
            logger.exception('[FileProcessor] Failed to process item %s', item_id)
            self.queue_db.update_status(
                item_id, 'error',
                error_message=str(e),
            )
            return True

    def _move_to_errors(self, file_path: str) -> None:
        """Move a file to the error directory."""
        import shutil
        error_dir = Path(self.error_dir)
        error_dir.mkdir(parents=True, exist_ok=True)
        dest = error_dir / Path(file_path).name
        try:
            shutil.move(file_path, str(dest))
            logger.info('[FileProcessor] Moved to errors: %s', dest)
        except OSError as e:
            logger.error('[FileProcessor] Failed to move %s to errors: %s', file_path, e)


class EmbyUpdaterWorker(BaseWorker):
    """Picks 'moved' items, triggers Emby library scan, finds the item in Emby,
    updates metadata, and marks items as 'completed'.
    """

    def __init__(
        self,
        queue_db: QueueDB,
        config: dict,
        emby_client: Optional[EmbyClient] = None,
        poll_interval: float = 10.0,
    ):
        super().__init__(queue_db, poll_interval)
        self.config = config
        self.emby_client = emby_client
        self.parent_folder_id = config.get('emby', {}).get('parent_folder_id', '')

    def process_one(self) -> bool:
        if not self.emby_client:
            return False

        item = self.queue_db.get_next_moved()
        if not item:
            return False

        item_id = item['id']
        new_path = item.get('new_path', '')
        logger.info('[EmbyUpdater] Processing item %s: %s', item_id, new_path)

        try:
            # Step 1: Trigger library scan using parent folder ID
            if self.parent_folder_id:
                logger.info('[EmbyUpdater] Triggering scan for parent folder %s', self.parent_folder_id)
                scan_success = self.emby_client.scan_library_by_id(self.parent_folder_id)
            else:
                logger.info('[EmbyUpdater] Triggering full library scan')
                scan_success = self.emby_client.trigger_library_scan()

            if not scan_success:
                logger.error('[EmbyUpdater] Scan failed for item %s', item_id)
                self.queue_db.update_status(
                    item_id, 'error',
                    error_message='Emby library scan failed',
                )
                return True

            # Step 2: Poll for the item with exponential backoff retry
            logger.info('[EmbyUpdater] Polling for Emby item with retry: %s', new_path)
            emby_item = self.emby_client.get_item_by_path_with_retry(new_path)
            if not emby_item:
                logger.warning('[EmbyUpdater] Item not found in Emby after retries: %s', new_path)
                self.queue_db.update_status(
                    item_id, 'error',
                    error_message=f'Emby item not found for path: {new_path}',
                )
                return True

            emby_item_id = emby_item.get('Id')

            # Step 3: Update Emby metadata
            metadata = item.get('metadata_json')
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            if metadata:
                update_success = self.emby_client.update_item_metadata(emby_item_id, metadata)
                if not update_success:
                    logger.error('[EmbyUpdater] Failed to update metadata for Emby item %s', emby_item_id)
                    self.queue_db.update_status(
                        item_id, 'error',
                        error_message=f'Failed to update Emby metadata for item {emby_item_id}',
                        emby_item_id=emby_item_id,
                    )
                    return True

                # Step 4: Upload images (best-effort, don't block pipeline)
                image_url = metadata.get('image_cropped') or metadata.get('raw_image_url', '')
                if image_url:
                    try:
                        self.emby_client.upload_item_images(emby_item_id, image_url)
                    except Exception as e:
                        logger.error('[EmbyUpdater] Image upload failed for item %s: %s', emby_item_id, e)
                else:
                    logger.info('[EmbyUpdater] No image URL in metadata for item %s', emby_item_id)

            # Step 5: Mark completed
            self.queue_db.update_status(
                item_id, 'completed',
                emby_item_id=emby_item_id,
            )
            logger.info('[EmbyUpdater] Completed item %s (Emby ID: %s)', item_id, emby_item_id)
            return True

        except Exception as e:
            logger.exception('[EmbyUpdater] Failed to process item %s', item_id)
            self.queue_db.update_status(
                item_id, 'error',
                error_message=str(e),
            )
            return True


class RetryHandler(BaseWorker):
    """Periodically checks for error items eligible for retry and resets them
    back to 'pending' status with exponential backoff.
    """

    def __init__(self, queue_db: QueueDB, poll_interval: float = 30.0):
        super().__init__(queue_db, poll_interval)

    def process_one(self) -> bool:
        retryable = self.queue_db.get_retryable_errors(limit=10)
        if not retryable:
            return False

        for item in retryable:
            item_id = item['id']
            retry_count = item['retry_count']
            logger.info(
                '[RetryHandler] Retrying item %s (attempt %d)',
                item_id, retry_count,
            )
            self.queue_db.reset_for_retry(item_id)

        logger.info('[RetryHandler] Reset %d items for retry', len(retryable))
        return True


class WorkerManager:
    """Manages the lifecycle of all worker threads and handles graceful shutdown."""

    def __init__(
        self,
        queue_db: QueueDB,
        config: dict,
        metadata_client: MetadataClient,
        emby_client: Optional[EmbyClient] = None,
    ):
        self.queue_db = queue_db
        self.config = config
        self._shutdown_event = threading.Event()

        worker_config = config.get('workers', {})

        self.file_processor = FileProcessorWorker(
            queue_db=queue_db,
            config=config,
            metadata_client=metadata_client,
            poll_interval=worker_config.get('file_processor_interval', 5.0),
        )

        self.emby_updater = EmbyUpdaterWorker(
            queue_db=queue_db,
            config=config,
            emby_client=emby_client,
            poll_interval=worker_config.get('emby_updater_interval', 10.0),
        )

        self.retry_handler = RetryHandler(
            queue_db=queue_db,
            poll_interval=worker_config.get('retry_interval', 30.0),
        )

        self._workers = [self.file_processor, self.emby_updater, self.retry_handler]

    def start_all(self):
        """Start all worker threads."""
        logger.info('Starting all workers...')
        for worker in self._workers:
            worker.start()
        logger.info('All workers started')

    def stop_all(self, timeout: float = 15.0):
        """Signal all workers to stop and wait for them."""
        logger.info('Stopping all workers...')
        self._shutdown_event.set()
        for worker in self._workers:
            worker.stop(timeout=timeout)
        logger.info('All workers stopped')

    def install_signal_handlers(self):
        """Install SIGTERM and SIGINT handlers for graceful shutdown."""
        def handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info('Received %s, initiating graceful shutdown...', sig_name)
            self._shutdown_event.set()

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    @property
    def shutdown_event(self) -> threading.Event:
        return self._shutdown_event

    def wait_for_shutdown(self):
        """Block until a shutdown signal is received, then stop all workers."""
        try:
            while not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_all()
