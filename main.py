"""Entry point for the emby-processor pipeline."""

import logging
import signal
import sys
import time

import yaml

from src.metadata import MetadataClient
from src.pipeline import Pipeline
from src.watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('emby-processor')


def load_config(path: str = 'config.yaml') -> dict:
    """Load configuration from YAML file."""
    with open(path, 'r') as f:
        return yaml.safe_load(f)


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

    # Init pipeline
    pipeline = Pipeline(config, client)

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
