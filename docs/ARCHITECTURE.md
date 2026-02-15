# Architecture

## System Overview

The emby-processor is a Python Docker service that watches for new video files, fetches metadata from WordPress, renames and organizes files, then updates Emby with metadata and images. It uses a PostgreSQL queue to decouple file operations from Emby updates and supports retry with exponential backoff.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Watch Directory                              │
│                /volume3/docker/yt_dlp/downloads/                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ (watchdog inotify)
                  ┌────────────▼─────────────┐
                  │  watcher.py              │
                  │  - FileCreated events    │
                  │  - StabilityChecker      │
                  └────────────┬─────────────┘
                               │ queue.add(file_path, status='pending')
                  ┌────────────▼─────────────┐
                  │   PostgreSQL Queue DB   │
                  │  (processing_queue tbl) │
                  └──┬──────────┬──────────┬─┘
                     │          │          │
        ┌────────────▼──┐ ┌────▼────────┐ ┌▼──────────────────┐
        │ Worker 1:     │ │ Worker 2:   │ │ Worker 3:         │
        │ File          │ │ Emby        │ │ Retry             │
        │ Processor     │ │ Updater     │ │ Handler           │
        │               │ │             │ │                   │
        │ pending →     │ │ moved →     │ │ error →           │
        │ processing →  │ │ scan →      │ │ (if retriable) →  │
        │ moved         │ │ poll →      │ │ pending           │
        │               │ │ update →    │ │                   │
        │               │ │ images →    │ │                   │
        │               │ │ completed   │ │                   │
        └───────┬───────┘ └──────┬──────┘ └───────────────────┘
                │                │
     ┌──────────▼──────┐  ┌─────▼─────────┐
     │ WordPress API   │  │ Emby Server   │
     │ /missav/search  │  │ /Items/{id}   │
     │ /javguru/search │  │ /Images/{type}│
     └─────────────────┘  └───────────────┘
                               │
              ┌────────────────▼─────────────────────────────┐
              │              Destination Directory            │
              │    /volume2/system32/linux/systemd/jpv/       │
              │    ├── Ruri Saijo/                            │
              │    ├── Yua Mikami/                            │
              │    └── {Actress}/                             │
              └──────────────────────────────────────────────┘
```

---

## 1. PostgreSQL Queue Database

### Connection

External PostgreSQL server. Connection configured via environment variables:

```bash
# Option 1: Full connection string
DATABASE_URL=postgresql://emby:emby@localhost:5432/emby_processor

# Option 2: Individual parameters
DB_HOST=localhost
DB_PORT=5432
DB_NAME=emby_processor
DB_USER=emby
DB_PASSWORD=emby
```

Connection pooling via `psycopg2.pool.ThreadedConnectionPool` (min=1, max=5 connections).

### Schema

Table name: `processing_queue` (migration: `migrations/001_create_queue.sql`)

```sql
CREATE TABLE IF NOT EXISTS processing_queue (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    movie_code      VARCHAR(20),
    actress         VARCHAR(255),
    subtitle        VARCHAR(50),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    new_path        TEXT,
    emby_item_id    VARCHAR(100),
    metadata_json   JSONB,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index on status for queue polling queries
CREATE INDEX IF NOT EXISTS idx_queue_status ON processing_queue (status);

-- Partial index on next_retry_at for retry polling (only error rows)
CREATE INDEX IF NOT EXISTS idx_queue_retry ON processing_queue (next_retry_at)
    WHERE status = 'error' AND next_retry_at IS NOT NULL;

-- Unique index on file_path to prevent duplicate entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_file_path ON processing_queue (file_path);

-- Auto-update updated_at on row changes
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_queue_updated_at
    BEFORE UPDATE ON processing_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### Status Flow

```
          ┌──────────────────────────────────────────────────────────────┐
          │                     Worker 1: File Processor                 │
          │                                                              │
          │   pending ──► processing ──► moved                          │
          │       │            │                                         │
          │       │            ▼                                         │
          │       │         error ◄──────────────────────┐              │
          └───────┼──────────────────────────────────────┼──────────────┘
                  │                                      │
          ┌───────┼──────────────────────────────────────┼──────────────┐
          │       │          Worker 2: Emby Updater      │              │
          │       │                                      │              │
          │       │   moved ──► emby_pending ──► completed│              │
          │       │                  │                    │              │
          │       │                  ▼                    │              │
          │       │               error ─────────────────┘              │
          └───────┼─────────────────────────────────────────────────────┘
                  │
          ┌───────┼─────────────────────────────────────────────────────┐
          │       │          Worker 3: Retry Handler                     │
          │       │                                                      │
          │       └──── error (where retry_count <= MAX_RETRIES          │
          │                     AND next_retry_at <= now)                 │
          │                          │                                   │
          │                          ▼                                   │
          │                      pending (retry_count already incremented│
          │                               on error transition)           │
          └──────────────────────────────────────────────────────────────┘
```

### Status Descriptions

| Status | Owner | Description |
|--------|-------|-------------|
| `pending` | -- | File detected and queued, waiting for Worker 1 |
| `processing` | Worker 1 | Extracting code, fetching metadata, renaming, moving |
| `moved` | -- | File successfully renamed and moved to destination |
| `emby_pending` | Worker 2 | Emby scan triggered, polling for item, updating metadata, uploading images |
| `completed` | -- | All steps finished successfully |
| `error` | -- | Failed at some step; `error_message` has details |

### Queue Operations (`src/queue.py`)

```python
class QueueDB:
    def __init__(self, database_url: str | None = None, **kwargs):
        """Initialize PostgreSQL connection pool (ThreadedConnectionPool).
        Accepts DATABASE_URL or individual params (host, port, dbname, user, password).
        Falls back to DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD env vars."""

    def initialize(self):
        """Run migration SQL (migrations/001_create_queue.sql) to create schema."""

    def add(self, file_path: str, movie_code=None, actress=None, subtitle=None) -> dict:
        """Insert a new item with status='pending'. Returns the created row.
        On UNIQUE violation, returns existing row (idempotent)."""

    def get(self, item_id: int) -> dict | None:
        """Get a queue item by ID."""

    def get_by_file_path(self, file_path: str) -> dict | None:
        """Get a queue item by file path."""

    def get_next_pending(self) -> dict | None:
        """Atomically claim the oldest pending item → status='processing'.
        Uses FOR UPDATE SKIP LOCKED for safe concurrent access."""

    def get_next_moved(self) -> dict | None:
        """Atomically claim the oldest moved item → status='emby_pending'.
        Uses FOR UPDATE SKIP LOCKED for safe concurrent access."""

    def update_status(self, item_id: int, status: str, **kwargs) -> dict | None:
        """Update status and optional fields (error_message, new_path, emby_item_id, metadata_json).
        On error status: auto-increments retry_count and sets next_retry_at with backoff."""

    def get_retryable_errors(self, limit: int = 10) -> list[dict]:
        """Get error items where retry_count <= MAX_RETRIES and next_retry_at <= NOW()."""

    def reset_for_retry(self, item_id: int) -> dict | None:
        """Reset an error item to 'pending', clear error_message and next_retry_at."""

    def count_by_status(self) -> dict[str, int]:
        """Return count per status: {'pending': 5, 'processing': 1, ...}"""

    def list_by_status(self, status: str, limit: int = 50) -> list[dict]:
        """List items filtered by status, ordered by created_at DESC."""

    def delete(self, item_id: int) -> bool:
        """Delete a queue item by ID. Returns True if deleted."""

    def close(self):
        """Close the connection pool."""
```

### Concurrency Safety

PostgreSQL provides robust concurrent access through row-level locking. The `ThreadedConnectionPool` (min=1, max=5) manages connections for worker threads.

- **Atomic claim**: `get_next_pending()` and `get_next_moved()` use `FOR UPDATE SKIP LOCKED` to prevent double-pickup when multiple workers poll simultaneously:

```sql
UPDATE processing_queue
SET status = 'processing'
WHERE id = (
    SELECT id FROM processing_queue
    WHERE status = 'pending'
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

- **Auto-updated timestamps**: A PostgreSQL trigger (`trg_queue_updated_at`) automatically sets `updated_at = NOW()` on every row update, so application code never needs to manage this.

- **Retry backoff**: When status transitions to `error`, `update_status()` auto-increments `retry_count` and computes `next_retry_at` using the backoff schedule `[1, 5, 15]` minutes.

---

## 2. Worker Architecture

All workers run as daemon threads within the single Python process, coordinated through the PostgreSQL queue.

### Worker Thread Model

```python
# main.py startup
def main():
    config = load_config()
    queue_db = QueueDB(database_url=config.get('database_url'))

    # Start watcher (adds files to queue)
    observer = start_watcher(..., callback=queue_db.add)

    # Start workers as daemon threads
    workers = [
        FileProcessorWorker(config, queue_db),
        EmbyUpdaterWorker(config, queue_db),
        RetryWorker(config, queue_db),
    ]
    for w in workers:
        w.start()

    # Main thread: periodic status logging
    while True:
        stats = queue_db.get_stats()
        logger.info('Queue: %s', stats)
        time.sleep(60)
```

### Worker 1: File Processor

**Picks up**: `status = 'pending'`
**Sets to**: `processing` -> `moved` (or `error`)
**Poll interval**: 2 seconds

```
Sequence:
1. get_next('pending') → item (atomically sets status='processing')
2. extract_movie_code(filename)
   - No match → status='error', error_message='No movie code found'
3. detect_subtitle(filename)
4. metadata_client.search(movie_code)
   - No result → retry once → still nothing → status='error'
5. build_filename(actress, subtitle, code, title, ext)
6. move_file(source, destination, actress, filename)
   - OSError → status='error'
7. status='moved', new_path=destination, metadata_json=json.dumps(metadata)
```

**Key behavior**: This worker does NOT touch Emby at all. It only handles filesystem operations and metadata lookup. This means files are organized even if Emby is down.

### Worker 2: Emby Updater

**Picks up**: `status = 'moved'`
**Sets to**: `emby_pending` -> `completed` (or `error`)
**Poll interval**: 5 seconds

```
Sequence:
1. get_next_moved() → item (atomically sets status='emby_pending')
2. Trigger Emby scan on parent folder (EMBY_PARENT_FOLDER_ID=4)
   - Scan fail → status='error', error_message='Emby scan failed'
3. Poll for Emby item with exponential backoff:
   - Attempts: 2s, 4s, 8s, 16s, 32s, 64s (6 attempts, ~126s max)
   - get_item_by_path(new_path)
   - If not found after retries → fallback: find_item_by_filename()
   - Still not found → status='error', error_message='Item not indexed'
4. Update Emby metadata (title, actress, genre, studios, etc.)
   - Fail → status='error'
5. Upload images (see Section 4 below)
   - Image upload failures are logged but do NOT block completion
6. status='completed', emby_item_id=item_id
```

### Worker 3: Retry Handler

**Picks up**: `status = 'error'` where `retry_count <= MAX_RETRIES` and `next_retry_at <= now`
**Poll interval**: 30 seconds

```
Sequence:
1. get_retryable_errors(limit=10) → list of items
2. For each item:
   a. reset_for_retry(item_id)
      → Sets status='pending', clears error_message and next_retry_at
      (retry_count was already incremented when status was set to 'error')
```

Note: The `retry_count` increment and `next_retry_at` backoff calculation happen inside `update_status()` when transitioning to `error`, not when resetting for retry. This ensures the backoff schedule is always correctly applied.

---

## 3. Retry / Polling Strategy

### Exponential Backoff Parameters

| Parameter | Value | Config Key |
|-----------|-------|------------|
| Max retries (queue) | 3 | `MAX_RETRIES` (in `src/queue.py`) |
| Retry backoff schedule | [1, 5, 15] minutes | `RETRY_BACKOFF_MINUTES` (in `src/queue.py`) |
| Emby poll delays | 2, 4, 8, 16, 32, 64 seconds | `EMBY_SCAN_RETRY_DELAYS` |
| Emby poll max attempts | 6 | Length of `EMBY_SCAN_RETRY_DELAYS` |

### Queue Retry Schedule (Worker 3)

Failed items are retried with a stepped backoff schedule:

```
Retry 1: after 1 minute
Retry 2: after 5 minutes
Retry 3: after 15 minutes
--- MAX_RETRIES reached, item stays in error permanently ---
```

The backoff index is `min(retry_count - 1, len(RETRY_BACKOFF_MINUTES) - 1)`, so if retry_count exceeds the schedule length, the last delay is reused.

### Emby Item Polling (Worker 2, inline)

After triggering an Emby scan, poll for the item to appear:

```
Attempt 1: immediate
  wait 2s
Attempt 2: after 2s total
  wait 4s
Attempt 3: after 6s total
  wait 8s
Attempt 4: after 14s total
  wait 16s
Attempt 5: after 30s total
  wait 32s
Attempt 6: after 62s total
--- give up, try fallback search by filename ---
```

Formula: `delay = INITIAL_DELAY * 2^attempt` (starting at attempt 0)

### Scan Endpoint Fix

The legacy system uses `EmbyService.scanLibrary(4)` where `4` is the parent folder ID containing all actress subfolders. The current code incorrectly uses either a library ID or a full library refresh.

**Fix**: Use the parent folder ID for targeted scanning:

```python
parent_folder_id = config.get('emby', {}).get('parent_folder_id', '4')
self.emby_client.scan_library_by_id(parent_folder_id)
```

The `scan_library_by_id()` endpoint already exists and calls `POST /Items/{id}/Refresh?Recursive=true`.

---

## 4. Image Upload Flow

### Overview

The legacy system downloads images from WordPress (via `image_cropped` URL), converts to base64, and uploads three image types to Emby. We replicate this.

### Image Types

| Type | Source | Purpose |
|------|--------|---------|
| Primary | `image_cropped` (original aspect) | Main poster/thumbnail |
| Backdrop | `image_cropped` with `?w=800` | Wide background image |
| Banner | `image_cropped` with `?w=800` | Header banner |

### Flow (within Worker 2, after metadata update)

```
1. Extract image_cropped URL from metadata_json
   - URL not present → skip images (not an error)

2. Download original image
   - GET image_cropped URL
   - Validate Content-Type starts with 'image/'
   - Convert response bytes to base64 string
   - Download fail → log warning, skip images

3. Download W800 variant for Backdrop/Banner
   - Modify URL: set ?w=800, remove ?horizontal
   - GET modified URL → base64

4. Delete existing images from Emby (clean slate)
   - DELETE /Items/{id}/Images/Primary/0
   - DELETE /Items/{id}/Images/Backdrop/0..4
   - DELETE /Items/{id}/Images/Banner/0
   - DELETE /Items/{id}/Images/Logo/0
   - Ignore 404s (image may not exist)

5. Upload new images to Emby
   - POST /Items/{id}/Images/Primary
     Content-Type: image/jpeg
     Body: base64 string (original)
   - POST /Items/{id}/Images/Backdrop
     Content-Type: image/jpeg
     Body: base64 string (W800)
   - POST /Items/{id}/Images/Banner
     Content-Type: image/jpeg
     Body: base64 string (W800)

6. Log results; failures are warnings, not errors
```

### Emby Image API

```
Upload:  POST /Items/{id}/Images/{type}?api_key={key}
         Content-Type: image/jpeg
         Body: raw base64 string (no data:image prefix)

Delete:  DELETE /Items/{id}/Images/{type}/{index}
         X-Emby-Token: {key}
```

### Implementation (`src/emby_client.py`)

```python
def delete_image(self, item_id: str, image_type: str, index: int = 0) -> bool:
    """Delete an image from an Emby item. Returns True on success or 404."""

def upload_image(self, item_id: str, image_type: str, base64_data: str,
                 content_type: str = 'image/jpeg') -> bool:
    """Upload a base64-encoded image to an Emby item."""
```

### Image Helper (`src/image_helper.py`)

```python
def download_image_as_base64(url: str) -> tuple[str, str] | None:
    """Download image from URL, return (base64_string, content_type) or None."""

def get_w800_url(url: str) -> str:
    """Modify image URL to request w=800 variant (remove horizontal param)."""

def upload_images_for_item(emby_client, item_id: str, metadata: dict) -> bool:
    """Full image flow: download, delete old, upload new.
    Returns True if at least Primary was uploaded."""
```

---

## 5. Integration Points

### Watcher -> Queue (changed)

**Before**: `watcher.py` calls `pipeline.process(file_path)` directly.
**After**: `watcher.py` calls `queue_db.add(file_path)`.

```python
# watcher.py - VideoHandler._handle()
def _handle(self, file_path: str):
    # ... existing extension/stability checks ...
    try:
        self.callback(file_path)  # callback is now queue_db.add
    except Exception as e:
        logger.error('Failed to queue file: %s', e)
```

### Pipeline Refactoring (changed)

**Before**: `Pipeline.process()` does everything synchronously.
**After**: `Pipeline` is split into methods called by workers.

The existing `Pipeline` class is refactored into utility methods:

```python
class Pipeline:
    def process_file(self, item: dict) -> dict:
        """Worker 1 logic: extract, metadata, rename, move.
        Returns dict with new_path, metadata, actress, etc."""

    def update_emby(self, item: dict) -> dict:
        """Worker 2 logic: scan, poll, update metadata.
        Returns dict with emby_item_id."""

    def upload_images(self, item: dict) -> bool:
        """Worker 2 sub-step: download and upload images."""
```

### Configuration Changes

New environment variables (added to `.env.example`):

```bash
# PostgreSQL Queue Database
# Option 1: Full connection string
# DATABASE_URL=postgresql://emby:emby@localhost:5432/emby_processor

# Option 2: Individual parameters
DB_HOST=localhost
DB_PORT=5432
DB_NAME=emby_processor
DB_USER=emby
DB_PASSWORD=emby

# Emby scan retry delays (comma-separated seconds, exponential backoff)
EMBY_SCAN_RETRY_DELAYS=2,4,8,16,32,64

# Emby parent folder (for targeted scan)
EMBY_PARENT_FOLDER_ID=4
```

### Docker Changes

The PostgreSQL database is external (e.g., running on the Synology NAS or another container). No local data volume is needed for the queue. The `docker-compose.yml` connects to PostgreSQL via the network configuration.

---

## 6. Error Handling Strategy

### Error Categories

| Category | Example | Retry? | Reset To |
|----------|---------|--------|----------|
| **Extraction failure** | No movie code in filename | No | stays error |
| **Metadata not found** | WordPress returns no results | Yes | `pending` |
| **File system error** | Permission denied, disk full | Yes | `pending` |
| **Emby scan failure** | Emby server unreachable | Yes | `pending` |
| **Emby item not found** | Item not indexed after polling | Yes | `pending` |
| **Emby update failure** | Metadata POST fails | Yes | `pending` |
| **Image download failure** | WordPress image URL broken | No | completes anyway |
| **Image upload failure** | Emby rejects image | No | completes anyway |

Note: The `reset_for_retry()` method always resets to `pending` status. When Worker 1 picks up a retried item that already has `new_path` set (file was already moved), it can detect this and skip the file processing step, passing the item directly to `moved` status for Emby updates.

### Error Classification

Errors are classified by the `error_message` prefix to determine retry behavior:

```python
NON_RETRIABLE_PREFIXES = [
    'No movie code',        # Filename won't change on retry
    'No metadata found',    # Removed: this IS retriable (WP might update)
]

# Actually, the only truly non-retriable error is extraction failure.
# Everything else could succeed on retry (API back online, Emby indexed, etc.)
```

Decision: All errors retry EXCEPT those with `error_message` starting with `'No movie code'`. The retry handler checks this before resetting.

### Error Logging

Every error transition logs:
- Item ID and file path
- Current status and target status
- Full error message
- Retry count

### Dead Letter Behavior

Items that exhaust `MAX_RETRIES` (default 3) remain in `error` status permanently. They appear in CLI output and can be manually retried via `python -m src.cli retry <id>` or `retry-all`.

---

## 7. CLI Interface

### Entry Point

```bash
python -m src.cli <command> [options]
```

### Commands

| Command | Description |
|---------|-------------|
| `status` | Show queue summary (count per status) |
| `list [--status STATUS] [--limit N]` | List queue items |
| `retry <id>` | Reset specific item for retry |
| `retry-all` | Reset all retriable error items |
| `cleanup [--days N]` | Delete completed items older than N days (default 7) |
| `reset <id>` | Force-reset any item to pending |

### Example Output

```
$ python -m src.cli status
Queue Status:
  pending:          3
  processing:       1
  moved:            0
  emby_pending:     0
  completed:       47
  error:            2
  ─────────────────────
  total:           53

$ python -m src.cli list --status error
ID   Movie Code  Status  Retries  Error                     Updated
──   ──────────  ──────  ───────  ─────                     ───────
12   SONE-760    error   2/3      Emby item not indexed     2026-02-15 10:30
25   ABF-123     error   3/3      No movie code found       2026-02-15 11:15
```

---

## 8. File Structure (New/Modified)

### New Files

```
src/queue.py            # PostgreSQL queue database operations (psycopg2 + connection pool)
src/workers.py          # FileProcessorWorker, EmbyUpdaterWorker, RetryWorker
src/image_helper.py     # Image download/upload utilities
src/cli.py              # CLI commands for queue management
migrations/001_create_queue.sql  # PostgreSQL schema migration
tests/test_queue.py     # Queue database tests
tests/test_workers.py   # Worker logic tests
tests/test_image.py     # Image helper tests
```

### Modified Files

```
main.py                 # Start workers, initialize queue
src/watcher.py          # Callback becomes queue_db.add
src/pipeline.py         # Split into worker-callable methods
src/emby_client.py      # Add retry polling, image upload/delete, fallback search
.env.example            # Add PostgreSQL and retry configuration
docker-compose.yml      # Network configuration for PostgreSQL access
requirements.txt        # Add psycopg2-binary
```

---

## 9. Docker Network

```
┌────────────────────────────────────────────────────────┐
│             wpfamilyhubid_net                          │
│              (Docker network)                          │
│                                                        │
│  ┌──────────────────┐    ┌────────────────────────┐   │
│  │ emby-processor   │───▶│ wpfamilyhubid_nginx    │   │
│  │ (Python)         │HTTP│ (WordPress + Nginx)    │   │
│  │                  │    └────────────────────────┘   │
│  │ Volumes:         │                                  │
│  │  /watch          │    ┌────────────────────────┐   │
│  │  /destination    │───▶│ emby_server            │   │
│  │                  │HTTP│ (Emby Media Server)    │   │
│  │  Network:        │    └────────────────────────┘   │
│  │  PostgreSQL ─────│──▶ (external DB server)         │
│  └──────────────────┘                                  │
│                                                        │
└────────────────────────────────────────────────────────┘

Volumes:
  /volume3/docker/yt_dlp/downloads     →  /watch         (input)
  /volume2/system32/linux/systemd/jpv  →  /destination   (output)

External services:
  PostgreSQL (DB_HOST:DB_PORT)         →  processing_queue table
```

---

## 10. Data Flow (Complete Pipeline)

```
1. yt-dlp downloads video to /watch/
   │
2. watcher.py detects file, waits for stability
   │
3. queue_db.add(file_path) → status: pending
   │
   ├──────────────── Worker 1: File Processor ────────────────
   │
4. Pick up pending item → status: processing
   │
5. extractor.extract_movie_code(filename)
   │ No match → status: error ("No movie code found")
   │
6. extractor.detect_subtitle(filename)
   │
7. metadata_client.search(movie_code)
   │ Try missav, then javguru, retry once
   │ No result → status: error ("No metadata found")
   │
8. renamer.build_filename(actress, subtitle, code, title, ext)
   │
9. renamer.move_file(source, destination, actress, filename)
   │ → status: moved (new_path saved, metadata_json saved)
   │
   ├──────────────── Worker 2: Emby Updater ──────────────────
   │
10. Pick up moved item → status: emby_pending
    │
11. emby_client.scan_library_by_id(parent_folder_id=4)
    │ Fail → status: error ("Emby scan failed")
    │
12. Poll: emby_client.get_item_by_path(new_path)
    │ Exponential backoff: 2s, 4s, 8s, 16s, 32s, 64s
    │ Not found → fallback: find_item_by_filename()
    │ Still not found → status: error ("Item not indexed")
    │
13. emby_client.update_item_metadata(item_id, metadata)
    │ Fail → status: error ("Metadata update failed")
    │
14. image_helper.upload_images_for_item(emby_client, item_id, metadata)
    │ Download image_cropped → base64 (original + W800)
    │ Delete old: Primary, Backdrop/0..4, Banner, Logo
    │ Upload new: Primary (original), Backdrop (W800), Banner (W800)
    │ Failures logged as warnings, do not block completion
    │
15. status: completed (emby_item_id saved)
    │
    ├──────────────── Worker 3: Retry Handler ─────────────────
    │
16. Every 30s: check for error items with retry_count <= 3
    │ and next_retry_at <= now
    │
17. reset_for_retry(item_id) → status: pending
    │ (retry_count was already incremented on error transition)
    │ (next_retry_at was set with backoff: 1min, 5min, 15min)
```

---

## Design Decisions

1. **PostgreSQL over SQLite**: PostgreSQL provides robust `FOR UPDATE SKIP LOCKED` for safe concurrent worker access, `JSONB` for structured metadata storage, proper timestamp handling with time zones, and trigger-based `updated_at` management. The external database also persists independently of container lifecycle and can be shared by future services.

2. **Threads over processes**: Workers share the same Python process. Threading is simpler for our I/O-bound workload (waiting on HTTP responses, file system). PostgreSQL's `ThreadedConnectionPool` manages connections safely across threads.

3. **Connection pooling**: `psycopg2.pool.ThreadedConnectionPool` with min=1, max=5 connections. This avoids per-query connection overhead while keeping resource usage low for a background service.

4. **Images don't block completion**: Image upload failures are warnings, not errors. The item still has correct metadata even without images. Images can be retried manually via CLI.

5. **Targeted scan over full library refresh**: Using `scan_library_by_id(parent_folder_id)` matches the legacy `EmbyService.scanLibrary(4)` pattern. This is faster than scanning all libraries.

6. **Fallback search by filename**: If path-based search fails (path normalization differences between Docker and Emby), searching by filename within the actress folder is a reliable fallback.

7. **Retry count on error, not on reset**: The `retry_count` is incremented when transitioning to `error` status, not when resetting for retry. This ensures the backoff schedule (`next_retry_at`) is always computed from the correct attempt number at the moment of failure.

8. **Queue deduplication**: The `file_path` column has a UNIQUE index. If the same file triggers watchdog events multiple times (e.g., during copy), the `add()` method returns the existing row instead of raising (idempotent insert).
