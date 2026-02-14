# Learning Log

## 2026-02-15 — Phase 1: Core Pipeline

### Why this design — Separate Python service instead of WP cron

The file processing pipeline runs as an independent Python Docker container rather than a WordPress cron job or WP-CLI command. Three reasons:

1. **watchdog** gives real-time file detection (inotify-backed on Linux). WP cron only fires on HTTP requests, so files could sit for minutes or hours without a visitor.
2. Python's `shutil`, `pathlib`, and regex are better suited for filesystem operations than PHP's equivalents.
3. The container runs on the same Docker network as WordPress, so it can hit the REST API internally (`http://wpfamilyhubid_nginx/wp-json/...`) with zero external exposure.

The trade-off: a second runtime (Python) in the stack. Acceptable because the container is 50MB (slim image) and stateless — it reads config from a mounted YAML file and talks to the existing WP API for metadata.

### What just happened — Pipeline modules implemented

Five modules, each with a single responsibility:

- **extractor.py** — regex for movie codes (`[A-Za-z]{2,6}-\d{1,5}`) and keyword scan for subtitle language. Operates on filename stem only, never touches file contents.
- **metadata.py** — `MetadataClient` POSTs to `/emby/v1/{source}/search` with the movie code. Iterates through `search_order` (default: missav → javguru). Returns the `data` dict from the first successful response or `None`.
- **renamer.py** — builds `{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}`, sanitizes invalid chars, truncates title if filename exceeds 200 chars. `find_matching_folder()` does case-insensitive comparison against existing actress directories to avoid duplicates like "Ruri Saijo" vs "ruri saijo".
- **pipeline.py** — orchestrates the flow: extract → search → rename → move. On failure (no code, no metadata), moves file to `errors/` subfolder. Retries API search once before giving up.
- **watcher.py** — `watchdog.Observer` watches for `FileCreated` and `FileMoved` events. `StabilityChecker` polls file size twice with a configurable interval to ensure yt-dlp has finished writing before processing.

Key insight: the stability check is essential because yt-dlp writes files incrementally. Without it, the pipeline would process half-written files. Two consecutive size checks with a 5-second gap catches even slow connections.

### What could go wrong — Actress name variations

The `find_matching_folder()` function uses simple case-insensitive comparison. This handles "Ruri Saijo" vs "ruri saijo" but NOT romanization variations like "Saijou" vs "Saijo" or "Yua Mikami" vs "Mikami Yua" (name order). The API returns actress names in a specific format, and existing folders may use a different romanization. For now, this creates separate folders for the same actress with different spellings. Phase 2 should consider fuzzy matching (Levenshtein distance or similar) or a canonical name lookup table.

### What could go wrong — API availability on container startup

The emby-processor container may start before the WordPress stack is ready (depends on Docker Compose startup order). The first file detection could hit an unavailable API. The current retry-once logic handles transient failures, but a sustained outage during startup would send files to `errors/`. Phase 2 should add a startup health check that waits for the API to respond before starting the watcher.
