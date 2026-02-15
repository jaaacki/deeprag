"""PostgreSQL-backed processing queue for the emby-processor pipeline.

Status flow: pending -> processing -> moved -> emby_pending -> completed
Any stage can transition to 'error'. Errors with retry_count < max can be retried.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

VALID_STATUSES = {'pending', 'processing', 'moved', 'emby_pending', 'completed', 'error'}

MAX_RETRIES = 3
RETRY_BACKOFF_MINUTES = [1, 5, 15]  # Backoff per retry attempt


class QueueDB:
    """PostgreSQL queue with connection pooling."""

    def __init__(self, database_url: Optional[str] = None, **kwargs):
        """Initialize the queue database connection pool.

        Args:
            database_url: PostgreSQL connection string (postgres://user:pass@host:port/db).
                          Falls back to individual kwargs or environment variables.
            **kwargs: Individual connection params (host, port, dbname, user, password).
        """
        if database_url:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5, dsn=database_url,
            )
        else:
            conn_params = {
                'host': kwargs.get('host', os.getenv('DB_HOST', 'localhost')),
                'port': kwargs.get('port', os.getenv('DB_PORT', '5432')),
                'dbname': kwargs.get('dbname', os.getenv('DB_NAME', 'emby_processor')),
                'user': kwargs.get('user', os.getenv('DB_USER', 'emby')),
                'password': kwargs.get('password', os.getenv('DB_PASSWORD', '')),
            }
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5, **conn_params,
            )
        logger.info('Queue database connection pool created')

    def _get_conn(self):
        return self._pool.getconn()

    def _put_conn(self, conn):
        self._pool.putconn(conn)

    def close(self):
        """Close the connection pool."""
        self._pool.closeall()
        logger.info('Queue database connection pool closed')

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def initialize(self):
        """Run all migration SQL files to create/update the schema."""
        migrations_dir = Path(__file__).parent.parent / 'migrations'
        migration_files = sorted(migrations_dir.glob('*.sql'))

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for migration_path in migration_files:
                    sql = migration_path.read_text()
                    cur.execute(sql)
                    logger.info('Ran migration: %s', migration_path.name)
            conn.commit()
            logger.info('Queue database schema initialized (%d migrations)', len(migration_files))
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def add(self, file_path: str, movie_code: Optional[str] = None,
            actress: Optional[str] = None, subtitle: Optional[str] = None) -> dict:
        """Add a new file to the processing queue.

        Returns the created row as a dict.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO processing_queue (file_path, movie_code, actress, subtitle)
                       VALUES (%s, %s, %s, %s)
                       RETURNING *""",
                    (file_path, movie_code, actress, subtitle),
                )
                row = cur.fetchone()
            conn.commit()
            logger.info('Queue item added: id=%s file=%s', row['id'], file_path)
            return dict(row)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            logger.warning('File already in queue: %s', file_path)
            return self.get_by_file_path(file_path)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def get(self, item_id: int) -> Optional[dict]:
        """Get a queue item by ID."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SELECT * FROM processing_queue WHERE id = %s', (item_id,))
                row = cur.fetchone()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    def get_by_file_path(self, file_path: str) -> Optional[dict]:
        """Get a queue item by file path."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SELECT * FROM processing_queue WHERE file_path = %s', (file_path,))
                row = cur.fetchone()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    def update_status(self, item_id: int, status: str,
                      error_message: Optional[str] = None,
                      new_path: Optional[str] = None,
                      emby_item_id: Optional[str] = None,
                      metadata_json: Optional[dict] = None) -> Optional[dict]:
        """Update the status and optional fields of a queue item.

        Returns the updated row as a dict, or None if not found.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f'Invalid status: {status}. Must be one of {VALID_STATUSES}')

        fields = ['status = %s']
        values = [status]

        if error_message is not None:
            fields.append('error_message = %s')
            values.append(error_message)

        if new_path is not None:
            fields.append('new_path = %s')
            values.append(new_path)

        if emby_item_id is not None:
            fields.append('emby_item_id = %s')
            values.append(emby_item_id)

        if metadata_json is not None:
            fields.append('metadata_json = %s')
            values.append(json.dumps(metadata_json))

        # On error, increment retry_count and set next_retry_at
        if status == 'error':
            fields.append('retry_count = retry_count + 1')

        values.append(item_id)

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""UPDATE processing_queue
                        SET {', '.join(fields)}
                        WHERE id = %s
                        RETURNING *""",
                    values,
                )
                row = cur.fetchone()

                # Set next_retry_at based on new retry_count
                if row and status == 'error' and row['retry_count'] <= MAX_RETRIES:
                    backoff_idx = min(row['retry_count'] - 1, len(RETRY_BACKOFF_MINUTES) - 1)
                    delay = RETRY_BACKOFF_MINUTES[backoff_idx]
                    next_retry = datetime.now(timezone.utc) + timedelta(minutes=delay)
                    cur.execute(
                        """UPDATE processing_queue
                           SET next_retry_at = %s
                           WHERE id = %s
                           RETURNING *""",
                        (next_retry, item_id),
                    )
                    row = cur.fetchone()

            conn.commit()
            if row:
                logger.info('Queue item %s status -> %s', item_id, status)
                return dict(row)
            logger.warning('Queue item %s not found for update', item_id)
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def get_next_pending(self) -> Optional[dict]:
        """Get the oldest pending item and atomically set it to 'processing'.

        Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent access.
        Returns the item dict, or None if no pending items.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """UPDATE processing_queue
                       SET status = 'processing'
                       WHERE id = (
                           SELECT id FROM processing_queue
                           WHERE status = 'pending'
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING *""",
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                logger.info('Claimed pending item: id=%s file=%s', row['id'], row['file_path'])
                return dict(row)
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def get_next_moved(self) -> Optional[dict]:
        """Get the oldest 'moved' item and atomically set it to 'emby_pending'.

        Returns the item dict, or None if no moved items.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """UPDATE processing_queue
                       SET status = 'emby_pending'
                       WHERE id = (
                           SELECT id FROM processing_queue
                           WHERE status = 'moved'
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING *""",
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                logger.info('Claimed moved item: id=%s file=%s', row['id'], row['file_path'])
                return dict(row)
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def get_retryable_errors(self, limit: int = 10) -> list[dict]:
        """Get error items that are eligible for retry.

        Returns items where retry_count <= MAX_RETRIES and next_retry_at <= now.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM processing_queue
                       WHERE status = 'error'
                         AND retry_count <= %s
                         AND next_retry_at <= NOW()
                       ORDER BY next_retry_at ASC
                       LIMIT %s""",
                    (MAX_RETRIES, limit),
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            self._put_conn(conn)

    def reset_for_retry(self, item_id: int) -> Optional[dict]:
        """Reset an error item for retry.

        If the file was already moved (new_path is set), resets to 'moved'
        so it resumes at the Emby update stage. Otherwise resets to 'pending'
        for the full pipeline.

        Returns the updated row, or None if not found or not eligible.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Check if the file was already moved
                cur.execute(
                    'SELECT new_path FROM processing_queue WHERE id = %s AND status = %s',
                    (item_id, 'error'),
                )
                check = cur.fetchone()
                if not check:
                    return None

                resume_status = 'moved' if check['new_path'] else 'pending'

                cur.execute(
                    """UPDATE processing_queue
                       SET status = %s, error_message = NULL, next_retry_at = NULL
                       WHERE id = %s AND status = 'error' AND retry_count <= %s
                       RETURNING *""",
                    (resume_status, item_id, MAX_RETRIES),
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                logger.info('Reset item %s to %s for retry (attempt %s)', item_id, resume_status, row['retry_count'])
                return dict(row)
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def list_by_status(self, status: str, limit: int = 50) -> list[dict]:
        """List queue items filtered by status."""
        if status not in VALID_STATUSES:
            raise ValueError(f'Invalid status: {status}. Must be one of {VALID_STATUSES}')

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM processing_queue
                       WHERE status = %s
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (status, limit),
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            self._put_conn(conn)

    def count_by_status(self) -> dict[str, int]:
        """Get counts of items grouped by status."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT status, COUNT(*) as count
                       FROM processing_queue
                       GROUP BY status
                       ORDER BY status""",
                )
                rows = cur.fetchall()
            return {row['status']: row['count'] for row in rows}
        finally:
            self._put_conn(conn)

    def delete(self, item_id: int) -> bool:
        """Delete a queue item by ID. Returns True if deleted."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM processing_queue WHERE id = %s', (item_id,))
                deleted = cur.rowcount > 0
            conn.commit()
            if deleted:
                logger.info('Deleted queue item %s', item_id)
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # Download job operations
    # ------------------------------------------------------------------

    def add_download(self, url: str, filename: Optional[str] = None) -> dict:
        """Add a new download job. Returns the created row as a dict."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO download_jobs (url, filename)
                       VALUES (%s, %s)
                       RETURNING *""",
                    (url, filename),
                )
                row = cur.fetchone()
            conn.commit()
            logger.info('Download job added: id=%s url=%s', row['id'], url)
            return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def get_download(self, download_id: int) -> Optional[dict]:
        """Get a download job by ID."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SELECT * FROM download_jobs WHERE id = %s', (download_id,))
                row = cur.fetchone()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    def list_downloads(self, limit: int = 20) -> list[dict]:
        """List recent download jobs, newest first."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM download_jobs
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            self._put_conn(conn)

    def update_download_status(self, download_id: int, *,
                               status: Optional[str] = None,
                               error: Optional[str] = None,
                               output_tail: Optional[list] = None,
                               started_at: Optional[datetime] = None,
                               finished_at: Optional[datetime] = None) -> Optional[dict]:
        """Update a download job's status and fields. Returns updated row."""
        fields = []
        values = []

        if status is not None:
            fields.append('status = %s')
            values.append(status)
        if error is not None:
            fields.append('error = %s')
            values.append(error)
        if output_tail is not None:
            fields.append('output_tail = %s')
            values.append(json.dumps(output_tail))
        if started_at is not None:
            fields.append('started_at = %s')
            values.append(started_at)
        if finished_at is not None:
            fields.append('finished_at = %s')
            values.append(finished_at)

        if not fields:
            return self.get_download(download_id)

        values.append(download_id)

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""UPDATE download_jobs
                        SET {', '.join(fields)}
                        WHERE id = %s
                        RETURNING *""",
                    values,
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                return dict(row)
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def cleanup_old_downloads(self, older_than_days: int = 30) -> int:
        """Delete completed/failed downloads older than N days. Returns count deleted."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM download_jobs
                       WHERE status IN ('completed', 'failed')
                         AND created_at < NOW() - INTERVAL '1 day' * %s
                       RETURNING id""",
                    (older_than_days,),
                )
                deleted = cur.rowcount
            conn.commit()
            if deleted:
                logger.info('Cleaned up %d old download jobs', deleted)
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def recover_stale_downloads(self) -> int:
        """Mark any 'downloading' jobs as 'failed' (stale from container restart).
        Returns count of recovered jobs."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE download_jobs
                       SET status = 'failed',
                           error = 'Container restarted during download',
                           finished_at = NOW()
                       WHERE status IN ('queued', 'downloading')""",
                )
                recovered = cur.rowcount
            conn.commit()
            if recovered:
                logger.info('Recovered %d stale download jobs', recovered)
            return recovered
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)
