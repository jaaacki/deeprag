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

## 2026-02-15 — Emby Metadata Integration

### Why this design — Modify-and-POST pattern instead of direct field updates

The Emby API doesn't support PATCH requests for individual fields. To update metadata, you must:
1. GET the full item object via `/Items/{itemId}`
2. Modify the fields you want to change in the returned object
3. POST the entire modified object back to `/Items/{itemId}`

This is counter-intuitive (why GET if you're just updating?), but it's how Emby's API works. The JavaScript reference implementation (`googlescript_legacy/items.js`) confirms this pattern. Key insight: **always fetch first, modify, then post back**. Directly constructing an update object without the existing data will fail validation or lose unrelated fields.

### What just happened — Field mapping from WordPress to Emby

Implemented `EmbyClient.update_item_metadata()` to map WordPress API responses to Emby's expected format:

| WordPress Field | Emby Field | Transformation |
|----------------|------------|----------------|
| `original_title` | `OriginalTitle` | Direct string copy |
| `overview` | `Overview` | Direct string copy |
| `release_date` | `ProductionYear` | Extract year: `int(date.split('-')[0])` |
| `release_date` | `PremiereDate` | ISO date string (no change) |
| `actress[]` | `People[]` | Array → `[{Name: name, Type: "Actor"}]` |
| `genre[]` | `GenreItems[]` | Array → `[{Name: genre}]` |
| `label` | `Studios[]` | String → `[{Name: label}]` |

Critical: **`LockData: true`** must be set, or Emby will overwrite the metadata during library scans. Without this flag, Emby's auto-tagging replaces actress names, genres, and titles with its own scrapers' data.

### What just happened — Timing is everything

The pipeline flow now includes a 10-second wait between triggering an Emby scan and attempting to find the item by path. This is necessary because:
1. Moving the file to destination doesn't immediately register in Emby
2. Triggering a scan is asynchronous (API returns 204 immediately, but scanning happens in background)
3. The item must be indexed before `get_item_by_path()` can find it

The 10-second wait is a heuristic. For large libraries or slow storage, this may be insufficient. Future improvement: poll `/Items?Path={path}` with retries until the item appears, instead of a fixed sleep.

### What could go wrong — Race condition with Emby's auto-metadata

If Emby's own metadata agents (TheMovieDB, etc.) run before our `update_item_metadata()` call, they may set fields that we then overwrite. Worse: if `LockData` is false or not set, Emby will overwrite our data on the next scan. The current implementation sets `LockData: true`, but this only works if the update happens **before** Emby's auto-tagging completes. The 10-second wait may not be enough for slow systems. Consider disabling Emby's metadata agents for the library entirely, or setting LockData immediately after scan detection.

### What could go wrong — Item not found by path

`get_item_by_path()` searches for items where `Path` matches the file path. This assumes:
1. Emby has already indexed the file (requires scan completion)
2. The path is an exact match (case-sensitive on Linux, case-insensitive on Windows)
3. Emby hasn't renamed or moved the file internally

If the item isn't found, the pipeline logs an error but doesn't retry. The file is successfully moved, but metadata is missing in Emby. Phase 2 should add retry logic with exponential backoff for `get_item_by_path()`, or fall back to searching by filename if path search fails.

## 2026-02-15 — Gap Analysis vs Google Script Legacy

### Why this matters — Understanding the legacy requirements

Analyzed the complete `googlescript_legacy/` implementation to identify gaps. The legacy system is fundamentally different:
- **Architecture**: Webhook-driven batch processor using Google Sheets as a database
- **Scope**: Processes entire existing Emby library + responds to Emby webhooks
- **Features**: Image upload, state tracking, actress aliases, scout mode

The Python implementation is a **file-watcher pipeline** that only processes new files as they arrive. This is intentional for the initial release, but several production features are missing.

### Critical gaps identified

**1. Image Upload** (High Priority)
- Legacy downloads images from WordPress (`image_cropped`, `raw_image_url`)
- Converts to base64 or binary
- Deletes existing images: `DELETE /Items/{id}/Images/{type}/{index}`
- Uploads 3 types: Primary (original), Backdrop (W800), Banner (W800)
- Uses `POST /Items/{id}/Images/{type}?api_key={key}` with binary payload
- **Impact**: Videos have no poster images in Emby, visually incomplete library

**2. State Tracking** (High Priority)
- Legacy uses Google Sheets to track every item: Id, MovieCode, missAv_status, Processed (checkbox), error messages
- Benefits: See processing status, retry failed items, avoid re-processing, audit trail
- Python is stateless: no memory between runs, errors lost in logs, can't resume
- **Impact**: No visibility, no retries, potential re-processing

**3. Batch Mode** (High Priority)
- Legacy can process entire library: `getParentFolders()` → `getParentChildFolders()` → `populateItemDetails()` → `getMissAvData()` → `updateEmbyItems()`
- Queries Emby for all items under ParentId=4 (root library folder)
- Python only handles new files
- **Impact**: Can't fix existing library, can't re-process after API improvements

**4. Emby Webhooks** (Medium Priority)
- Legacy receives `library.new` and `library.deleted` webhooks from Emby
- Processes items added outside watch directory (manual imports, batch scans)
- Syncs deletions to Google Sheets
- **Impact**: Limited to watched directory, can't respond to Emby events

**5. Actress Alias Mapping** (Medium Priority)
- Legacy has `actressAlias` sheet for romanization variations (Saijo vs Saijou, Yua Mikami vs Mikami Yua)
- Python creates duplicate folders for different spellings
- **Impact**: Inconsistent organization, multiple folders per actress

### What we learned — WordPress API endpoints

Legacy uses additional endpoints:
- `/wp-json/emby/v1/missavdetails/` — Get metadata by URL (not movie code)
- `/wp-json/emby/v1/missavscout` — Scout URLs for new content to download

Python only uses `/missavsearch/` and `/javguru/search`.

### What we learned — Image upload implementation details

From `googlescript_legacy/items.js` lines 371-388:
1. Delete existing images (Primary, Backdrop, Banner, Logo) — clean slate
2. Convert image URL to base64: `Util.convertBase64FromUrl(url)`
3. For Backdrop/Banner: resize to W800: `Util.convertBase64FromUrlW800(url)`
4. Upload with `POST /Items/{id}/Images/{type}?api_key={key}`
5. Content-Type: `image/jpeg` or detect from source
6. Payload: clean base64 string (strip data URI prefix, remove whitespace)

Critical: Use `?api_key={key}` in URL, not X-Emby-Token header, for image uploads.

### Priority recommendation

Based on gap analysis (see `GAP_ANALYSIS.md`):
1. **Phase 3 completion**: Image upload (2-3 days)
2. **Phase 4**: State tracking (3-4 days), Batch mode (4-5 days)
3. **Phase 5**: Emby webhooks (5-7 days), Actress aliases (1-2 days)

The file-watcher pipeline is a solid v0.1, but needs image upload + state tracking for production readiness.
