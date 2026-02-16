"""FastAPI web dashboard for queue monitoring and manual controls."""

import json
import logging
import os
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .log_buffer import get_log_buffer
from .metrics import DASHBOARD_REQUEST_DURATION, QUEUE_DEPTH, DOWNLOADS_DEPTH
from .queue import QueueDB
from .token_manager import TokenManager, load_refresh_token

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Emby Processor Dashboard",
    description="Queue monitoring and manual controls for emby-processor",
    version="0.5.0",
)

# Path normalization regex for Prometheus labels (avoid cardinality explosion)
_ID_PATTERN = re.compile(r'/\d+')


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request duration for dashboard endpoints."""

    async def dispatch(self, request: Request, call_next):
        # Skip the /metrics endpoint itself to avoid recursion
        if request.url.path == '/metrics':
            return await call_next(request)

        start = _time.monotonic()
        response = await call_next(request)
        duration = _time.monotonic() - start

        # Normalize path: replace numeric IDs with {id}
        endpoint = _ID_PATTERN.sub('/{id}', request.url.path)

        DASHBOARD_REQUEST_DURATION.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=str(response.status_code),
        ).observe(duration)

        return response


# Add CORS middleware (allow all origins for LAN access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add metrics middleware (outermost to capture full request duration)
app.add_middleware(MetricsMiddleware)

# Global QueueDB instance (initialized on startup)
queue_db: Optional[QueueDB] = None

# Global TokenManager instance (initialized on startup)
_token_manager: Optional[TokenManager] = None


def get_queue_db() -> QueueDB:
    """Get or create QueueDB instance."""
    global queue_db
    if queue_db is None:
        # Load database config from environment
        database_url = os.getenv('DATABASE_URL', '')
        if database_url:
            queue_db = QueueDB(database_url=database_url)
        else:
            queue_db = QueueDB(
                host=os.getenv('DB_HOST', 'localhost'),
                port=os.getenv('DB_PORT', '5432'),
                dbname=os.getenv('DB_NAME', 'emby_processor'),
                user=os.getenv('DB_USER', 'emby'),
                password=os.getenv('DB_PASSWORD', ''),
            )
        queue_db.initialize()
    return queue_db


@app.on_event("startup")
async def startup_event():
    """Initialize database connection on startup."""
    # Initialize log buffer FIRST (adds itself to root logger)
    log_buffer = get_log_buffer()

    # Configure root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Set formatter on log buffer
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    log_buffer.setFormatter(formatter)

    # Initialize database
    db = get_queue_db()

    # Initialize download manager with DB access
    from .downloader import get_download_manager
    get_download_manager(queue_db=db)

    # Initialize token manager
    global _token_manager
    refresh_token = load_refresh_token()
    if refresh_token:
        api_base_url = os.getenv('API_BASE_URL', '')
        refresh_url = api_base_url.replace(
            '/wp-json/emby/v1', '/wp-json/api-bearer-auth/v1/tokens/refresh'
        )
        _token_manager = TokenManager(
            db_pool=db._pool,
            refresh_url=refresh_url,
            refresh_token=refresh_token,
            initial_access_token=os.getenv('API_TOKEN', ''),
        )
        _token_manager.initialize()
        logger.info("Token manager initialized in API process")
    else:
        logger.warning("No refresh token found — token auto-refresh disabled in API process")

    logger.info("=== FastAPI dashboard started ===")
    logger.info(f"Log buffer has {len(log_buffer.buffer)} entries")
    logger.info(f"Root logger handlers: {[type(h).__name__ for h in root_logger.handlers]}")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection and token manager on shutdown."""
    global queue_db, _token_manager
    if _token_manager:
        _token_manager.stop()
        _token_manager = None
    if queue_db:
        queue_db.close()
        queue_db = None
    logger.info("FastAPI dashboard shut down")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML page."""
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if not dashboard_path.exists():
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard.html is missing</p>",
            status_code=404,
        )
    return HTMLResponse(content=dashboard_path.read_text())


@app.get("/api/config")
async def get_config():
    """Get frontend configuration (Emby public URL, server ID)."""
    return {
        "emby_public_url": os.getenv('EMBY_PUBLIC_URL', ''),
        "emby_server_id": os.getenv('EMBY_SERVER_ID', ''),
    }


@app.get("/api/health")
async def health():
    """Get system health status."""
    db = get_queue_db()

    # Check database connection
    try:
        conn = db._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        db._put_conn(conn)
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    # TODO: Check worker status (would need IPC or shared state)
    # For now, just return placeholder

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "workers": {
            "FileProcessor": "unknown",
            "EmbyUpdater": "unknown",
            "RetryHandler": "unknown",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Expose Prometheus metrics (multiprocess-safe)."""
    from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
    from prometheus_client.multiprocess import MultiProcessCollector

    # Refresh queue/download gauges from DB before generating output
    _refresh_queue_gauges()

    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/api/metrics-summary")
async def metrics_summary():
    """JSON summary of key metrics for the last 24 hours."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            # Completed in last 24h
            cur.execute("""
                SELECT COUNT(*) FROM processing_queue
                WHERE status = 'completed'
                  AND updated_at >= NOW() - INTERVAL '24 hours'
            """)
            completed_24h = cur.fetchone()[0]

            # Errors in last 24h
            cur.execute("""
                SELECT COUNT(*) FROM processing_queue
                WHERE status = 'error'
                  AND updated_at >= NOW() - INTERVAL '24 hours'
            """)
            errors_24h = cur.fetchone()[0]

            # Average processing time (created_at -> updated_at for completed items in last 24h)
            cur.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)))
                FROM processing_queue
                WHERE status = 'completed'
                  AND updated_at >= NOW() - INTERVAL '24 hours'
            """)
            avg_row = cur.fetchone()[0]
            avg_processing_seconds = round(float(avg_row), 2) if avg_row else 0.0

        total_24h = completed_24h + errors_24h
        error_rate_24h = round(errors_24h / total_24h, 4) if total_24h > 0 else 0.0

        return {
            "completed_24h": completed_24h,
            "errors_24h": errors_24h,
            "avg_processing_seconds": avg_processing_seconds,
            "error_rate_24h": error_rate_24h,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db._put_conn(conn)


def _refresh_queue_gauges():
    """Update queue/download depth gauges from the database."""
    try:
        db = get_queue_db()
        conn = db._get_conn()
        try:
            with conn.cursor() as cur:
                # Queue depth by status
                cur.execute("""
                    SELECT status, COUNT(*) FROM processing_queue GROUP BY status
                """)
                # Reset all known statuses to 0 first
                for s in ('pending', 'processing', 'moved', 'emby_pending', 'completed', 'error'):
                    QUEUE_DEPTH.labels(status=s).set(0)
                for row in cur.fetchall():
                    QUEUE_DEPTH.labels(status=row[0]).set(row[1])

                # Download depth by status
                cur.execute("""
                    SELECT status, COUNT(*) FROM download_jobs GROUP BY status
                """)
                for s in ('queued', 'downloading', 'completed', 'failed'):
                    DOWNLOADS_DEPTH.labels(status=s).set(0)
                for row in cur.fetchall():
                    DOWNLOADS_DEPTH.labels(status=row[0]).set(row[1])
        finally:
            db._put_conn(conn)
    except Exception as e:
        logger.warning('Failed to refresh queue gauges: %s', e)


@app.get("/api/stats")
async def stats():
    """Get queue statistics."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            # Total counts by status
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM processing_queue
                GROUP BY status
            """)
            status_counts = {row[0]: row[1] for row in cur.fetchall()}

            # Total items
            cur.execute("SELECT COUNT(*) FROM processing_queue")
            total = cur.fetchone()[0]

            # Top actresses
            cur.execute("""
                SELECT actress, COUNT(*) as count
                FROM processing_queue
                WHERE actress IS NOT NULL AND status = 'completed'
                GROUP BY actress
                ORDER BY count DESC
                LIMIT 10
            """)
            by_actress = {row[0]: row[1] for row in cur.fetchall()}

        return {
            "total": total,
            "completed": status_counts.get('completed', 0),
            "pending": status_counts.get('pending', 0),
            "processing": status_counts.get('processing', 0),
            "moved": status_counts.get('moved', 0),
            "emby_pending": status_counts.get('emby_pending', 0),
            "error": status_counts.get('error', 0),
            "by_actress": by_actress,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db._put_conn(conn)


@app.get("/api/queue")
async def get_queue(
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search movie code or actress"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Get queue items with filters and pagination."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        # Build query
        where_clauses = []
        params = []

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        if search:
            where_clauses.append("(movie_code ILIKE %s OR actress ILIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Get items
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, file_path, movie_code, actress, subtitle, status,
                       error_message, new_path, emby_item_id, retry_count,
                       created_at, updated_at,
                       (metadata_json IS NOT NULL) as has_metadata
                FROM processing_queue
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])

            items = []
            for row in cur.fetchall():
                items.append({
                    "id": row[0],
                    "file_path": row[1],
                    "movie_code": row[2],
                    "actress": row[3],
                    "subtitle": row[4],
                    "status": row[5],
                    "error_message": row[6],
                    "new_path": row[7],
                    "emby_item_id": row[8],
                    "retry_count": row[9],
                    "created_at": row[10].isoformat() if row[10] else None,
                    "updated_at": row[11].isoformat() if row[11] else None,
                    "has_metadata": bool(row[12]),
                })

            # Get total count
            cur.execute(f"""
                SELECT COUNT(*) FROM processing_queue {where_sql}
            """, params)
            total = cur.fetchone()[0]

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db._put_conn(conn)


@app.get("/api/queue/{item_id}")
async def get_queue_item(item_id: int):
    """Get detailed information for a specific queue item."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, file_path, movie_code, actress, subtitle, status,
                       error_message, new_path, emby_item_id, metadata_json,
                       retry_count, next_retry_at, created_at, updated_at
                FROM processing_queue
                WHERE id = %s
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found")

            # Parse metadata JSON
            metadata_json = row[9]
            if isinstance(metadata_json, str):
                metadata_json = json.loads(metadata_json)

            return {
                "id": row[0],
                "file_path": row[1],
                "movie_code": row[2],
                "actress": row[3],
                "subtitle": row[4],
                "status": row[5],
                "error_message": row[6],
                "new_path": row[7],
                "emby_item_id": row[8],
                "metadata_json": metadata_json,
                "retry_count": row[10],
                "next_retry_at": row[11].isoformat() if row[11] else None,
                "created_at": row[12].isoformat() if row[12] else None,
                "updated_at": row[13].isoformat() if row[13] else None,
            }
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/retry")
async def retry_item(item_id: int):
    """Manually retry a failed queue item."""
    db = get_queue_db()

    # Get item to verify it exists and is in error state
    conn = db._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM processing_queue WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found")

            if row[0] != 'error':
                raise HTTPException(
                    status_code=400,
                    detail=f"Item is not in error state (current: {row[0]})"
                )
    finally:
        db._put_conn(conn)

    # Reset for retry
    db.reset_for_retry(item_id)

    return {
        "success": True,
        "message": f"Item {item_id} reset to pending for retry",
        "item_id": item_id,
    }


@app.post("/api/queue/{item_id}/reprocess-metadata")
async def reprocess_metadata(item_id: int):
    """Re-fetch metadata and update Emby for a completed item."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, new_path FROM processing_queue WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found")

            if row[0] != 'completed':
                raise HTTPException(
                    status_code=400,
                    detail=f"Item must be completed to reprocess metadata (current: {row[0]})"
                )

            if not row[1]:
                raise HTTPException(status_code=400, detail="Item has no new_path (file not moved)")

            # Reset to moved state to trigger EmbyUpdater reprocessing
            cur.execute("""
                UPDATE processing_queue
                SET status = 'moved', updated_at = NOW()
                WHERE id = %s
            """, (item_id,))
            conn.commit()

        return {
            "success": True,
            "message": f"Item {item_id} reset to moved for metadata reprocessing",
            "item_id": item_id,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/actions/extract-code")
async def action_extract_code(item_id: int):
    """Re-extract movie code and subtitle from filename."""
    from .extractor import extract_movie_code, detect_subtitle

    logger.info(f"[API Action] Extract code requested for item {item_id}")
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM processing_queue WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(f"[API Action] Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            file_path = row[0]
            filename = Path(file_path).name
            logger.info(f"[API Action] Extracting from filename: {filename}")

            # Extract code and subtitle
            movie_code = extract_movie_code(filename)
            subtitle = detect_subtitle(filename)

            if not movie_code:
                logger.warning(f"[API Action] No movie code found in: {filename}")
                raise HTTPException(
                    status_code=400,
                    detail=f"No movie code found in filename: {filename}"
                )

            logger.info(f"[API Action] Extracted: {movie_code}, subtitle: {subtitle}")

            # Update database
            cur.execute("""
                UPDATE processing_queue
                SET movie_code = %s, subtitle = %s, updated_at = NOW()
                WHERE id = %s
            """, (movie_code, subtitle, item_id))
            conn.commit()

            logger.info(f"[API Action] Item {item_id} updated with code: {movie_code}")

            return {
                "success": True,
                "message": f"Extracted: {movie_code}" + (f" [{subtitle}]" if subtitle else ""),
                "movie_code": movie_code,
                "subtitle": subtitle,
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(f"[API Action] Failed to extract code for item {item_id}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/actions/fetch-metadata")
async def action_fetch_metadata(
    item_id: int,
    fresh: bool = Query(False, description="Force fresh metadata (bypass cache)")
):
    """Re-fetch metadata from WordPress API."""
    from .metadata import MetadataClient

    fresh_text = " (FORCE FRESH)" if fresh else ""
    logger.info(f"[API Action] Fetch metadata requested for item {item_id}{fresh_text}")
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT movie_code FROM processing_queue WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(f"[API Action] Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            movie_code = row[0]
            if not movie_code:
                logger.warning(f"[API Action] Item {item_id} has no movie code")
                raise HTTPException(
                    status_code=400,
                    detail="No movie code - run extract-code first"
                )

            logger.info(f"[API Action] Fetching metadata for: {movie_code}{fresh_text}")

            # Fetch metadata
            metadata_client = MetadataClient(
                base_url=os.getenv('API_BASE_URL', ''),
                token=os.getenv('API_TOKEN', ''),
                token_manager=_token_manager,
            )

            metadata = metadata_client.search(movie_code, fresh=fresh)
            if not metadata:
                logger.warning(f"[API Action] No metadata found for {movie_code}")
                raise HTTPException(
                    status_code=404,
                    detail=f"No metadata found for {movie_code}"
                )

            actress_list = metadata.get('actress', [])
            actress = actress_list[0] if actress_list else 'Unknown'
            logger.info(f"[API Action] Metadata found: {actress} - {metadata.get('title', '')[:50]}")

            # Update database
            cur.execute("""
                UPDATE processing_queue
                SET metadata_json = %s, updated_at = NOW()
                WHERE id = %s
            """, (json.dumps(metadata), item_id))
            conn.commit()

            logger.info(f"[API Action] Item {item_id} metadata updated")

            title = metadata.get('title', '')[:50] + '...'

            return {
                "success": True,
                "message": f"Fetched metadata: {actress} - {title}",
                "actress": actress,
                "title": metadata.get('title', ''),
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(f"[API Action] Failed to fetch metadata for item {item_id}")
        raise HTTPException(status_code=500, detail=f"Metadata fetch failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/actions/rename-file")
async def action_rename_file(item_id: int):
    """Re-rename and move file using current metadata."""
    from .renamer import build_filename, move_file

    logger.info(f"[API Action] Rename/move file requested for item {item_id}")
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT file_path, movie_code, subtitle, metadata_json
                FROM processing_queue WHERE id = %s
            """, (item_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(f"[API Action] Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            file_path, movie_code, subtitle, metadata_json = row

            if not metadata_json:
                logger.warning(f"[API Action] Item {item_id} has no metadata")
                raise HTTPException(
                    status_code=400,
                    detail="No metadata - run fetch-metadata first"
                )

            # Parse metadata
            if isinstance(metadata_json, str):
                metadata = json.loads(metadata_json)
            else:
                metadata = metadata_json

            # Check if file exists; if not, check unprocessed directory
            if not Path(file_path).exists():
                # Try unprocessed directory as fallback
                watch_dir = os.getenv('WATCH_DIR', '/watch')
                unprocessed_path = Path(watch_dir) / 'unprocessed' / Path(file_path).name
                if unprocessed_path.exists():
                    logger.info(f"[API Action] File found in unprocessed dir: {unprocessed_path}")
                    file_path = str(unprocessed_path)
                else:
                    logger.warning(f"[API Action] File not found: {file_path}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"File not found: {file_path}"
                    )

            # Extract fields
            actress_list = metadata.get('actress', [])
            actress = actress_list[0] if actress_list else 'Unknown'
            title = metadata.get('title', '')
            api_code = metadata.get('movie_code', movie_code)

            actress = actress.title()

            # Remove code from title if present
            if title.upper().startswith(api_code.upper()):
                title = title[len(api_code):].strip()
                if title and title[0] in ['-', ' ']:
                    title = title[1:].strip()
            title = title.title()

            logger.info(f"[API Action] Building filename for: {actress} - {api_code}")

            # Build filename and move
            destination_dir = os.getenv('DESTINATION_DIR', '/destination')
            extension = Path(file_path).suffix
            new_filename = build_filename(actress, subtitle, api_code, title, extension)

            logger.info(f"[API Action] Moving file: {Path(file_path).name} -> {actress}/{new_filename}")
            new_path = move_file(file_path, destination_dir, actress, new_filename)

            # Update database
            cur.execute("""
                UPDATE processing_queue
                SET new_path = %s, status = 'moved', actress = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_path, actress, item_id))
            conn.commit()

            logger.info(f"[API Action] Item {item_id} moved successfully to: {new_path}")

            return {
                "success": True,
                "message": f"Moved to: {actress}/{new_filename[:40]}...",
                "new_path": new_path,
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(f"[API Action] Failed to rename/move file for item {item_id}")
        raise HTTPException(status_code=500, detail=f"File move failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/actions/update-emby")
async def action_update_emby(
    item_id: int,
    fresh: bool = Query(False, description="Force fresh metadata (bypass cache)")
):
    """Re-fetch metadata (optionally fresh) and update Emby."""
    from .metadata import MetadataClient
    from .emby_client import EmbyClient

    fresh_text = " (FORCE FRESH)" if fresh else ""
    logger.info(f"[API Action] Update Emby requested for item {item_id}{fresh_text}")
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT movie_code, emby_item_id, status, new_path
                FROM processing_queue WHERE id = %s
            """, (item_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(f"[API Action] Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            movie_code, emby_item_id, status, new_path = row

            if not movie_code:
                logger.warning(f"[API Action] Item {item_id} has no movie code")
                raise HTTPException(
                    status_code=400,
                    detail="No movie code - run extract-code first"
                )

            # If item doesn't have emby_item_id, reset to moved for EmbyUpdater
            if not emby_item_id:
                if not new_path:
                    raise HTTPException(
                        status_code=400,
                        detail="File not moved yet - run rename-file first"
                    )
                # Reset to moved state to trigger EmbyUpdater reprocessing
                cur.execute("""
                    UPDATE processing_queue
                    SET status = 'moved', updated_at = NOW()
                    WHERE id = %s
                """, (item_id,))
                conn.commit()
                return {
                    "success": True,
                    "message": f"Item {item_id} reset to moved for Emby scan",
                    "item_id": item_id,
                }

            logger.info(f"[API Action] Fetching metadata for: {movie_code}{fresh_text}")

            # Fetch metadata (fresh or cached)
            metadata_client = MetadataClient(
                base_url=os.getenv('API_BASE_URL', ''),
                token=os.getenv('API_TOKEN', ''),
                token_manager=_token_manager,
            )

            metadata = metadata_client.search(movie_code, fresh=fresh)
            if not metadata:
                logger.warning(f"[API Action] No metadata found for {movie_code}")
                raise HTTPException(
                    status_code=404,
                    detail=f"No metadata found for {movie_code}"
                )

            actress_list = metadata.get('actress', [])
            actress = actress_list[0] if actress_list else 'Unknown'
            title = metadata.get('title', '')
            logger.info(f"[API Action] Metadata found: {actress} - {title[:50]}")

            # Update metadata_json in database
            cur.execute("""
                UPDATE processing_queue
                SET metadata_json = %s, updated_at = NOW()
                WHERE id = %s
            """, (json.dumps(metadata), item_id))
            conn.commit()

            # Update Emby directly using stored emby_item_id
            emby_config = {
                'base_url': os.getenv('EMBY_BASE_URL', ''),
                'api_key': os.getenv('EMBY_API_KEY', ''),
                'parent_folder_id': os.getenv('EMBY_PARENT_FOLDER_ID', '4'),
                'user_id': os.getenv('EMBY_USER_ID', ''),
            }

            if emby_config['base_url'] and emby_config['api_key']:
                emby_client = EmbyClient(
                    base_url=emby_config['base_url'],
                    api_key=emby_config['api_key'],
                    parent_folder_id=emby_config['parent_folder_id'],
                    user_id=emby_config['user_id'],
                    wordpress_token=os.getenv('API_TOKEN', ''),
                    token_manager=_token_manager,
                )

                logger.info(f"[API Action] Updating Emby metadata for item {item_id} (Emby ID: {emby_item_id})")

                # Update Emby metadata
                update_success = emby_client.update_item_metadata(emby_item_id, metadata)

                if update_success:
                    logger.info(f"[API Action] Successfully updated Emby for item {item_id}")

                    # Upload images (best-effort)
                    image_url = metadata.get('image_cropped') or metadata.get('raw_image_url', '')
                    if image_url:
                        try:
                            emby_client.upload_item_images(emby_item_id, image_url)
                            logger.info(f"[API Action] Uploaded images for Emby item {emby_item_id}")
                        except Exception as e:
                            logger.warning(f"[API Action] Image upload failed for item {emby_item_id}: {e}")

                    return {
                        "success": True,
                        "message": f"Updated Emby: {actress} - {title[:40]}",
                        "actress": actress,
                        "title": title,
                    }
                else:
                    raise HTTPException(status_code=500, detail="Emby update failed")
            else:
                raise HTTPException(status_code=500, detail="Emby not configured")

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(f"[API Action] Failed to update Emby for item {item_id}")
        raise HTTPException(status_code=500, detail=f"Emby update failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/queue/{item_id}/actions/full-retry")
async def action_full_retry(item_id: int):
    """Reset to pending for full pipeline retry (alias for retry)."""
    # Just call the existing endpoint
    return await retry_item(item_id)


@app.delete("/api/queue/{item_id}")
async def delete_queue_item(item_id: int):
    """Delete a queue item from the database.

    Useful for removing error items or cleaning up the queue.
    Does NOT delete the actual file - only removes from processing queue.
    """
    logger.info(f"[API Action] Delete requested for item {item_id}")
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            # Check if item exists
            cur.execute("SELECT file_path, status FROM processing_queue WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(f"[API Action] Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            file_path, status = row
            logger.info(f"[API Action] Deleting item {item_id}: {file_path} (status: {status})")

            # Delete from database
            cur.execute("DELETE FROM processing_queue WHERE id = %s", (item_id,))
            conn.commit()

            logger.info(f"[API Action] Item {item_id} deleted from queue")

            return {
                "success": True,
                "message": f"Deleted item {item_id} from queue",
                "item_id": item_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(f"[API Action] Failed to delete item {item_id}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/cleanup")
async def cleanup(older_than_days: int = Query(30, ge=1, le=365)):
    """Delete completed items older than specified days (queue + downloads)."""
    db = get_queue_db()
    conn = db._get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM processing_queue
                WHERE status = 'completed'
                  AND updated_at < NOW() - INTERVAL '%s days'
                RETURNING id
            """, (older_than_days,))
            deleted_ids = [row[0] for row in cur.fetchall()]
            conn.commit()

        # Also clean up old download jobs
        dl_deleted = db.cleanup_old_downloads(older_than_days)

        return {
            "success": True,
            "message": f"Deleted {len(deleted_ids)} queue items and {dl_deleted} download jobs older than {older_than_days} days",
            "deleted_count": len(deleted_ids),
            "downloads_deleted": dl_deleted,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_conn(conn)


@app.post("/api/generate-preview")
async def generate_preview():
    """Trigger Emby video preview/trickplay generation scheduled task."""
    from .emby_client import EmbyClient

    emby_config = {
        'base_url': os.getenv('EMBY_BASE_URL', ''),
        'api_key': os.getenv('EMBY_API_KEY', ''),
    }

    if not emby_config['base_url'] or not emby_config['api_key']:
        raise HTTPException(status_code=500, detail="Emby not configured")

    emby_client = EmbyClient(
        base_url=emby_config['base_url'],
        api_key=emby_config['api_key'],
    )

    success = emby_client.generate_video_preview()
    if success:
        return {"success": True, "message": "Video preview generation task triggered"}
    raise HTTPException(status_code=500, detail="Failed to trigger video preview task")


@app.post("/api/bulk/refresh-metadata")
async def bulk_refresh_metadata(
    status: Optional[str] = Query(None, description="Filter by status (default: completed)"),
    update_emby: bool = Query(True, description="Also update Emby metadata"),
    fresh: bool = Query(False, description="Force fresh metadata (bypass cache)"),
):
    """Bulk re-fetch metadata for items using unified search endpoint.

    This uses the new /emby/v1/search unified endpoint which handles
    provider selection (missav → javguru) on the backend.

    Does NOT move files - only updates metadata_json and optionally Emby.
    """
    from .metadata import MetadataClient

    fresh_text = " (FORCE FRESH)" if fresh else ""
    logger.info(f"[API Bulk] Bulk metadata refresh started{fresh_text}")
    db = get_queue_db()
    conn = db._get_conn()

    # Default to completed items if no status specified
    filter_status = status or 'completed'

    try:
        # Get items to refresh
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, movie_code, new_path, emby_item_id
                FROM processing_queue
                WHERE status = %s AND movie_code IS NOT NULL
                ORDER BY id ASC
            """, (filter_status,))
            items = cur.fetchall()

        if not items:
            logger.info("[API Bulk] No items found with status: %s", filter_status)
            return {
                "success": True,
                "message": f"No items found with status: {filter_status}",
                "total": 0,
                "updated": 0,
                "failed": 0,
            }

        logger.info(f"[API Bulk] Found {len(items)} items to refresh")

        # Initialize metadata client with unified search
        metadata_client = MetadataClient(
            base_url=os.getenv('API_BASE_URL', ''),
            token=os.getenv('API_TOKEN', ''),
            token_manager=_token_manager,
        )

        updated_count = 0
        failed_count = 0
        failed_items = []

        for item_id, movie_code, new_path, emby_item_id in items:
            try:
                fresh_item_text = " (FORCE FRESH)" if fresh else ""
                logger.info(f"[API Bulk] Refreshing metadata for item {item_id}: {movie_code}{fresh_item_text}")

                # Fetch metadata using unified search
                metadata = metadata_client.search(movie_code, fresh=fresh)
                if not metadata:
                    logger.warning(f"[API Bulk] No metadata found for {movie_code} (item {item_id})")
                    failed_count += 1
                    failed_items.append({"id": item_id, "code": movie_code, "reason": "No metadata found"})
                    continue

                # Update metadata_json in database
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE processing_queue
                        SET metadata_json = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (json.dumps(metadata), item_id))
                    conn.commit()

                # Update Emby directly if requested and item has emby_item_id
                if update_emby and emby_item_id:
                    from .emby_client import EmbyClient

                    # Initialize Emby client
                    emby_config = {
                        'base_url': os.getenv('EMBY_BASE_URL', ''),
                        'api_key': os.getenv('EMBY_API_KEY', ''),
                        'parent_folder_id': os.getenv('EMBY_PARENT_FOLDER_ID', '4'),
                        'user_id': os.getenv('EMBY_USER_ID', ''),
                    }

                    if emby_config['base_url'] and emby_config['api_key']:
                        emby_client = EmbyClient(
                            base_url=emby_config['base_url'],
                            api_key=emby_config['api_key'],
                            parent_folder_id=emby_config['parent_folder_id'],
                            user_id=emby_config['user_id'],
                            wordpress_token=os.getenv('API_TOKEN', ''),
                            token_manager=_token_manager,
                        )

                        logger.info(f"[API Bulk] Updating Emby metadata for item {item_id} (Emby ID: {emby_item_id})")

                        # Update Emby metadata directly using stored emby_item_id
                        update_success = emby_client.update_item_metadata(emby_item_id, metadata)

                        if update_success:
                            logger.info(f"[API Bulk] Successfully updated Emby for item {item_id}")

                            # Upload images (best-effort)
                            image_url = metadata.get('image_cropped') or metadata.get('raw_image_url', '')
                            if image_url:
                                try:
                                    emby_client.upload_item_images(emby_item_id, image_url)
                                    logger.info(f"[API Bulk] Uploaded images for Emby item {emby_item_id}")
                                except Exception as e:
                                    logger.warning(f"[API Bulk] Image upload failed for item {emby_item_id}: {e}")
                        else:
                            logger.warning(f"[API Bulk] Failed to update Emby for item {item_id}")
                    else:
                        logger.warning("[API Bulk] Emby not configured, skipping Emby update")

                updated_count += 1
                logger.info(f"[API Bulk] Successfully updated item {item_id}")

            except Exception as e:
                logger.exception(f"[API Bulk] Failed to refresh item {item_id}")
                failed_count += 1
                failed_items.append({"id": item_id, "code": movie_code, "reason": str(e)})
                conn.rollback()

        logger.info(f"[API Bulk] Completed: {updated_count} updated, {failed_count} failed")

        return {
            "success": True,
            "message": f"Refreshed {updated_count}/{len(items)} items",
            "total": len(items),
            "updated": updated_count,
            "failed": failed_count,
            "failed_items": failed_items[:10],  # Return first 10 failures
        }

    except Exception as e:
        logger.exception("[API Bulk] Bulk refresh failed")
        raise HTTPException(status_code=500, detail=f"Bulk refresh failed: {str(e)}")
    finally:
        db._put_conn(conn)


@app.post("/api/download")
async def submit_download(
    url: str = Query(..., description="URL to download"),
    filename: str = Query("", description="Optional output filename"),
):
    """Submit a yt-dlp download job via docker exec."""
    from .downloader import get_download_manager

    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    manager = get_download_manager()
    job = manager.submit(url.strip(), filename.strip() or None)

    logger.info(f"[API] Download submitted: job={job['id']} url={url}")

    return {
        "success": True,
        "message": f"Download started (job {job['id']})",
        "job": job,
    }


@app.get("/api/downloads")
async def list_downloads(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List recent download jobs with pagination and optional status filter."""
    from .downloader import get_download_manager

    manager = get_download_manager()
    jobs, total = manager.list_jobs(limit=limit, offset=offset, status=status)
    return {
        "jobs": jobs,
        "total": total,
        "count": len(jobs),
    }


@app.get("/api/downloads/{job_id}")
async def get_download(job_id: int):
    """Get details for a specific download job."""
    from .downloader import get_download_manager

    manager = get_download_manager()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found")
    return {"job": job}


@app.get("/api/logs")
async def get_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get recent log lines from in-memory buffer."""
    try:
        log_buffer = get_log_buffer()
        log_lines = log_buffer.get_recent_logs(lines=lines)

        return {
            "lines": log_lines,
            "count": len(log_lines),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to fetch logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
