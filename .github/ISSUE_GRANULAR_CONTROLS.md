# Issue: Add Granular Pipeline Controls with UI Feedback

## Problem
Current dashboard buttons:
- ❌ No visual feedback (uses blocking `alert()` dialogs)
- ❌ No loading states
- ❌ Only 2 actions: full retry or metadata update
- ❌ Can't trigger individual pipeline steps

## Pipeline Steps Breakdown

```
pending → processing → moved → emby_pending → completed
           │              │           │
           ▼              ▼           ▼
    [FileProcessor]  [File Move]  [EmbyUpdater]
```

**FileProcessor Worker:**
1. Extract movie code & subtitle from filename
2. Fetch metadata from WordPress API
3. Rename & move file to actress folder
4. Status: pending → moved

**EmbyUpdater Worker:**
5. Trigger Emby library scan
6. Find item and update metadata in Emby
7. Status: moved → completed

## Requirements

### 1. New Granular API Endpoints

All under `/api/queue/{item_id}/actions/`:

- **POST `/extract-code`** - Re-extract movie code and subtitle from current filename
  - Updates: `movie_code`, `subtitle` fields
  - Requires: file still exists

- **POST `/fetch-metadata`** - Re-fetch metadata from WordPress API
  - Requires: `movie_code` present
  - Updates: `metadata_json`

- **POST `/rename-file`** - Re-rename and move file using current metadata
  - Requires: `metadata_json` present, file exists
  - Updates: `new_path`, status to 'moved'

- **POST `/update-emby`** - Re-trigger Emby scan and metadata update
  - Requires: `new_path` present (file already moved)
  - Same as current `/reprocess-metadata`

- **POST `/full-retry`** - Reset to pending (full pipeline retry)
  - Same as current `/retry`

### 2. UI Improvements

**Toast Notifications:**
- Replace `alert()` with Bootstrap toast notifications
- Show: success (green), error (red), info (blue), warning (yellow)
- Auto-dismiss after 3 seconds (closable)
- Position: top-right corner

**Button Loading States:**
- Disable button when clicked
- Show spinner icon while processing
- Re-enable after response
- Show different icon for success/failure

**Action Dropdown:**
Replace current buttons with dropdown menu showing:
- View Details (eye icon)
- **Granular Actions (for error/completed items):**
  - Re-extract Code → Extract
  - Re-fetch Metadata → Fetch
  - Re-rename & Move → Move
  - Re-update Emby → Emby
  - Full Retry → Retry All
  - Dividers between logical groups

**Status Indicators:**
- Show which step failed (in error items)
- Highlight available actions based on current state

### 3. Implementation Files

**Backend:**
- `src/api.py` - Add 5 new endpoints
- `src/extractor.py` - Already has extract functions
- `src/metadata.py` - Already has search function
- `src/renamer.py` - Already has build_filename, move_file
- `src/emby_client.py` - Already has scan and update functions

**Frontend:**
- `src/static/dashboard.html` - Add toast container, update buttons, loading states

## Acceptance Criteria

- [x] All 5 granular endpoints implemented
- [x] Toast notifications replace all `alert()` calls
- [x] Buttons show loading state (spinner + disabled) during action
- [x] Action dropdown shows context-appropriate options
- [x] Each action provides clear success/error feedback
- [x] Manual test: trigger each action and verify it works
- [x] Logs show action execution
- [x] Dashboard auto-refreshes after action completes

## Testing Checklist

1. Create error item (missing metadata)
2. Use "Re-fetch Metadata" action
3. Verify toast notification appears
4. Verify button shows loading state
5. Verify success/error toast with message
6. Verify queue refreshes automatically
7. Repeat for all 5 actions

## Dependencies

- Bootstrap 5 (already included) - has built-in toast component
- FastAPI (already included)
- Existing worker code (already has all sub-functions)
