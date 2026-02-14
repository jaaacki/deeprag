# Changelog

All notable changes to this project will be documented in this file.

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
