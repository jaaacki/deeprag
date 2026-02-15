"""Tests for the worker processes."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.workers import (
    BaseWorker,
    FileProcessorWorker,
    EmbyUpdaterWorker,
    RetryHandler,
    WorkerManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_queue_item(**overrides):
    """Create a fake queue item dict with sensible defaults."""
    item = {
        'id': 1,
        'file_path': '/watch/SONE-760.mp4',
        'movie_code': None,
        'actress': None,
        'subtitle': None,
        'status': 'pending',
        'error_message': None,
        'new_path': None,
        'emby_item_id': None,
        'metadata_json': None,
        'retry_count': 0,
        'next_retry_at': None,
    }
    item.update(overrides)
    return item


def make_metadata(**overrides):
    """Create a fake metadata response."""
    meta = {
        'movie_code': 'SONE-760',
        'title': 'The Same Commute Train',
        'actress': ['Ruri Saijo'],
        'genre': ['Drama'],
        'release_date': '2026-01-15',
        'label': 'S1 NO.1 STYLE',
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# BaseWorker tests
# ---------------------------------------------------------------------------

class TestBaseWorker:
    def test_start_and_stop(self):
        """Worker thread starts and stops cleanly."""
        queue_db = MagicMock()

        class TestWorker(BaseWorker):
            def process_one(self):
                return False

        worker = TestWorker(queue_db, poll_interval=0.1)
        worker.start()
        assert worker.is_running

        worker.stop(timeout=2.0)
        assert not worker.is_running

    def test_process_one_called_in_loop(self):
        """process_one is called repeatedly while worker is running."""
        queue_db = MagicMock()
        call_count = 0

        class CountWorker(BaseWorker):
            def process_one(self):
                nonlocal call_count
                call_count += 1
                if call_count >= 3:
                    self._stop_event.set()
                return True

        worker = CountWorker(queue_db, poll_interval=0.01)
        worker.start()
        worker._thread.join(timeout=2.0)
        assert call_count >= 3

    def test_exception_in_process_one_does_not_crash(self):
        """Worker survives exceptions in process_one."""
        queue_db = MagicMock()
        call_count = 0

        class CrashWorker(BaseWorker):
            def process_one(self):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise RuntimeError('boom')
                self._stop_event.set()
                return False

        worker = CrashWorker(queue_db, poll_interval=0.01)
        worker.start()
        worker._thread.join(timeout=5.0)
        assert call_count >= 3

    def test_name_property(self):
        queue_db = MagicMock()

        class MyWorker(BaseWorker):
            def process_one(self):
                return False

        assert MyWorker(queue_db).name == 'MyWorker'


# ---------------------------------------------------------------------------
# FileProcessorWorker tests
# ---------------------------------------------------------------------------

class TestFileProcessorWorker:
    def _make_worker(self, queue_db=None, metadata_client=None):
        queue_db = queue_db or MagicMock()
        metadata_client = metadata_client or MagicMock()
        config = {
            'error_dir': '/watch/errors',
            'destination_dir': '/destination',
        }
        return FileProcessorWorker(
            queue_db=queue_db,
            config=config,
            metadata_client=metadata_client,
            poll_interval=0.1,
        )

    def test_no_pending_items_returns_false(self):
        """Returns False when no pending items in queue."""
        queue_db = MagicMock()
        queue_db.get_next_pending.return_value = None
        worker = self._make_worker(queue_db=queue_db)

        assert worker.process_one() is False

    def test_no_movie_code_moves_to_error(self):
        """Files without a movie code are moved to errors."""
        queue_db = MagicMock()
        queue_db.get_next_pending.return_value = make_queue_item(
            file_path='/watch/random_file.mp4',
        )

        worker = self._make_worker(queue_db=queue_db)
        with patch.object(worker, '_move_to_errors') as mock_move:
            result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'
        assert 'No movie code' in args[1]['error_message']

    def test_no_metadata_moves_to_error(self):
        """Files with no metadata result are moved to errors."""
        queue_db = MagicMock()
        queue_db.get_next_pending.return_value = make_queue_item(
            file_path='/watch/SONE-760.mp4',
        )

        metadata_client = MagicMock()
        metadata_client.search.return_value = None

        worker = self._make_worker(queue_db=queue_db, metadata_client=metadata_client)
        with patch.object(worker, '_move_to_errors'):
            result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'
        assert 'No metadata' in args[1]['error_message']

    @patch('src.workers.move_file', return_value='/destination/Ruri Saijo/Ruri Saijo - [No Sub] SONE-760 The Same Commute Train.mp4')
    def test_successful_processing_marks_moved(self, mock_move_file):
        """Successful file processing marks item as moved."""
        queue_db = MagicMock()
        queue_db.get_next_pending.return_value = make_queue_item(
            file_path='/watch/SONE-760.mp4',
        )
        # Mock the connection for the field update
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        queue_db._get_conn.return_value = mock_conn

        metadata_client = MagicMock()
        metadata_client.search.return_value = make_metadata()

        worker = self._make_worker(queue_db=queue_db, metadata_client=metadata_client)
        result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'moved'
        assert args[1]['new_path'] is not None
        assert args[1]['metadata_json'] is not None

    @patch('src.workers.move_file', side_effect=OSError('disk full'))
    def test_move_failure_marks_error(self, mock_move_file):
        """OSError during move marks item as error."""
        queue_db = MagicMock()
        queue_db.get_next_pending.return_value = make_queue_item(
            file_path='/watch/SONE-760.mp4',
        )

        metadata_client = MagicMock()
        metadata_client.search.return_value = make_metadata()

        worker = self._make_worker(queue_db=queue_db, metadata_client=metadata_client)
        result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'
        assert 'disk full' in args[1]['error_message']


# ---------------------------------------------------------------------------
# EmbyUpdaterWorker tests
# ---------------------------------------------------------------------------

class TestEmbyUpdaterWorker:
    def _make_worker(self, queue_db=None, emby_client=None, config=None):
        queue_db = queue_db or MagicMock()
        emby_client = emby_client or MagicMock()
        config = config or {
            'emby': {'parent_folder_id': '4'},
        }
        return EmbyUpdaterWorker(
            queue_db=queue_db,
            config=config,
            emby_client=emby_client,
            poll_interval=0.1,
        )

    def test_no_emby_client_returns_false(self):
        """Returns False when no Emby client is configured."""
        worker = EmbyUpdaterWorker(
            queue_db=MagicMock(),
            config={'emby': {}},
            emby_client=None,
        )
        assert worker.process_one() is False

    def test_no_moved_items_returns_false(self):
        """Returns False when no moved items in queue."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = None
        worker = self._make_worker(queue_db=queue_db)

        assert worker.process_one() is False

    def test_scan_failure_marks_error(self):
        """Failed Emby scan marks item as error."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = False

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        emby_client.scan_library_by_id.assert_called_once_with('4')
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'
        assert 'scan failed' in args[1]['error_message']

    def test_uses_parent_folder_id_for_scan(self):
        """Scan uses parent_folder_id, not library_id."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=make_metadata(),
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        config = {'emby': {'parent_folder_id': '42'}}
        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client, config=config)
        worker.process_one()

        emby_client.scan_library_by_id.assert_called_once_with('42')

    def test_falls_back_to_full_scan_without_parent_folder_id(self):
        """Without parent_folder_id, falls back to full library scan."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=make_metadata(),
        )

        emby_client = MagicMock()
        emby_client.trigger_library_scan.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        config = {'emby': {'parent_folder_id': ''}}
        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client, config=config)
        worker.process_one()

        emby_client.trigger_library_scan.assert_called_once()
        emby_client.scan_library_by_id.assert_not_called()

    def test_item_not_found_in_emby_marks_error(self):
        """When Emby can't find the item after retries, marks as error."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = None

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        emby_client.get_item_by_path_with_retry.assert_called_once()
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'

    def test_successful_update_marks_completed(self):
        """Successful Emby update marks item as completed."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=make_metadata(),
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'completed'
        assert args[1]['emby_item_id'] == 'emby123'

    def test_metadata_update_failure_marks_error(self):
        """Failed metadata update marks item as error."""
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=make_metadata(),
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = False

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        queue_db.update_status.assert_called_once()
        args = queue_db.update_status.call_args
        assert args[0][1] == 'error'
        assert args[1]['emby_item_id'] == 'emby123'

    def test_image_upload_after_metadata_update(self):
        """Images are uploaded after successful metadata update."""
        meta = make_metadata(raw_image_url='https://example.com/image.jpg')
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=meta,
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        emby_client.upload_item_images.assert_called_once_with('emby123', 'https://example.com/image.jpg')
        # Should still mark completed
        args = queue_db.update_status.call_args
        assert args[0][1] == 'completed'

    def test_image_cropped_preferred_over_raw(self):
        """image_cropped is used preferentially over raw_image_url."""
        meta = make_metadata(
            image_cropped='https://example.com/cropped.jpg',
            raw_image_url='https://example.com/raw.jpg',
        )
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=meta,
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        worker.process_one()

        emby_client.upload_item_images.assert_called_once_with('emby123', 'https://example.com/cropped.jpg')

    def test_image_upload_failure_does_not_block_completion(self):
        """Image upload failure is best-effort; item still marked completed."""
        meta = make_metadata(raw_image_url='https://example.com/image.jpg')
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=meta,
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True
        emby_client.upload_item_images.side_effect = Exception('network error')

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        args = queue_db.update_status.call_args
        assert args[0][1] == 'completed'

    def test_metadata_json_as_string_is_parsed(self):
        """metadata_json stored as a string is parsed correctly."""
        meta = make_metadata()
        queue_db = MagicMock()
        queue_db.get_next_moved.return_value = make_queue_item(
            status='emby_pending',
            new_path='/destination/Ruri Saijo/file.mp4',
            metadata_json=json.dumps(meta),
        )

        emby_client = MagicMock()
        emby_client.scan_library_by_id.return_value = True
        emby_client.get_item_by_path_with_retry.return_value = {'Id': 'emby123'}
        emby_client.update_item_metadata.return_value = True

        worker = self._make_worker(queue_db=queue_db, emby_client=emby_client)
        result = worker.process_one()

        assert result is True
        emby_client.update_item_metadata.assert_called_once_with('emby123', meta)


# ---------------------------------------------------------------------------
# RetryHandler tests
# ---------------------------------------------------------------------------

class TestRetryHandler:
    def test_no_retryable_items_returns_false(self):
        queue_db = MagicMock()
        queue_db.get_retryable_errors.return_value = []

        handler = RetryHandler(queue_db, poll_interval=0.1)
        assert handler.process_one() is False

    def test_retries_eligible_items(self):
        """Resets all retryable items back to pending."""
        queue_db = MagicMock()
        queue_db.get_retryable_errors.return_value = [
            make_queue_item(id=1, status='error', retry_count=1),
            make_queue_item(id=2, status='error', retry_count=2),
        ]

        handler = RetryHandler(queue_db, poll_interval=0.1)
        result = handler.process_one()

        assert result is True
        assert queue_db.reset_for_retry.call_count == 2
        queue_db.reset_for_retry.assert_any_call(1)
        queue_db.reset_for_retry.assert_any_call(2)


# ---------------------------------------------------------------------------
# WorkerManager tests
# ---------------------------------------------------------------------------

class TestWorkerManager:
    def _make_manager(self):
        queue_db = MagicMock()
        config = {
            'error_dir': '/watch/errors',
            'destination_dir': '/destination',
            'emby': {'parent_folder_id': '4'},
            'workers': {
                'file_processor_interval': 0.1,
                'emby_updater_interval': 0.1,
                'retry_interval': 0.1,
            },
        }
        metadata_client = MagicMock()
        emby_client = MagicMock()

        return WorkerManager(
            queue_db=queue_db,
            config=config,
            metadata_client=metadata_client,
            emby_client=emby_client,
        )

    def test_start_and_stop_all(self):
        """All workers start and stop cleanly."""
        manager = self._make_manager()
        manager.start_all()

        assert manager.file_processor.is_running
        assert manager.emby_updater.is_running
        assert manager.retry_handler.is_running

        manager.stop_all(timeout=2.0)

        assert not manager.file_processor.is_running
        assert not manager.emby_updater.is_running
        assert not manager.retry_handler.is_running

    def test_shutdown_event_stops_workers(self):
        """Setting shutdown event causes wait_for_shutdown to complete."""
        manager = self._make_manager()
        manager.start_all()

        # Trigger shutdown after a short delay
        def trigger():
            time.sleep(0.2)
            manager.shutdown_event.set()

        t = threading.Thread(target=trigger)
        t.start()

        manager.wait_for_shutdown()
        t.join()

        assert not manager.file_processor.is_running
        assert not manager.emby_updater.is_running
        assert not manager.retry_handler.is_running
