"""Entry point for the emby-processor pipeline."""

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

from src.emby_client import EmbyClient
from src.log_buffer import get_log_buffer
from src.metadata import MetadataClient
from src.pipeline import Pipeline
from src.queue import QueueDB
from src.token_manager import TokenManager, load_refresh_token
from src.watcher import start_watcher
from src.workers import WorkerManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('emby-processor')

# Initialize log buffer for dashboard access
get_log_buffer()


def load_config() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()

    return {
        'watch_dir': os.getenv('WATCH_DIR', '/watch'),
        'destination_dir': os.getenv('DESTINATION_DIR', '/destination'),
        'unprocessed_dir': os.getenv('UNPROCESSED_DIR', '/watch/unprocessed'),
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
            'user_id': os.getenv('EMBY_USER_ID', ''),
            'library_id': os.getenv('EMBY_LIBRARY_ID', ''),
            'library_path': os.getenv('EMBY_LIBRARY_PATH', '/mnt/media/jpv'),
            'parent_folder_id': os.getenv('EMBY_PARENT_FOLDER_ID', '4'),
            'trigger_scan': os.getenv('EMBY_TRIGGER_SCAN', 'true').lower() == 'true',
            'scan_wait_seconds': os.getenv('EMBY_SCAN_WAIT_SECONDS', '10'),
            'scan_retry_delays': [
                int(x) for x in os.getenv('EMBY_SCAN_RETRY_DELAYS', '2,4,8,16,32,64').split(',')
            ],
        },
        'stability': {
            'check_interval_seconds': int(os.getenv('STABILITY_CHECK_INTERVAL', '5')),
            'min_stable_checks': int(os.getenv('STABILITY_MIN_CHECKS', '2')),
        },
        'database': {
            'url': os.getenv('DATABASE_URL', ''),
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'dbname': os.getenv('DB_NAME', 'emby_processor'),
            'user': os.getenv('DB_USER', 'emby'),
            'password': os.getenv('DB_PASSWORD', ''),
        },
        'workers': {
            'file_processor_interval': float(os.getenv('WORKER_FILE_PROCESSOR_INTERVAL', '5')),
            'emby_updater_interval': float(os.getenv('WORKER_EMBY_UPDATER_INTERVAL', '10')),
            'retry_interval': float(os.getenv('WORKER_RETRY_INTERVAL', '30')),
        },
    }


def main():
    config = load_config()
    logger.info('Configuration loaded')

    # Init database FIRST (needed by token manager)
    db_config = config.get('database', {})
    database_url = db_config.get('url', '')
    if database_url:
        queue_db = QueueDB(database_url=database_url)
    else:
        queue_db = QueueDB(
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', '5432'),
            dbname=db_config.get('dbname', 'emby_processor'),
            user=db_config.get('user', 'emby'),
            password=db_config.get('password', ''),
        )
    queue_db.initialize()
    logger.info('Queue database initialized')

    # Init token manager for WordPress API auto-refresh
    api_config = config.get('api', {})
    token_manager = None
    refresh_token = load_refresh_token()
    if refresh_token:
        refresh_url = api_config.get('base_url', '').replace(
            '/wp-json/emby/v1', '/wp-json/api-bearer-auth/v1/tokens/refresh'
        )
        token_manager = TokenManager(
            db_pool=queue_db._pool,
            refresh_url=refresh_url,
            refresh_token=refresh_token,
            initial_access_token=api_config.get('token', ''),
        )
        token_manager.initialize()
        logger.info('Token manager initialized')
    else:
        logger.warning('No refresh token found — token auto-refresh disabled')

    # Init metadata client
    metadata_client = MetadataClient(
        base_url=api_config.get('base_url', ''),
        token=api_config.get('token', ''),
        search_order=api_config.get('search_order', ['missav', 'javguru']),
        token_manager=token_manager,
    )

    # Init Emby client
    emby_config = config.get('emby', {})
    emby_client = None
    if emby_config.get('base_url') and emby_config.get('api_key'):
        emby_client = EmbyClient(
            base_url=emby_config['base_url'],
            api_key=emby_config['api_key'],
            parent_folder_id=emby_config.get('parent_folder_id', '4'),
            user_id=emby_config.get('user_id', ''),
            wordpress_token=api_config.get('token', ''),
            retry_delays=emby_config.get('scan_retry_delays'),
            token_manager=token_manager,
        )
        logger.info('Emby client initialized (parent_folder_id=%s)', emby_config.get('parent_folder_id'))

    # Init worker manager
    worker_manager = WorkerManager(
        queue_db=queue_db,
        config=config,
        metadata_client=metadata_client,
        emby_client=emby_client,
    )

    # Define queue callback for watcher: adds files to queue instead of direct processing
    def enqueue_file(file_path: str):
        logger.info('Enqueuing file: %s', file_path)
        queue_db.add(file_path)

    # Scan watch directory on startup for existing files
    watch_dir = config.get('watch_dir', '/watch')
    extensions = config.get('video_extensions', ['.mp4', '.mkv', '.avi', '.wmv'])
    unprocessed_dir = config.get('unprocessed_dir', '/watch/unprocessed')

    logger.info('Scanning watch directory on startup: %s', watch_dir)
    from pathlib import Path
    watch_path = Path(watch_dir)
    if watch_path.exists():
        for ext in extensions:
            for video_file in watch_path.glob(f'*{ext}'):
                # Skip files in subdirectories (like unprocessed/)
                if video_file.parent != watch_path:
                    continue
                file_path_str = str(video_file)
                logger.info('Found existing file: %s', file_path_str)
                enqueue_file(file_path_str)

    # Start watcher (now enqueues files instead of processing directly)
    stability_config = config.get('stability', {})
    observer = start_watcher(
        watch_dir=watch_dir,
        extensions=extensions,
        stability_config=stability_config,
        callback=enqueue_file,
    )

    # Start all worker threads
    worker_manager.start_all()

    # Install signal handlers for graceful shutdown
    worker_manager.install_signal_handlers()

    logger.info('emby-processor running with queue workers. Watching for new files...')

    try:
        # Block until shutdown signal
        worker_manager.wait_for_shutdown()
    finally:
        logger.info('Shutting down...')
        observer.stop()
        observer.join()
        if token_manager:
            token_manager.stop()
        queue_db.close()
        logger.info('Shutdown complete')


if __name__ == '__main__':
    main()
