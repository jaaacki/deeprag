"""Tests for the PostgreSQL queue module.

Uses a real PostgreSQL database for integration tests.
Set DATABASE_URL env var or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD.
Falls back to localhost defaults for local development.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

# Skip all tests if psycopg2 is not installed
psycopg2 = pytest.importorskip('psycopg2')

from src.queue import QueueDB, VALID_STATUSES, MAX_RETRIES


@pytest.fixture
def db():
    """Create a QueueDB instance connected to the test database."""
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        queue = QueueDB(database_url=database_url)
    else:
        queue = QueueDB(
            host=os.getenv('DB_HOST', 'localhost'),
            port=os.getenv('DB_PORT', '5432'),
            dbname=os.getenv('DB_NAME', 'emby_processor_test'),
            user=os.getenv('DB_USER', 'emby'),
            password=os.getenv('DB_PASSWORD', 'emby'),
        )

    # Initialize schema
    queue.initialize()

    # Clean the table before each test
    conn = queue._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM processing_queue')
        conn.commit()
    finally:
        queue._put_conn(conn)

    yield queue
    queue.close()


class TestQueueAdd:
    """Tests for add()."""

    def test_add_basic(self, db):
        row = db.add('/watch/SONE-760.mp4')
        assert row['file_path'] == '/watch/SONE-760.mp4'
        assert row['status'] == 'pending'
        assert row['retry_count'] == 0
        assert row['id'] is not None

    def test_add_with_metadata(self, db):
        row = db.add(
            file_path='/watch/JUR-589.mp4',
            movie_code='JUR-589',
            actress='Test Actress',
            subtitle='English Sub',
        )
        assert row['movie_code'] == 'JUR-589'
        assert row['actress'] == 'Test Actress'
        assert row['subtitle'] == 'English Sub'

    def test_add_duplicate_returns_existing(self, db):
        row1 = db.add('/watch/SONE-760.mp4')
        row2 = db.add('/watch/SONE-760.mp4')
        assert row1['id'] == row2['id']


class TestQueueGet:
    """Tests for get() and get_by_file_path()."""

    def test_get_by_id(self, db):
        added = db.add('/watch/SONE-760.mp4')
        fetched = db.get(added['id'])
        assert fetched['file_path'] == '/watch/SONE-760.mp4'

    def test_get_nonexistent(self, db):
        assert db.get(99999) is None

    def test_get_by_file_path(self, db):
        db.add('/watch/SONE-760.mp4', movie_code='SONE-760')
        fetched = db.get_by_file_path('/watch/SONE-760.mp4')
        assert fetched['movie_code'] == 'SONE-760'

    def test_get_by_file_path_nonexistent(self, db):
        assert db.get_by_file_path('/nonexistent.mp4') is None


class TestUpdateStatus:
    """Tests for update_status()."""

    def test_update_to_processing(self, db):
        row = db.add('/watch/SONE-760.mp4')
        updated = db.update_status(row['id'], 'processing')
        assert updated['status'] == 'processing'

    def test_update_to_moved_with_new_path(self, db):
        row = db.add('/watch/SONE-760.mp4')
        updated = db.update_status(
            row['id'], 'moved',
            new_path='/destination/Actress/SONE-760.mp4',
        )
        assert updated['status'] == 'moved'
        assert updated['new_path'] == '/destination/Actress/SONE-760.mp4'

    def test_update_to_error_increments_retry(self, db):
        row = db.add('/watch/SONE-760.mp4')
        updated = db.update_status(row['id'], 'error', error_message='Connection timeout')
        assert updated['status'] == 'error'
        assert updated['error_message'] == 'Connection timeout'
        assert updated['retry_count'] == 1
        assert updated['next_retry_at'] is not None

    def test_update_with_metadata_json(self, db):
        row = db.add('/watch/SONE-760.mp4')
        metadata = {'title': 'Test Title', 'actress': ['Test']}
        updated = db.update_status(row['id'], 'processing', metadata_json=metadata)
        assert updated['metadata_json'] == metadata

    def test_update_with_emby_item_id(self, db):
        row = db.add('/watch/SONE-760.mp4')
        updated = db.update_status(row['id'], 'emby_pending', emby_item_id='12345')
        assert updated['emby_item_id'] == '12345'

    def test_update_nonexistent(self, db):
        assert db.update_status(99999, 'processing') is None

    def test_invalid_status_raises(self, db):
        row = db.add('/watch/SONE-760.mp4')
        with pytest.raises(ValueError, match='Invalid status'):
            db.update_status(row['id'], 'invalid_status')

    def test_full_status_flow(self, db):
        """Test the complete happy path: pending -> processing -> moved -> emby_pending -> completed."""
        row = db.add('/watch/SONE-760.mp4', movie_code='SONE-760')

        row = db.update_status(row['id'], 'processing')
        assert row['status'] == 'processing'

        row = db.update_status(row['id'], 'moved', new_path='/dest/Actress/SONE-760.mp4')
        assert row['status'] == 'moved'

        row = db.update_status(row['id'], 'emby_pending', emby_item_id='456')
        assert row['status'] == 'emby_pending'

        row = db.update_status(row['id'], 'completed')
        assert row['status'] == 'completed'


class TestGetNextPending:
    """Tests for get_next_pending()."""

    def test_claims_oldest_pending(self, db):
        db.add('/watch/first.mp4')
        time.sleep(0.01)  # Ensure ordering
        db.add('/watch/second.mp4')

        claimed = db.get_next_pending()
        assert claimed['file_path'] == '/watch/first.mp4'
        assert claimed['status'] == 'processing'

    def test_returns_none_when_empty(self, db):
        assert db.get_next_pending() is None

    def test_skips_non_pending(self, db):
        row = db.add('/watch/SONE-760.mp4')
        db.update_status(row['id'], 'processing')
        assert db.get_next_pending() is None


class TestGetNextMoved:
    """Tests for get_next_moved()."""

    def test_claims_oldest_moved(self, db):
        r1 = db.add('/watch/first.mp4')
        time.sleep(0.01)
        r2 = db.add('/watch/second.mp4')
        db.update_status(r1['id'], 'processing')
        db.update_status(r1['id'], 'moved', new_path='/dest/first.mp4')
        db.update_status(r2['id'], 'processing')
        db.update_status(r2['id'], 'moved', new_path='/dest/second.mp4')

        claimed = db.get_next_moved()
        assert claimed['file_path'] == '/watch/first.mp4'
        assert claimed['status'] == 'emby_pending'

    def test_returns_none_when_no_moved(self, db):
        db.add('/watch/SONE-760.mp4')
        assert db.get_next_moved() is None


class TestRetryableErrors:
    """Tests for get_retryable_errors() and reset_for_retry()."""

    def test_get_retryable_errors(self, db):
        row = db.add('/watch/SONE-760.mp4')
        db.update_status(row['id'], 'error', error_message='timeout')

        # Manually set next_retry_at to the past so it's retryable now
        conn = db._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE processing_queue SET next_retry_at = NOW() - INTERVAL '1 minute' WHERE id = %s",
                    (row['id'],),
                )
            conn.commit()
        finally:
            db._put_conn(conn)

        errors = db.get_retryable_errors()
        assert len(errors) == 1
        assert errors[0]['id'] == row['id']

    def test_excludes_max_retries(self, db):
        row = db.add('/watch/SONE-760.mp4')
        # Exceed max retries
        for _ in range(MAX_RETRIES + 1):
            db.update_status(row['id'], 'error', error_message='timeout')

        conn = db._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE processing_queue SET next_retry_at = NOW() - INTERVAL '1 minute' WHERE id = %s",
                    (row['id'],),
                )
            conn.commit()
        finally:
            db._put_conn(conn)

        errors = db.get_retryable_errors()
        assert len(errors) == 0

    def test_reset_for_retry(self, db):
        row = db.add('/watch/SONE-760.mp4')
        db.update_status(row['id'], 'error', error_message='timeout')
        reset = db.reset_for_retry(row['id'])
        assert reset['status'] == 'pending'
        assert reset['error_message'] is None
        assert reset['next_retry_at'] is None

    def test_reset_nonexistent(self, db):
        assert db.reset_for_retry(99999) is None


class TestListAndCount:
    """Tests for list_by_status() and count_by_status()."""

    def test_list_by_status(self, db):
        db.add('/watch/a.mp4')
        db.add('/watch/b.mp4')
        r3 = db.add('/watch/c.mp4')
        db.update_status(r3['id'], 'processing')

        pending = db.list_by_status('pending')
        assert len(pending) == 2

    def test_list_invalid_status_raises(self, db):
        with pytest.raises(ValueError, match='Invalid status'):
            db.list_by_status('bogus')

    def test_count_by_status(self, db):
        db.add('/watch/a.mp4')
        db.add('/watch/b.mp4')
        r3 = db.add('/watch/c.mp4')
        db.update_status(r3['id'], 'processing')

        counts = db.count_by_status()
        assert counts.get('pending', 0) == 2
        assert counts.get('processing', 0) == 1


class TestDelete:
    """Tests for delete()."""

    def test_delete_existing(self, db):
        row = db.add('/watch/SONE-760.mp4')
        assert db.delete(row['id']) is True
        assert db.get(row['id']) is None

    def test_delete_nonexistent(self, db):
        assert db.delete(99999) is False
