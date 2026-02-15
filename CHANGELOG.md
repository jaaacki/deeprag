# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.4.0] — 2026-02-15

Phase 4: Production Features — queue database, worker processes, image upload, and retry polling bring emby-processor to production readiness.

### Added
- PostgreSQL queue database with connection pooling (#2)
  - `QueueDatabase` class with ThreadedConnectionPool (psycopg2)
  - Atomic worker claiming via `FOR UPDATE SKIP LOCKED`
  - Status flow: pending → processing → moved → emby_pending → completed
  - Database migration: `migrations/001_create_queue.sql`
  - Exponential backoff retry for errors (1m, 5m, 15m)
- Worker processes for decoupled processing (#2)
  - `FileProcessorWorker`: picks pending files → extracts → fetches metadata → moves → marks moved
  - `EmbyUpdaterWorker`: picks moved files → scans Emby → updates metadata → uploads images → marks completed
  - `RetryHandler`: automatic retry for errors with exponential backoff
  - `WorkerManager`: lifecycle management with graceful shutdown (SIGTERM/SIGINT)
- Image upload to Emby (#1)
  - Downloads and uploads Primary, Backdrop, Banner images from WordPress
  - Prefers `image_cropped`, falls back to `raw_image_url`
  - Best-effort upload (failures logged, don't block completion)
  - Integrated in both `pipeline.py` and `EmbyUpdaterWorker`
- Retry polling for Emby item lookup (#3)
  - `EmbyClient.get_item_by_path_with_retry()`: exponential backoff (2s, 4s, 8s, 16s, 32s, 64s)
  - Replaces fixed 10s sleep + single attempt
  - Dramatically reduces time from file move to Emby indexing
- Targeted Emby scan endpoint (#3)
  - Uses `parent_folder_id` (EMBY_PARENT_FOLDER_ID=4) for recursive scan
  - Avoids full library scan, faster indexing
- CLI for queue management (#2)
  - Commands: `status`, `list`, `retry`, `retry-all`, `cleanup`, `reset`
  - Entry point: `python -m src`
  - Real-time visibility into processing pipeline
- Comprehensive test coverage
  - 152 tests passing (up from 45)
  - New test suites: `test_queue.py` (24), `test_workers.py` (25), `test_cli.py` (50)
  - Enhanced `test_emby_client.py` (8 new tests for retry polling and image upload)

### Changed
- Watcher integration: file events now call `queue_db.add()` instead of `pipeline.process()`
- Architecture updated to PostgreSQL-based queue (ARCHITECTURE.md reflects new design)
- `docker-compose.yml`: removed deprecated `version` field

### Fixed
- Security: removed hardcoded API keys from DEPLOY.md and test files
- Entry point documentation: corrected to `python -m src` in all references

## [0.3.0] — 2026-02-15

Phase 3: Emby Integration — processed files are automatically registered in Emby with correct metadata.

### Added
- Emby metadata update integration: writes WordPress metadata to Emby items (#8)
  - `EmbyClient.get_item_by_path()`: Find Emby item by file path
  - `EmbyClient.get_item_details()`: Retrieve full item metadata
  - `EmbyClient.update_item_metadata()`: Update item with WordPress API data
  - Field mapping: actress→People, genre→GenreItems, label→Studios
  - Sets `LockData: true` to prevent Emby from overwriting metadata
  - Pipeline now waits for Emby scan, finds item, and updates metadata after file move
- Test documentation: `test_emby_simple.md` and `test_emby_update.md` with detailed checklists
- Reference implementation: `googlescript_legacy/` JavaScript code for field mapping specs

### Fixed
- Title casing: apply `.title()` for proper capitalization after stripping movie code (#8)
- Duplicate movie code in filenames: strip code from title if already present (#8)

## [0.1.0] — 2026-02-15

Phase 1: Core Pipeline — files dropped in the watch folder are automatically
renamed with metadata and moved to actress-organized folders.

### Added
- Movie code extraction from filenames via regex (`SONE-760`, `JUR-589`, etc.) (#1)
- Subtitle language detection from filename keywords (English Sub, Chinese Sub, No Sub) (#1)
- WP REST API metadata client with configurable search order: MissAV first, JavGuru fallback (#2)
- Filename builder: `{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}` with sanitization and truncation (#3)
- Case-insensitive actress folder matching against existing destination folders (#3)
- watchdog-based folder monitor with file stability check (polls size until stable) (#4)
- Pipeline orchestrator: extractor → metadata → renamer → move (#5)
- Error handling: no movie code or API failure → move to `errors/` subfolder with log (#5)
- Docker setup: Python 3.12-slim image, volume mounts for watch/destination dirs, shared WP network (#6)
- Configuration via `config.yaml`: paths, API URL/token, search order, stability settings (#6)
- Unit tests for extractor (11 tests) and renamer (12 tests) — 36 total passing (#7)
