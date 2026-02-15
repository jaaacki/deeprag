"""FastAPI web dashboard for queue monitoring and manual controls."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from .queue import QueueDB

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Emby Processor Dashboard",
    description="Queue monitoring and manual controls for emby-processor",
    version="0.5.0",
)

# Add CORS middleware (allow all origins for LAN access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global QueueDB instance (initialized on startup)
queue_db: Optional[QueueDB] = None


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
    get_queue_db()
    logger.info("FastAPI dashboard started")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    global queue_db
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
                       created_at, updated_at
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


@app.post("/api/cleanup")
async def cleanup(older_than_days: int = Query(30, ge=1, le=365)):
    """Delete completed items older than specified days."""
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

        return {
            "success": True,
            "message": f"Deleted {len(deleted_ids)} completed items older than {older_than_days} days",
            "deleted_count": len(deleted_ids),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_conn(conn)


@app.get("/api/logs")
async def get_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get recent log lines from docker container."""
    try:
        import subprocess

        # Get logs from docker container
        result = subprocess.run(
            ['docker', 'logs', '--tail', str(lines), 'emby-processor'],
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Combine stdout and stderr
        log_output = result.stdout + result.stderr
        log_lines = log_output.strip().split('\n')[-lines:]

        return {
            "lines": log_lines,
            "count": len(log_lines),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Log fetch timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker command not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
