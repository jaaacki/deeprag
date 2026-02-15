"""yt-dlp download manager using docker exec to trigger downloads."""

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 1800  # 30 minutes
JOB_TTL = 86400  # 24 hours


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadJob:
    id: str
    url: str
    filename: Optional[str]
    status: DownloadStatus = DownloadStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    output_tail: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "output_tail": self.output_tail[-20:],
        }


class DownloadManager:
    def __init__(self):
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        self._container_name = os.getenv("YTDLP_CONTAINER_NAME", "ytdlp")

    def submit(self, url: str, filename: Optional[str] = None) -> DownloadJob:
        job = DownloadJob(id=str(uuid4())[:8], url=url, filename=filename)
        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_old_jobs()

        thread = threading.Thread(target=self._run_download, args=(job,), daemon=True)
        thread.start()
        logger.info(f"[Download] Submitted job {job.id}: {url} (filename={filename})")
        return job

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[DownloadJob]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _run_download(self, job: DownloadJob):
        job.status = DownloadStatus.DOWNLOADING
        job.started_at = datetime.now(timezone.utc)

        cmd = ["docker", "exec", self._container_name, "bash", "./scripts/downloadWithFileName.sh", job.url]
        if job.filename:
            cmd.append(job.filename)

        logger.info(f"[Download] Job {job.id} starting: {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            output_lines = []
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.info(f"[Download:{job.id}] {line}")
                output_lines.append(line)
                # Keep last 50 lines in memory
                if len(output_lines) > 50:
                    output_lines.pop(0)
                job.output_tail = output_lines.copy()

            proc.wait(timeout=DOWNLOAD_TIMEOUT)

            if proc.returncode == 0:
                job.status = DownloadStatus.COMPLETED
                logger.info(f"[Download] Job {job.id} completed successfully")
            else:
                job.status = DownloadStatus.FAILED
                job.error = f"Exit code {proc.returncode}"
                logger.warning(f"[Download] Job {job.id} failed with exit code {proc.returncode}")

        except subprocess.TimeoutExpired:
            proc.kill()
            job.status = DownloadStatus.FAILED
            job.error = f"Timed out after {DOWNLOAD_TIMEOUT}s"
            logger.error(f"[Download] Job {job.id} timed out")
        except Exception as e:
            job.status = DownloadStatus.FAILED
            job.error = str(e)
            logger.exception(f"[Download] Job {job.id} error: {e}")
        finally:
            job.finished_at = datetime.now(timezone.utc)

    def _cleanup_old_jobs(self):
        now = time.time()
        expired = [
            jid for jid, job in self._jobs.items()
            if (now - job.created_at.timestamp()) > JOB_TTL
            and job.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED)
        ]
        for jid in expired:
            del self._jobs[jid]
        if expired:
            logger.info(f"[Download] Cleaned up {len(expired)} old jobs")


# Singleton instance
_manager: Optional[DownloadManager] = None


def get_download_manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager
