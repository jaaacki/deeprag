"""Entry point for the emby-processor pipeline."""

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

from src.emby_client import EmbyClient
from src.metadata import MetadataClient
from src.pipeline import Pipeline
from src.watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('emby-processor')


def load_config() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()

    return {
        'watch_dir': os.getenv('WATCH_DIR', '/watch'),
        'destination_dir': os.getenv('DESTINATION_DIR', '/destination'),
        'error_dir': os.getenv('ERROR_DIR', '/watch/errors'),
        'video_extensions': os.getenv('VIDEO_EXTENSIONS', '.mp4,.mkv,.avi,.wmv').split(','),
        'api': {
            'base_url': os.getenv('API_BASE_URL', ''),
            'token': os.getenv('API_TOKEN', ''),
            'search_order': os.getenv('API_SEARCH_ORDER', 'missav,javguru').split(','),
        },
        'emby': {
            'base_url': os.getenv('EMBY_BASE_URL', ''),
            'api_key': os.getenv('EMBY_API_KEY', ''),
            'server_id': os.getenv('EMBY_SERVER_ID', ''),
            'library_id': os.getenv('EMBY_LIBRARY_ID', ''),
            'trigger_scan': os.getenv('EMBY_TRIGGER_SCAN', 'true').lower() == 'true',
        },
        'stability': {
            'check_interval_seconds': int(os.getenv('STABILITY_CHECK_INTERVAL', '5')),
            'min_stable_checks': int(os.getenv('STABILITY_MIN_CHECKS', '2')),
        },
    }


def main():
    config = load_config()
    logger.info('Configuration loaded')

    # Init metadata client
    api_config = config.get('api', {})
    client = MetadataClient(
        base_url=api_config.get('base_url', ''),
        token=api_config.get('token', ''),
        search_order=api_config.get('search_order', ['missav', 'javguru']),
    )

    # Init Emby client
    emby_config = config.get('emby', {})
    emby_client = None
    if emby_config.get('base_url') and emby_config.get('api_key'):
        emby_client = EmbyClient(
            base_url=emby_config['base_url'],
            api_key=emby_config['api_key'],
        )
        logger.info('Emby client initialized')

    # Init pipeline
    pipeline = Pipeline(config, client, emby_client)

    # Start watcher
    stability_config = config.get('stability', {})
    observer = start_watcher(
        watch_dir=config.get('watch_dir', '/watch'),
        extensions=config.get('video_extensions', ['.mp4', '.mkv', '.avi', '.wmv']),
        stability_config=stability_config,
        callback=pipeline.process,
    )

    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info('Shutting down...')
        observer.stop()
        observer.join()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info('emby-processor running. Watching for new files...')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == '__main__':
    main()
