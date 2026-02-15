# Emby Processor

[![GitHub](https://img.shields.io/badge/github-jaaacki%2Femby--processor-blue)](https://github.com/jaaacki/emby-processor)

Automated file processing pipeline that watches for new video files, fetches metadata from the emby-service WordPress plugin, renames files with structured names, organizes them into actress folders, and triggers Emby library scans.

## What It Does

- Watches a download folder for new video files (`.mp4`, `.mkv`, `.avi`, `.wmv`)
- Extracts movie code and subtitle language from the filename
- Searches the WP REST API for metadata (actress, title, etc.)
- Renames to: `{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}`
- Moves to `{destination}/{Actress}/` (creates folder if needed, matches case-insensitively)
- Queues files in PostgreSQL database for reliable processing
- Worker processes handle file operations and Emby operations independently
- Triggers Emby server to scan and import the new file (targeted scan, not full library)
- Writes metadata to Emby (title, actress, genre, studios) with LockData to prevent overwrites
- Downloads and uploads poster images (Primary, Backdrop, Banner) from WordPress
- Automatic retry with exponential backoff for failures
- CLI for queue management and monitoring
- yt-dlp download form on dashboard (triggers downloads via `docker exec`)

### Example

```
Input:  SONE-760 English subbed The same commute train as always.mp4
Output: Ruri Saijo - [English Sub] SONE-760 The Same Commute Train As Always.mp4
Moved:  /destination/Ruri Saijo/
```

## Requirements

- Docker and Docker Compose
- PostgreSQL database (for queue and state tracking)
- The emby-service WordPress plugin running on the same Docker network
- Emby server with API access
- A watch directory where yt-dlp (or similar) drops files

## Setup

### 1. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
nano .env
```

Key settings to update:

```bash
# WordPress REST API (use Docker internal hostname)
API_BASE_URL=http://wpfamilyhubid_nginx/wp-json/emby/v1
API_TOKEN=your-wordpress-access-token  # JWT access token (expires in 24h)

# Emby Server (use Docker internal hostname)
# Find your Emby container: docker ps | grep -i emby
EMBY_BASE_URL=http://emby_server:8096
EMBY_API_KEY=your-emby-api-key
```

**Important**: Also create `.refresh_token` file with your WordPress refresh token:
```bash
echo "your-refresh-token-here" > .refresh_token
chmod 600 .refresh_token
```

The container will automatically refresh the access token every 20 hours using the refresh token.

See `.env.example` for all available options.

### 2. Deploy

For local development:
```bash
docker compose up -d
```

For production deployment on Synology NAS, see [DEPLOY.md](DEPLOY.md) for detailed instructions.

The `docker-compose.yml` mounts:
- `/volume3/docker/yt_dlp/downloads` → `/watch` (input)
- `/volume2/system32/linux/systemd/jpv` → `/destination` (output)
- `./.env` → `/app/.env` (read/write, updated by token refresh)
- `./.refresh_token` → `/app/.refresh_token` (WordPress refresh token)

### Automatic Token Refresh

WordPress JWT tokens expire every 24 hours. The container automatically refreshes them:

- **Cron job** runs inside container every 20 hours
- Uses refresh token to get new access token
- Updates `.env` file automatically
- **No manual intervention needed** after initial setup

See [scripts/README.md](scripts/README.md) for technical details.

### 3. Verify

Check logs:

```bash
docker compose logs -f emby-processor
```

Drop a test file in the watch directory and confirm it gets processed:

```
2026-02-15 10:00:00 [INFO] emby-processor: Watching for new files...
2026-02-15 10:00:05 [INFO] src.watcher: New file detected: SONE-760 English subbed title.mp4
2026-02-15 10:00:15 [INFO] src.watcher: File stable: /watch/SONE-760 English subbed title.mp4 (524288000 bytes)
2026-02-15 10:00:16 [INFO] src.queue: Added to queue: /watch/SONE-760 English subbed title.mp4
2026-02-15 10:00:16 [INFO] src.workers: FileProcessor claimed item 123
2026-02-15 10:00:17 [INFO] src.metadata: Found metadata for SONE-760 via missav
2026-02-15 10:00:17 [INFO] src.renamer: Moving /watch/... -> /destination/Ruri Saijo/...
2026-02-15 10:00:18 [INFO] src.workers: EmbyUpdater claimed item 123
2026-02-15 10:00:20 [INFO] src.emby_client: Found Emby item after 2s retry
2026-02-15 10:00:21 [INFO] src.emby_client: Successfully uploaded images for item
```

## Queue Management

The CLI provides real-time visibility and control over the processing queue:

```bash
# View queue statistics
python -m src status

# List items by status
python -m src list --status pending
python -m src list --status error

# Retry failed items
python -m src retry <item_id>
python -m src retry-all  # Retry all errors

# Clean up old items
python -m src cleanup --older-than 30  # Remove completed items older than 30 days

# Reset queue (dangerous - for development only)
python -m src reset
```

**Queue Status Flow:**
- `pending` → File detected, waiting for processing
- `processing` → FileProcessor extracting metadata
- `moved` → File moved to destination, waiting for Emby
- `emby_pending` → EmbyUpdater scanning and updating
- `completed` → Successfully processed
- `error` → Failed, will retry automatically

## Pipeline Flow

```
New file appears in /watch
  │
  ├─ Watcher: Stability check (wait for yt-dlp to finish writing)
  │
  ├─ Add to PostgreSQL queue (status: pending)
  │
  ▼
FileProcessorWorker picks item (status: processing)
  │
  ├─ Extract movie code: regex [A-Za-z]{2,6}-\d{1,5}
  │   └─ No code found → status: error (RetryHandler will retry)
  │
  ├─ Detect subtitle: scan for 'english'/'chinese' keywords
  │
  ├─ Search API: POST /missav/search → fallback: /javguru/search
  │   └─ No result → status: error (RetryHandler will retry)
  │
  ├─ Build filename: {Actress} - [{Sub}] {CODE} {Title}.{ext}
  │
  ├─ Move to /destination/{Actress}/
  │   └─ Creates actress folder if needed
  │   └─ Matches existing folders case-insensitively
  │
  └─ Mark as moved (status: moved)
  │
  ▼
EmbyUpdaterWorker picks item (status: emby_pending)
  │
  ├─ Trigger Emby library scan (parent_folder_id, targeted not full)
  │
  ├─ Retry polling for item (2s, 4s, 8s, 16s, 32s, 64s exponential backoff)
  │   └─ Item not found after 126s → status: error
  │
  ├─ Update Emby metadata
  │   └─ Write WordPress metadata (actress, title, genre, studios)
  │   └─ Set LockData: true to prevent overwrites
  │
  ├─ Upload images (Primary, Backdrop, Banner from WordPress)
  │   └─ Best-effort: failures logged, don't block completion
  │
  └─ Mark as completed (status: completed)
  │
  ▼
RetryHandler (background)
  │
  └─ Picks error items with exponential backoff (1m, 5m, 15m)
      └─ Resets status to pending for retry
      └─ Max 3 retries, then stays in error
```

## Error Handling

Files that can't be processed are marked with `status: error` in the queue:
- No movie code found in filename
- API search returned no results
- File move failed
- Emby scan or metadata update failed

**Automatic Retry**: The RetryHandler worker automatically retries errors with exponential backoff (1m, 5m, 15m). Max 3 retries.

**Manual Intervention**:
```bash
# List all errors
python -m src list --status error

# Retry specific item
python -m src retry <item_id>

# Retry all errors immediately
python -m src retry-all
```

Check the queue database and logs to diagnose persistent failures.

## Development

### Run tests locally

```bash
cd emby-processor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

**Note**: Tests run in CI and locally. 152 tests covering extractor, renamer, Emby client, queue database, workers, and CLI.

### Test Emby Integration

Manual testing scripts for Emby API integration:

- **[test_emby_simple.md](test_emby_simple.md)** — curl commands to test Emby API endpoints
- **[test_emby_update.md](test_emby_update.md)** — Python test script for metadata updates

```bash
# Run Python test (requires .env configuration)
python3 test_emby_update.py

# Or use curl commands from test_emby_simple.md
```

See test documentation for detailed checklists and passing criteria.

### Project structure

```
emby-processor/
├── main.py                  # Entry point: load config, start watcher + workers
├── .env                     # Environment configuration (not tracked)
├── .env.example             # Template for .env
├── src/
│   ├── __main__.py          # CLI entry point: python -m src
│   ├── watcher.py           # watchdog folder monitor + stability check
│   ├── queue.py             # PostgreSQL queue database (ThreadedConnectionPool)
│   ├── workers.py           # FileProcessor, EmbyUpdater, RetryHandler workers
│   ├── cli.py               # Queue management CLI (status, list, retry, cleanup)
│   ├── extractor.py         # Movie code + subtitle detection
│   ├── metadata.py          # WP REST API client
│   ├── emby_client.py       # Emby server API client (scan, metadata, images)
│   ├── renamer.py           # Filename builder + sanitizer + file move
│   ├── downloader.py        # yt-dlp download manager (docker exec + background threads)
│   └── pipeline.py          # Legacy orchestrator (kept for reference)
├── migrations/
│   └── 001_create_queue.sql # PostgreSQL schema for processing_queue table
├── tests/
│   ├── test_extractor.py    # Extractor unit tests (11 tests)
│   ├── test_renamer.py      # Renamer unit tests (12 tests)
│   ├── test_emby_client.py  # Emby client unit tests (11 tests)
│   ├── test_queue.py        # Queue database integration tests (24 tests)
│   ├── test_workers.py      # Worker process unit tests (25 tests)
│   └── test_cli.py          # CLI unit tests (50 tests)
├── test_emby_update.py      # Standalone Emby metadata test
├── test_emby_simple.py      # Curl command generator for testing
├── test_emby_update.md      # Python test documentation + checklist
├── test_emby_simple.md      # Curl test documentation + checklist
├── googlescript_legacy/     # Reference JavaScript implementation
├── docs/
│   └── ARCHITECTURE.md      # System architecture and data flow
├── Dockerfile
├── docker-compose.yml
├── DEPLOY.md                # Deployment guide for Synology NAS
└── requirements.txt
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component diagram and data flow.

See [ROADMAP.md](ROADMAP.md) for planned work and [CHANGELOG.md](CHANGELOG.md) for history.
