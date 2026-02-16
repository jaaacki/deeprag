"""Watch a directory for new video files and trigger processing."""

import logging
import os
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from .metrics import FILES_DETECTED_TOTAL

logger = logging.getLogger(__name__)


class StabilityChecker:
    """Wait for a file to stop being written to before processing."""

    def __init__(self, interval: int = 5, min_checks: int = 2):
        self.interval = interval
        self.min_checks = min_checks

    def wait_until_stable(self, file_path: str) -> bool:
        """Poll file size until it stabilizes.

        Returns True if file is stable, False if it disappeared.
        """
        stable_count = 0
        last_size = -1

        while stable_count < self.min_checks:
            try:
                current_size = os.path.getsize(file_path)
            except OSError:
                logger.warning('File disappeared while checking stability: %s', file_path)
                return False

            if current_size == last_size:
                stable_count += 1
            else:
                stable_count = 0

            last_size = current_size
            if stable_count < self.min_checks:
                time.sleep(self.interval)

        logger.info('File stable: %s (%d bytes)', file_path, last_size)
        return True


class VideoHandler(FileSystemEventHandler):
    """Handle new video files appearing in the watch directory."""

    def __init__(self, extensions: list[str], stability_checker: StabilityChecker, callback):
        super().__init__()
        self.extensions = {ext.lower() for ext in extensions}
        self.stability_checker = stability_checker
        self.callback = callback

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent):
            self._handle(event.src_path)

    def on_moved(self, event):
        if isinstance(event, FileMovedEvent):
            self._handle(event.dest_path)

    def _handle(self, file_path: str):
        """Check extension, wait for stability, then invoke callback."""
        path = Path(file_path)

        # Skip directories
        if path.is_dir():
            return

        # Skip non-video files
        if path.suffix.lower() not in self.extensions:
            logger.debug('Skipping non-video file: %s', path.name)
            return

        # Skip files in the errors subdirectory
        if 'errors' in path.parts:
            return

        logger.info('New file detected: %s', path.name)
        FILES_DETECTED_TOTAL.inc()

        if not self.stability_checker.wait_until_stable(file_path):
            return

        self.callback(file_path)


def start_watcher(
    watch_dir: str,
    extensions: list[str],
    stability_config: dict,
    callback,
) -> Observer:
    """Start watching a directory for new video files.

    Args:
        watch_dir: Directory to watch.
        extensions: List of video file extensions (e.g., ['.mp4', '.mkv']).
        stability_config: Dict with 'check_interval_seconds' and 'min_stable_checks'.
        callback: Function to call with the file path when a stable video is found.

    Returns:
        The running Observer instance.
    """
    checker = StabilityChecker(
        interval=stability_config.get('check_interval_seconds', 5),
        min_checks=stability_config.get('min_stable_checks', 2),
    )

    handler = VideoHandler(extensions, checker, callback)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()

    logger.info('Watching directory: %s', watch_dir)
    return observer
