# Roadmap

## Phase 1 — Core Pipeline (v0.1.0)

> Files dropped in the watch folder are automatically renamed with metadata and moved to actress-organized folders.

- [x] Movie code extraction from filenames (#1)
- [x] Subtitle language detection from filenames (#1)
- [x] WP REST API metadata client with MissAV/JavGuru fallback (#2)
- [x] Filename builder with sanitization and truncation (#3)
- [x] Actress folder matching (case-insensitive) (#3)
- [x] File watcher with stability check (#4)
- [x] Pipeline orchestrator: extract → metadata → rename → move (#5)
- [x] Error handling: missing code, API failure → errors/ folder (#5)
- [x] Docker setup with volume mounts and shared network (#6)
- [x] Unit tests for extractor and renamer (#7)

## Phase 2 — Resilience & Observability (v0.6.0)

> The pipeline handles edge cases gracefully and operators can monitor its health.

- [ ] Structured logging with JSON output for Docker log drivers
- [x] Retry with exponential backoff for API failures (done in v0.4.0)
- [ ] Health check endpoint or file for Docker health monitoring
- [ ] Process existing files on startup (catch up after restart)
- [ ] Duplicate detection (skip files already in destination)
- [x] Metrics: Prometheus `/metrics` endpoint with pipeline counters, API timing, queue depth gauges, worker heartbeats
- [x] `/api/metrics-summary` JSON endpoint for dashboard (completed_24h, errors_24h, error_rate, avg_time)

## Phase 3 — Emby Integration (v0.3.0)

> Processed files are automatically registered in Emby with correct metadata.

- [x] Emby API client for library scan trigger (#8)
- [x] Metadata push to Emby (title, actress, genre, studios) (#8)
- [x] LockData flag to prevent Emby from overwriting metadata (#8)
- [x] Image upload to Emby (Primary, Backdrop, Banner) from WordPress (#1)
- [x] Targeted scan using parent_folder_id instead of full library scan (#3)
- [x] Retry polling with exponential backoff for item lookup (#3)
- [ ] NFO file generation as fallback metadata source

## Phase 4 — Production Features (v0.4.0)

> Essential features for production reliability and completeness.

- [x] State tracking: PostgreSQL queue database for processed items (#2)
  - Track: file_path, movie_code, metadata, status, error_message, retry_count, timestamps
  - Enable retries for failed items with exponential backoff
  - Prevent re-processing with unique file_path constraint
  - Worker processes for decoupled file and Emby operations
  - CLI for queue management (status, list, retry, cleanup, reset)
- [x] Error retry logic with exponential backoff (#2)
  - Automatic retry for errors (1m, 5m, 15m)
  - RetryHandler worker process
  - Max retries: 3 (configurable)
- [ ] Batch mode: Process entire existing Emby library (#10)
  - CLI command: `python -m src batch`
  - Query Emby for all items (ParentId from EMBY_PARENT_FOLDER_ID)
  - Extract movie codes from file paths
  - Search WordPress and update metadata
- [ ] Actress alias mapping (#11)
  - YAML config file: canonical name → [aliases]
  - Handle romanization variations (Saijo vs Saijou)
  - Fuzzy matching for auto-suggestions

## Phase 5 — Advanced Integration (v0.5.0)

> Deep integration with Emby workflow and proactive features.

- [ ] Emby webhook receiver (#13)
  - Flask/FastAPI HTTP server
  - Handle library.new, library.deleted events
  - Process items added outside watch directory
  - Sync deletions to state database
- [ ] WordPress details endpoint integration (#14)
  - Use /missavdetails/ for URL-based metadata lookup
  - Fallback when search by code fails
- [ ] Scout mode for proactive content discovery (#15)
  - Use /missavscout endpoint
  - Queue URLs for download

## Phase 6 — Dashboard & Download Integration (v0.5.0+)

> Trigger downloads and monitor processing from a single web UI.

- [x] yt-dlp download form on dashboard (#4)
  - URL + optional filename inputs, submit via `docker exec` into ytdlp container
  - Background thread execution with in-memory job tracking
  - Recent downloads table with status badges and auto-refresh
- [x] Web UI dashboard for processing status (completed earlier, formalized here)
- [x] Subtitle dropdown in download form (No Sub, English/Chinese/Korean/Japanese Sub)

## Phase 7 — Dashboard Redesign (v0.7.0)

> Production-quality dashboard with polished UX and full observability.

- [x] Dark cinematic theme with custom typography (Sora, DM Sans, JetBrains Mono)
- [x] 24h metrics strip (completed, errors, error rate, avg processing time)
- [x] Pipeline progress indicator with glow effects per item
- [x] Log level syntax highlighting (INFO/WARN/ERROR)
- [x] Image preview in item detail modal
- [x] Collapsible Downloads and Queue sections (localStorage persisted)
- [x] Dark/light theme toggle with flash prevention
- [x] Admin actions tucked into navbar dropdown
- [x] Mobile responsive layout

## Backlog

_Unplaced items — will be assigned to a phase when priorities are clearer._

- [ ] Manual retry for files in errors/
- [ ] Notification (webhook/Telegram) on processing success/failure
- [ ] Multi-language subtitle priority configuration
- [ ] Batch processing mode for existing libraries
