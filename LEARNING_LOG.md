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

## 2026-02-15 — Phase 4: Queue Database, Workers, and Image Upload

### Why this design — PostgreSQL with FOR UPDATE SKIP LOCKED

The queue database uses PostgreSQL with `FOR UPDATE SKIP LOCKED` instead of SQLite for three critical reasons:

1. **Concurrent worker safety**: Multiple worker processes claim items atomically without locking entire tables. SQLite's row-level locking with `BEGIN IMMEDIATE` would serialize all workers.
2. **Connection pooling**: `ThreadedConnectionPool` maintains 1-5 connections for workers to share. SQLite requires exclusive file locks per connection.
3. **JSONB for metadata**: Native JSON storage and indexing. SQLite would require TEXT serialization with no query support.

The `FOR UPDATE SKIP LOCKED` pattern:
```sql
SELECT * FROM processing_queue
WHERE status = 'pending'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED
```
Worker 1 locks row 5, Worker 2 skips it and takes row 6 — zero contention, zero blocking. This is impossible with SQLite's file-level locks.

### What just happened — Worker architecture decouples file and Emby operations

Three worker processes run in parallel:
- **FileProcessorWorker**: pending → processing → moved (file operations only)
- **EmbyUpdaterWorker**: moved → emby_pending → completed (Emby operations only)
- **RetryHandler**: error → pending (retry logic with exponential backoff)

Key insight: Separating file and Emby operations into independent workers prevents Emby API slowness from blocking file moves. The queue acts as a buffer — files can be moved immediately while Emby operations catch up asynchronously.

Benefits:
- File moves never wait for Emby scans or metadata updates
- Emby failures don't block new files from being processed
- Each worker can be scaled independently (run 2 FileProcessors, 1 EmbyUpdater)
- Retry logic is isolated and doesn't interfere with new files

### What just happened — Exponential backoff retry polling for Emby item lookup

The fixed 10-second sleep after triggering an Emby scan was unreliable — sometimes too short, sometimes too long. The new retry polling with exponential backoff (2s, 4s, 8s, 16s, 32s, 64s) adapts to Emby's actual indexing speed:

- Fast storage: finds item in 2-4s (first 1-2 retries)
- Slow storage or large libraries: uses full backoff up to 64s
- Total max wait: ~126s before giving up (was 10s fixed)

Implementation: `EmbyClient.get_item_by_path_with_retry()` replaces `time.sleep(10)` + single `get_item_by_path()` call. Dramatically improves reliability for large libraries.

### What just happened — Image upload with fallback priority

Images are uploaded in this order:
1. Try `image_cropped` from WordPress API (preferred, better quality)
2. Fall back to `raw_image_url` if cropped not available
3. Upload three types: Primary (original), Backdrop (W800), Banner (W800)

The upload is **best-effort**: failures are logged but don't block the item from being marked `completed`. Rationale: A video with metadata but no poster is better than a failed processing pipeline. Images can be retried later via CLI (`python -m src retry --status completed`).

### What could go wrong — Database connection exhaustion

The `ThreadedConnectionPool` has a max of 5 connections. If more than 5 threads try to get a connection simultaneously, they will block until a connection is released. This is unlikely with 3 workers (1 connection each), but could happen if workers are scaled up or if queries are slow.

Mitigation: Monitor connection usage via PostgreSQL `pg_stat_activity`. Increase `maxconn=` in pool if scaling beyond 5 concurrent workers.

### What could go wrong — Queue database grows unbounded

Completed items remain in the queue forever. After processing 10,000 files, the queue will have 10,000 rows. Queries will slow down without proper indexes.

Current mitigation: Indexes on `status`, `(status, next_retry_at)`, and `file_path UNIQUE` keep lookups fast up to ~100k rows. Beyond that, consider:
1. Periodic cleanup: `DELETE FROM processing_queue WHERE status = 'completed' AND updated_at < NOW() - INTERVAL '30 days'`
2. Archival: move old completed items to a separate `processing_history` table
3. Partitioning: partition by `created_at` month

The CLI `cleanup` command provides manual purging, but automatic cleanup via cron job or RetryHandler may be needed for high-volume production.

### What we learned — Testing worker interactions requires integration tests

Unit tests for individual workers (FileProcessorWorker, EmbyUpdaterWorker) pass, but integration bugs appeared when workers ran together:
- Worker 1 marks item `moved`, Worker 2 claims it immediately before Worker 1's transaction commits → duplicate processing
- Fixed by ensuring `UPDATE ... WHERE id = ?` uses the ID from the locked row, not a re-query

Lesson: Worker coordination bugs only appear in integration tests with real database transactions. The 24 queue integration tests (`test_queue.py`) catch these — unit tests alone are insufficient for concurrent systems.

## 2026-02-15 — Production Deployment & Critical Metadata Fix

### What just happened — WordPress media-crop endpoints return 404 with valid data

Discovered WordPress media-crop URLs return valid JPEG image data but with HTTP **404 status code** instead of 200. Testing revealed:

```bash
curl -H "Authorization: Bearer $TOKEN" "https://wp.familyhub.id/media-crop/3961?w=379&h=600"
# Status: 404 Not Found
# Content-Type: image/jpeg
# Body: 48KB valid JPEG data
```

This is a **WordPress bug** — the endpoint works but returns the wrong status code. Our code was calling `resp.raise_for_status()` which threw an exception on 404, preventing image downloads despite valid data being available.

**Fix**: Modified `download_image()` to check for valid image data (Content-Type: image/*, non-empty body) **regardless of status code**. If we get valid image data, accept it even with 404 status. This allows all three image types (Primary, Backdrop, Banner) to upload successfully.

Key lesson: **Always validate response content, not just status codes**. HTTP status codes can be incorrect, especially with custom WordPress endpoints.

### CRITICAL: Name field must come from filename, not WordPress title

The most critical bug in the entire system was incorrect Emby metadata mapping. The Emby `Name` field controls what title is displayed in the UI.

**What we did wrong**: Set `emby_item['Name'] = metadata.get('title', '')` using WordPress API's `title` field.

**What the legacy Google Script does** (googlescript_legacy/items.js:336):
```javascript
embyItem.Name = Util.getNameFromPath(obj.Path || '');  // Filename without extension!
embyItem.OriginalTitle = obj.missAv_original_title || '';  // Japanese
embyItem.SortName = Util.getNameFromPath(obj.Path || '');
embyItem.ForcedSortName = Util.getNameFromPath(obj.Path || '');
```

The legacy script extracts Name from the **file path** (renamed filename), NOT from WordPress title field! The `getNameFromPath()` function simply strips the directory and extension:

```javascript
getNameFromPath: function (path) {
  return path.replace(/^.*\//, '').replace(/\.[^/.]+$/, '')  // Remove path and extension
}
```

**Why this matters**: The renamed filename contains all the structured metadata we carefully build: `{Actress} - [{Sub}] {MOVIE-CODE} {Title}`. Using the WordPress title field loses this structure and shows incorrect titles in Emby.

**Correct mapping**:
- `Name`: Filename without extension (e.g., "Meguri (Meg Fujiura) - [English Sub] JUR-589 I Wanted My Wife To...")
- `OriginalTitle`: WordPress `original_title` (Japanese text)
- `SortName`: Same as Name
- `ForcedSortName`: Same as Name

**Fix**: Extract Name from `emby_item['Path']` by taking the last path component and removing the extension. This matches legacy behavior exactly.

### What we learned — Always check legacy implementation for field mappings

When implementing metadata mapping, we made assumptions about what fields should contain based on their names (`Name` = title, `OriginalTitle` = original). These assumptions were **wrong**.

The legacy Google Script has the definitive field mapping specification. Before implementing any Emby integration, we should:

1. **Read the legacy code first** — Don't guess field mappings
2. **Search for all field assignments** — Use grep to find every place a field is set
3. **Understand the transformations** — What functions like `getNameFromPath()` actually do
4. **Test against legacy behavior** — Compare Emby output between systems

This debugging session cost ~2 hours because we didn't check the legacy implementation first. The fix took 2 minutes once we found the correct mapping in the Google Script.

**Lesson**: Legacy code is the specification. Documentation and field names can be misleading. When migrating a system, the existing implementation is the source of truth for behavior, not assumptions or intuition.

### What could go wrong — Other field mappings may also be incorrect

We fixed `Name`, `SortName`, and `ForcedSortName`. But there are many other Emby fields we're setting:
- `Overview` — Are we using the right WordPress field?
- `People` — Is the actor type and structure correct?
- `GenreItems` — Are we transforming genre strings properly?
- `Studios` — Does label mapping match legacy?
- `ProductionYear` / `PremiereDate` — Date parsing assumptions?

**Action**: Audit ALL field mappings against `googlescript_legacy/items.js` lines 327-357 to verify they match. Don't assume our implementation is correct just because it "makes sense" — verify against legacy behavior.

### What we learned — Production testing reveals bugs unit tests miss

All unit tests passed, but production deployment with real files revealed two critical bugs (WordPress 404 handling, Name field mapping). Why?

1. **Unit tests mock external services** — We mocked WordPress responses with 200 status, missing the real 404 behavior
2. **Unit tests don't verify legacy compatibility** — We tested our logic, not compatibility with Google Script behavior
3. **Integration tests use test data** — Not real Emby instances with actual title display behavior

**Better testing strategy**:
- Integration tests with real WordPress and Emby instances (not mocks)
- Regression tests comparing output between legacy and new system
- Production smoke tests after deployment before marking complete
- Always test with real data from production, not synthetic test cases
