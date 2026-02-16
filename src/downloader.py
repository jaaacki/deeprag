"""yt-dlp download manager using docker exec to trigger downloads.

Persists jobs to PostgreSQL via QueueDB. Keeps in-memory buffer only for
active downloads (real-time output between DB flushes).
"""

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 1800  # 30 minutes
DB_FLUSH_INTERVAL = 5  # seconds between output_tail DB writes


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


def _row_to_dict(row: dict) -> dict:
    """Convert a DB row to the API-friendly dict format."""
    def _fmt(val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        return val

    output_tail = row.get('output_tail') or []
    return {
        "id": row['id'],
        "url": row['url'],
        "filename": row.get('filename'),
        "status": row['status'],
        "created_at": _fmt(row.get('created_at')),
        "started_at": _fmt(row.get('started_at')),
        "finished_at": _fmt(row.get('finished_at')),
        "error": row.get('error'),
        "output_tail": output_tail[-20:] if output_tail else [],
    }


class DownloadManager:
    def __init__(self, queue_db):
        self._queue_db = queue_db
        # In-memory buffer: only for active downloads (real-time output between DB flushes)
        self._active_output: dict[int, list[str]] = {}
        self._active_procs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._container_name = os.getenv("YTDLP_CONTAINER_NAME", "ytdlp")

        # Recover stale jobs from previous container run
        recovered = self._queue_db.recover_stale_downloads()
        if recovered:
            logger.info(f"[Download] Recovered {recovered} stale download jobs on startup")

    def submit(self, url: str, filename: Optional[str] = None) -> dict:
        """Submit a download job. Returns the job dict with DB id."""
        row = self._queue_db.add_download(url, filename)
        job_id = row['id']

        with self._lock:
            self._active_output[job_id] = []

        thread = threading.Thread(target=self._run_download, args=(job_id, url, filename), daemon=True)
        thread.start()
        logger.info(f"[Download] Submitted job {job_id}: {url} (filename={filename})")
        return _row_to_dict(row)

    def get_job(self, job_id: int) -> Optional[dict]:
        """Get a download job by ID. Merges real-time output for active jobs."""
        row = self._queue_db.get_download(job_id)
        if not row:
            return None
        result = _row_to_dict(row)
        # Overlay real-time output for active downloads
        with self._lock:
            if job_id in self._active_output:
                result['output_tail'] = self._active_output[job_id][-20:]
        return result

    def list_jobs(self, limit: int = 10, offset: int = 0, status: str = None) -> tuple[list[dict], int]:
        """List recent download jobs with pagination. Returns (jobs, total_count)."""
        rows, total = self._queue_db.list_downloads(limit=limit, offset=offset, status=status)
        results = []
        with self._lock:
            for row in rows:
                result = _row_to_dict(row)
                if row['id'] in self._active_output:
                    result['output_tail'] = self._active_output[row['id']][-20:]
                results.append(result)
        return results, total

    def retry(self, job_id: int) -> Optional[dict]:
        """Retry a failed download by resubmitting the same URL/filename. Returns new job or None."""
        row = self._queue_db.get_download(job_id)
        if not row or row['status'] not in ('failed',):
            return None
        return self.submit(row['url'], row.get('filename'))

    def cancel(self, job_id: int) -> bool:
        """Cancel an active download. Returns True if cancelled, False if not active."""
        with self._lock:
            proc = self._active_procs.get(job_id)
        if proc is None:
            # Not actively running — just mark as failed in DB
            row = self._queue_db.get_download(job_id)
            if row and row['status'] in ('queued', 'downloading'):
                self._queue_db.update_download_status(
                    job_id,
                    status='failed',
                    error='Cancelled by user',
                    finished_at=datetime.now(timezone.utc),
                )
                logger.info(f"[Download] Job {job_id} marked as cancelled (no active process)")
                return True
            return False
        # Kill the subprocess
        try:
            proc.kill()
            logger.info(f"[Download] Job {job_id} process killed by user")
        except OSError:
            pass
        # The _run_download thread will handle cleanup and mark as failed
        return True

    def _run_download(self, job_id: int, url: str, filename: Optional[str]):
        """Run the download in a background thread."""
        now = datetime.now(timezone.utc)
        self._queue_db.update_download_status(
            job_id, status='downloading', started_at=now,
        )

        cmd = ["docker", "exec", self._container_name, "bash", "./scripts/downloadWithFileName.sh", url]
        if filename:
            cmd.append(filename)

        logger.info(f"[Download] Job {job_id} starting: {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with self._lock:
                self._active_procs[job_id] = proc

            output_lines = []
            last_flush = time.monotonic()

            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.info(f"[Download:{job_id}] {line}")
                output_lines.append(line)
                # Keep last 50 lines in memory
                if len(output_lines) > 50:
                    output_lines.pop(0)

                with self._lock:
                    self._active_output[job_id] = output_lines.copy()

                # Flush to DB periodically
                if time.monotonic() - last_flush >= DB_FLUSH_INTERVAL:
                    self._queue_db.update_download_status(
                        job_id, output_tail=output_lines[-50:],
                    )
                    last_flush = time.monotonic()

            proc.wait(timeout=DOWNLOAD_TIMEOUT)

            # The shell script uses set -e and the last [[ -f ]] test
            # returns 1 when no subtitle file exists, even though the
            # video downloaded fine. Treat as success if output has "OK:".
            output_has_ok = any(l.strip().startswith("OK:") for l in output_lines)

            if proc.returncode == -9 or proc.returncode == -15:
                # Killed by signal (SIGKILL=-9, SIGTERM=-15) — user cancelled
                logger.info(f"[Download] Job {job_id} was cancelled by user")
                self._queue_db.update_download_status(
                    job_id,
                    status='failed',
                    error='Cancelled by user',
                    output_tail=output_lines[-50:],
                    finished_at=datetime.now(timezone.utc),
                )
            elif proc.returncode == 0 or output_has_ok:
                if proc.returncode != 0:
                    logger.info(f"[Download] Job {job_id} exit code {proc.returncode} but output contains OK — treating as success")
                else:
                    logger.info(f"[Download] Job {job_id} completed successfully")
                self._queue_db.update_download_status(
                    job_id,
                    status='completed',
                    output_tail=output_lines[-50:],
                    finished_at=datetime.now(timezone.utc),
                )
            else:
                error_msg = f"Exit code {proc.returncode}"
                logger.warning(f"[Download] Job {job_id} failed with exit code {proc.returncode}")
                self._queue_db.update_download_status(
                    job_id,
                    status='failed',
                    error=error_msg,
                    output_tail=output_lines[-50:],
                    finished_at=datetime.now(timezone.utc),
                )

        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error(f"[Download] Job {job_id} timed out")
            self._queue_db.update_download_status(
                job_id,
                status='failed',
                error=f"Timed out after {DOWNLOAD_TIMEOUT}s",
                finished_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.exception(f"[Download] Job {job_id} error: {e}")
            self._queue_db.update_download_status(
                job_id,
                status='failed',
                error=str(e),
                finished_at=datetime.now(timezone.utc),
            )
        finally:
            # Remove from active buffers
            with self._lock:
                self._active_output.pop(job_id, None)
                self._active_procs.pop(job_id, None)


# Singleton instance
_manager: Optional[DownloadManager] = None


def get_download_manager(queue_db=None) -> DownloadManager:
    global _manager
    if _manager is None:
        if queue_db is None:
            raise RuntimeError("DownloadManager requires queue_db on first init")
        _manager = DownloadManager(queue_db)
    return _manager
