# Gap Analysis: googlescript_legacy vs Python Implementation

## Executive Summary

The Google Script legacy system is a **webhook-driven, batch-processing, Google Sheets-based metadata management system**. The current Python implementation is a **file-watcher pipeline that processes new files one at a time**.

**Fundamental Difference**: The legacy system processes the **entire existing Emby library** and responds to Emby webhooks. The Python system only processes **new files as they arrive**.

---

## Architecture Comparison

| Aspect | Legacy (Google Script) | Current (Python) | Status |
|--------|----------------------|------------------|--------|
| **Trigger** | Emby webhooks (`library.new`, `library.deleted`) | File system watcher (inotify) | ❌ Different |
| **Storage** | Google Sheets (database) | None (stateless) | ❌ Missing |
| **Processing** | Batch (entire library) + event-driven | Real-time (new files only) | ❌ Different |
| **Workflow** | Pull from Emby → Update Emby | Process file → Move → Update Emby | ❌ Different |

---

## Feature Gap Analysis

### ✅ Implemented Features

| Feature | Legacy | Python | Notes |
|---------|--------|--------|-------|
| Movie code extraction | ✅ | ✅ | Both use regex `[A-Za-z]{2,6}-\d{1,5}` |
| Subtitle detection | ✅ | ✅ | Both scan for keywords (english, chinese) |
| WordPress API search | ✅ | ✅ | Both use `/missavsearch/` endpoint |
| Filename building | ✅ | ✅ | Similar format: `{Actress} - [{Sub}] {Code} {Title}` |
| Actress folder organization | ✅ | ✅ | Both create/match folders |
| Emby library scan trigger | ✅ | ✅ | Both call `/Items/{id}/Refresh` |
| Emby metadata update | ✅ | ✅ | Both POST to `/Items/{id}` |
| Token refresh | ✅ | ✅ | Both use `/tokens/refresh` |

### ❌ Missing Features (Critical)

| Feature | Legacy | Python | Gap Details |
|---------|--------|--------|-------------|
| **Emby webhook integration** | ✅ | ❌ | Legacy receives `library.new`/`library.deleted` events from Emby |
| **Batch library processing** | ✅ | ❌ | Legacy can process entire existing library, Python only handles new files |
| **Image upload to Emby** | ✅ | ❌ | Legacy downloads images from WordPress, uploads to Emby (Primary, Backdrop, Banner) |
| **State tracking** | ✅ | ❌ | Legacy uses Google Sheets to track which items are processed/completed/error |
| **Actress alias mapping** | ✅ | ❌ | Legacy has `actressAlias` sheet for name variations (e.g., "Saijo" vs "Saijou") |
| **Scout mode** | ✅ | ❌ | Legacy can scan missav.ws for new content and queue downloads |

### ⚠️ Missing Features (Important)

| Feature | Legacy | Python | Gap Details |
|---------|--------|--------|-------------|
| **Parent folder discovery** | ✅ | ❌ | Legacy fetches all actress folders from Emby (ParentId=4) |
| **Item synchronization** | ✅ | ❌ | Legacy removes deleted items from tracking |
| **Retry logic for metadata** | ✅ | ❌ | Legacy tracks `missAv_status` (completed/error) and retries |
| **Scheduled triggers** | ✅ | ❌ | Legacy creates time-based triggers for batch jobs |
| **WordPress details endpoint** | ✅ | ❌ | Legacy uses `/missavdetails/` for URL-based lookups |
| **Multiple search strategies** | ✅ | ❌ | Legacy uses search + details + scout endpoints |

### 📊 Different Implementation

| Feature | Legacy Implementation | Python Implementation | Impact |
|---------|---------------------|---------------------|--------|
| **Processing flow** | Emby → Google Sheets → WordPress → Emby | File → WordPress → Emby | Python can't process existing library |
| **Error handling** | Tracked in sheet, manual retry | Move to errors/ folder | Python errors require file system inspection |
| **Metadata updates** | Batch update (updateItemAll) | One at a time | Python slower for bulk updates |
| **Item discovery** | Query Emby for all items | Wait for file events | Python reactive, not proactive |

---

## Detailed Feature Breakdowns

### 1. Image Upload (CRITICAL GAP)

**Legacy**:
```javascript
// Downloads image from WordPress, converts to base64
const base64 = Util.convertBase64FromUrl(obj.missAv_image_cropped);
// Uploads to Emby
EmbyService.uploadImage(obj.Id, 'Primary', base64);
EmbyService.uploadImage(obj.Id, 'Backdrop', base64W); // W800 version
EmbyService.uploadImage(obj.Id, 'Banner', base64W);
```

**Python**: ❌ Not implemented

**Impact**: Videos in Emby have no poster images, making the library visually incomplete.

**Effort to implement**: Medium
- Fetch image URL from WordPress metadata
- Download image (handle base64 or direct upload)
- POST to `/Items/{id}/Images/{type}` with proper MIME type
- Handle multiple image types (Primary, Backdrop, Banner)

---

### 2. Emby Webhook Integration (CRITICAL GAP)

**Legacy**:
```javascript
// Receives webhook from Emby
function entryPoint(e) {
  const payload = JSON.parse(e.postData.contents);
  if (payload.Event === 'library.new') {
    // Save item to Google Sheets
    // Trigger metadata fetch
  }
  if (payload.Event === 'library.deleted') {
    // Remove from tracking
  }
}
```

**Python**: ❌ Not implemented

**Impact**:
- Can't respond to library changes (manual imports, deletions)
- Can't process files added outside the watch directory
- No integration with Emby's native workflow

**Effort to implement**: High
- Add Flask/FastAPI HTTP server
- Expose webhook endpoint
- Configure Emby to send webhooks
- Handle event types (library.new, library.deleted, playback.start, etc.)
- Integrate with existing pipeline

---

### 3. Batch Library Processing (CRITICAL GAP)

**Legacy**:
```javascript
// Process ALL items in Emby library
function getParentFolders() {
  const response = EmbyService.getItems('ParentId=4&IsFolder=true');
  // Returns all actress folders
}

function getParentChildFolders() {
  // For each folder, get all videos
  // Populate items sheet with all IDs
}

function populateItemDetails() {
  // Fetch details for all items from Emby
}

function getMissAvData() {
  // Search WordPress for all movie codes
}

function updateEmbyItems() {
  // Update all items with metadata
}
```

**Python**: ❌ Not implemented

**Impact**:
- Can't process existing library (videos already in Emby before Python service started)
- Can't fix metadata for files that were processed with errors
- Can't re-process after WordPress API improvements

**Effort to implement**: High
- Query Emby for all items in library
- Extract movie codes from file paths
- Search WordPress for each code
- Update metadata for each item
- Handle rate limiting and timeouts
- Add CLI command for batch mode

---

### 4. State Tracking (IMPORTANT GAP)

**Legacy**:
- **Google Sheets as database**: Tracks every item with status
- **Columns**: Id, MovieCode, missAv_status, Processed (checkbox), etc.
- **Benefits**:
  - See which items need processing
  - Retry failed items
  - Avoid re-processing
  - Audit trail

**Python**: ❌ No state (stateless)

**Impact**:
- No way to know if an item was already processed
- Errors are lost (just in logs)
- Can't resume after restart
- No visibility into processing status

**Effort to implement**: Medium
- Add SQLite database or JSON file storage
- Track: file_path, movie_code, emby_item_id, status, error_message, processed_at
- Add CLI commands to view/reset state
- Integrate state checks into pipeline

---

### 5. Actress Alias Mapping (IMPORTANT GAP)

**Legacy**:
- **Google Sheet**: `actressAlias` with mappings
- **Purpose**: Handle romanization variations
  - "Ruri Saijo" vs "Ruri Saijou"
  - "Yua Mikami" vs "Mikami Yua"
  - Different spellings from different sources

**Python**: ❌ Not implemented

**Impact**:
- Multiple folders for same actress with different spellings
- Inconsistent organization

**Effort to implement**: Low-Medium
- Create alias mapping file (YAML/JSON)
- Lookup canonical name before creating folder
- Optional: fuzzy matching for auto-suggestions

---

### 6. Scout Mode (NICE-TO-HAVE GAP)

**Legacy**:
```javascript
// Scan missav.ws for new content
function scoutNewUrls() {
  const url = Me.ScoutList.where(r => r['processed?'] === false).first();
  const newLinks = getNewScoutMissAv(url.url); // Calls WordPress scout endpoint
  // Save new URLs to fetchMissAvRemote sheet
}

// Fetch metadata for scouted URLs
function fetchMissAvDetails() {
  const rows = Me.FetchMissAvRemote.where(r => r['processed?'] === false).all();
  rows.forEach(r => {
    const result = getMissAvDetails(r.detailsUrl); // Calls WordPress details endpoint
  });
}
```

**Python**: ❌ Not implemented

**Impact**:
- Can't proactively discover new content
- Manual download management required

**Effort to implement**: High (separate feature)

---

## WordPress API Endpoint Comparison

| Endpoint | Legacy | Python | Purpose |
|----------|--------|--------|---------|
| `/missavsearch/` | ✅ | ✅ | Search by movie code |
| `/javguru/search` | ✅ | ✅ | Fallback search |
| `/missavdetails/` | ✅ | ❌ | Get metadata by URL |
| `/missavscout` | ✅ | ❌ | Scout URLs for new content |
| `/tokens/refresh` | ✅ | ✅ | Refresh JWT token |

**Missing**: `/missavdetails/` and `/missavscout` endpoints not used in Python.

---

## Emby API Endpoint Comparison

| Endpoint | Legacy | Python | Purpose |
|----------|--------|--------|---------|
| `GET /Items` | ✅ | ✅ | Query items |
| `GET /Items/{id}` | ✅ | ✅ | Get item details |
| `POST /Items/{id}` | ✅ | ✅ | Update item metadata |
| `POST /Items/{id}/Refresh` | ✅ | ✅ | Trigger scan |
| `POST /Items/{id}/Images/{type}` | ✅ | ❌ | Upload image |
| `DELETE /Items/{id}/Images/{type}/{index}` | ✅ | ❌ | Delete image |
| `GET /Library/VirtualFolders` | ❌ | ✅ | Get libraries |
| `POST /Library/Refresh` | ❌ | ✅ | Scan all libraries |

**Key difference**: Legacy uses image endpoints heavily, Python doesn't.

---

## Processing Flow Comparison

### Legacy Flow (Batch Mode):
```
1. Manual trigger or schedule
   ↓
2. getParentFolders() → Fetch all actress folders from Emby
   ↓
3. getParentChildFolders() → Fetch all video IDs in each folder
   ↓
4. getChildItems() → Populate Google Sheets with item IDs
   ↓
5. populateItemDetails() → Fetch full metadata from Emby
   ↓
6. getMissAvData() → Search WordPress for each movie code
   ↓
7. updateEmbyItems() → Update Emby with WordPress metadata
   ↓
8. Upload images to Emby
```

### Legacy Flow (Webhook Mode):
```
1. Emby sends webhook (library.new)
   ↓
2. entryPoint() receives webhook
   ↓
3. Save item to Google Sheets
   ↓
4. Extract movie code from path
   ↓
5. Trigger immediate background job
   ↓
6. Search WordPress for metadata
   ↓
7. Update Emby with metadata
   ↓
8. Upload images
```

### Python Flow (File Watcher):
```
1. New file appears in /watch
   ↓
2. Wait for file stability
   ↓
3. Extract movie code from filename
   ↓
4. Search WordPress for metadata
   ↓
5. Rename file
   ↓
6. Move to /destination/{actress}/
   ↓
7. Trigger Emby scan
   ↓
8. Wait 10s
   ↓
9. Find item by path
   ↓
10. Update Emby with metadata
```

**Key differences**:
- Legacy processes existing library, Python only new files
- Legacy uses webhooks, Python uses file watcher
- Legacy has Google Sheets for state, Python is stateless
- Legacy uploads images, Python doesn't

---

## Priority Recommendations

### High Priority (Implement Soon):
1. **Image Upload** - Visual completeness of library
2. **State Tracking** - Prevent re-processing, enable retries
3. **Batch Mode** - Process existing library

### Medium Priority (Consider):
4. **Emby Webhooks** - Better integration with Emby workflow
5. **Actress Alias Mapping** - Fix folder duplication
6. **Error Retry Logic** - Automatic retry for failed items

### Low Priority (Future):
7. **Scout Mode** - Proactive content discovery
8. **WordPress details endpoint** - Alternative metadata source
9. **Scheduled Triggers** - Time-based batch jobs

---

## Implementation Effort Estimates

| Feature | Effort | Files to Modify | New Dependencies |
|---------|--------|-----------------|------------------|
| Image Upload | 2-3 days | `emby_client.py`, `pipeline.py` | None |
| State Tracking | 3-4 days | New `state.py`, `pipeline.py`, `main.py` | `sqlite3` (stdlib) |
| Batch Mode | 4-5 days | New `batch.py`, CLI additions | None |
| Emby Webhooks | 5-7 days | New `webhook.py`, `main.py`, docker-compose | `flask` or `fastapi` |
| Actress Aliases | 1-2 days | `renamer.py`, new `aliases.yaml` | None |
| Error Retry | 2-3 days | `pipeline.py`, `state.py` | None |

---

## Conclusion

The Python implementation covers the **core file processing pipeline** but is missing several **production-ready features** that the legacy system has:

1. **No image handling** - Library visually incomplete
2. **No state tracking** - Can't resume, retry, or audit
3. **No batch mode** - Can't process existing library
4. **No webhooks** - Not integrated with Emby's native events

**Recommendation**: Prioritize **image upload** and **state tracking** as the next features to implement for production readiness.
