# Test: Emby Metadata Update (Python Client)

## Purpose
Verify the Python `EmbyClient` correctly updates Emby item metadata from WordPress API data.

## Prerequisites
- Emby server running and accessible
- Valid API key in `.env`
- Python 3.12+ with dependencies (`requests`, `python-dotenv`)
- Existing Emby item to test with
- WordPress API returning metadata for test movie code

## Test Environment
- **Script**: `test_emby_update.py`
- **Emby URL**: Auto-detected from `.env` (switches Docker internal URL to public)
- **Test Item**: User-provided item ID (default: 10249)
- **Test Movie Code**: SONE-760

## Test Checklist

| # | Test Case | Method | Expected Result | Status | Notes |
|---|-----------|--------|-----------------|--------|-------|
| 1 | Load environment | `.env` file parsing | EMBY_BASE_URL and EMBY_API_KEY loaded | ⬜ | Validates configuration |
| 2 | Create EmbyClient | `EmbyClient(base_url, api_key)` | Client instance created | ⬜ | No exceptions raised |
| 3 | Get item details | `client.get_item_details(item_id)` | Returns dict with item data | ⬜ | Logs current metadata |
| 4 | Verify item exists | Check returned dict has `Id` field | `Id` matches requested item | ⬜ | Item must be indexed |
| 5 | Create mock metadata | Build dict with WordPress-like fields | Dict with all required fields | ⬜ | See Mock Metadata section |
| 6 | Update item metadata | `client.update_item_metadata(item_id, metadata)` | Returns `True` | ⬜ | No API errors |
| 7 | Fetch updated item | `client.get_item_details(item_id)` again | Returns updated dict | ⬜ | Verify persistence |
| 8 | Verify OriginalTitle | Check `.OriginalTitle` field | Matches mock data | ⬜ | Text field update |
| 9 | Verify Overview | Check `.Overview` field | Matches mock data | ⬜ | Long text field |
| 10 | Verify ProductionYear | Check `.ProductionYear` field | Extracted from release_date (2025) | ⬜ | Date parsing |
| 11 | Verify PremiereDate | Check `.PremiereDate` field | Matches release_date | ⬜ | ISO date format |
| 12 | Verify People | Check `.People` array | Contains actress names with Type: "Actor" | ⬜ | Array mapping |
| 13 | Verify GenreItems | Check `.GenreItems` array | Contains genre names | ⬜ | Array of {Name} objects |
| 14 | Verify Studios | Check `.Studios` array | Contains label name | ⬜ | String to array |
| 15 | Verify LockData | Check `.LockData` field | `true` | ⬜ | Critical - prevents overwrites |
| 16 | Verify Language | Check `.PreferredMetadataLanguage` | "en" | ⬜ | Hardcoded value |
| 17 | Verify Country | Check `.PreferredMetadataCountryCode` | "JP" | ⬜ | Hardcoded value |

### Image Upload Tests (Phase 3 - Not Yet Implemented)

| # | Test Case | Method | Expected Result | Status | Notes |
|---|-----------|--------|-----------------|--------|-------|
| 18 | Fetch image URL | Extract from metadata | URL from WordPress | ⬜ | From `image_cropped` or `raw_image_url` |
| 19 | Download image | HTTP GET image URL | Binary image data | ⬜ | Handle redirects, validate MIME type |
| 20 | Delete existing images | `DELETE /Items/{id}/Images/{type}/{index}` | HTTP 204 | ⬜ | Clean slate before upload |
| 21 | Upload Primary image | `POST /Items/{id}/Images/Primary` | HTTP 204 | ⬜ | Original aspect ratio |
| 22 | Upload Backdrop image | `POST /Items/{id}/Images/Backdrop` | HTTP 204 | ⬜ | W800 variant |
| 23 | Upload Banner image | `POST /Items/{id}/Images/Banner` | HTTP 204 | ⬜ | W800 variant |
| 24 | Verify images visible | Check Emby web UI | Images display correctly | ⬜ | Manual verification |

## Mock Metadata Structure

```python
{
    'movie_code': 'SONE-760',
    'original_title': 'Test Original Title - 初めての背徳トライアングル',
    'overview': 'Test overview description for this video.',
    'release_date': '2025-01-07',
    'actress': ['Kaede Fua', 'Test Actress 2'],
    'genre': ['Drama', 'Romance'],
    'label': 'S1 NO.1 STYLE',
}
```

## Passing Criteria

### Critical (Must Pass All)
- ✅ Tests 1-6: Client setup, connection, and update executes without errors
- ✅ Test 15: `LockData` is `true` (prevents Emby from overwriting metadata)
- ✅ Test 8: `OriginalTitle` updated correctly

### Required (Must Pass ≥90%)
- ✅ Tests 7-14: All metadata fields update correctly
- ✅ Test 16-17: Language and country codes set

### Optional (Should Pass)
- ✅ Logs show detailed API responses
- ✅ No exceptions or warnings during execution

## Field Mapping Verification

| WordPress Field | Emby Field | Transformation | Test # |
|----------------|------------|----------------|--------|
| `original_title` | `OriginalTitle` | Direct string | 8 |
| `overview` | `Overview` | Direct string | 9 |
| `release_date` | `ProductionYear` | Extract year (int) | 10 |
| `release_date` | `PremiereDate` | ISO date string | 11 |
| `actress[]` | `People[]` | Array → `[{Name, Type: "Actor"}]` | 12 |
| `genre[]` | `GenreItems[]` | Array → `[{Name}]` | 13 |
| `label` | `Studios[]` | String → `[{Name}]` | 14 |
| (hardcoded) | `LockData` | `true` | 15 |
| (hardcoded) | `PreferredMetadataLanguage` | `"en"` | 16 |
| (hardcoded) | `PreferredMetadataCountryCode` | `"JP"` | 17 |

## Running the Test

### Local Testing (requires dependencies)
```bash
# Install dependencies
pip3 install requests python-dotenv

# Run test
./test_emby_update.py
# or
python3 test_emby_update.py

# Enter item ID when prompted (or use default)
```

### Docker Testing
```bash
# On NAS server
cd /volume3/docker/emby-processor

# Start container
docker-compose up -d

# Run test inside container
docker-compose exec emby_processor python3 test_emby_update.py
```

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "EMBY_BASE_URL not set" | Missing .env file | Create .env from .env.example |
| "Failed to get item details" | Item doesn't exist | Use existing item ID or trigger scan |
| "Update failed" | API error or auth issue | Check logs for HTTP status code |
| LockData still false | Field not in update payload | Check `update_item_metadata()` sets it |
| People array empty | Actress list empty or wrong format | Verify metadata dict has `actress` array |
| Update succeeds but fields unchanged | Not fetching fresh data | Ensure get_item_details() called after update |

## Example Output

```
INFO Creating Emby client: https://emby.familyhub.id
INFO Testing with item ID: 10249
INFO Step 1: Fetching current item details...
INFO Retrieved Emby item details for 10249
INFO Current item name: Kaede Fua - [English Sub] SONE-760...
INFO Current OriginalTitle:
INFO Current Overview:
INFO Current People: []

INFO Step 2: Creating mock metadata...
INFO Mock metadata:
INFO   movie_code: SONE-760
INFO   original_title: Test Original Title - 初めての背徳トライアングル
INFO   overview: Test overview description for this video.
INFO   release_date: 2025-01-07
INFO   actress: ['Kaede Fua', 'Test Actress 2']
INFO   genre: ['Drama', 'Romance']
INFO   label: S1 NO.1 STYLE

INFO Step 3: Updating Emby item metadata...
INFO Emby update response: status=204, body=
INFO Successfully updated Emby item 10249 metadata

INFO Step 4: Verifying the update...
INFO Updated OriginalTitle: Test Original Title - 初めての背徳トライアングル
INFO Updated Overview: Test overview description for this video.
INFO Updated ProductionYear: 2025
INFO Updated PremiereDate: 2025-01-07
INFO Updated People: ['Kaede Fua', 'Test Actress 2']
INFO Updated GenreItems: ['Drama', 'Romance']
INFO Updated Studios: ['S1 NO.1 STYLE']
INFO Updated LockData: True

INFO ✅ Test completed successfully!
```

## Test Results

| Date | Environment | Item ID | Pass/Fail | Issues | Notes |
|------|-------------|---------|-----------|--------|-------|
| YYYY-MM-DD | Local/Docker | | ⬜ PASS / ❌ FAIL | | |

## Integration with Pipeline

After this test passes, the full pipeline flow will be:
1. File moved to destination
2. Emby library scan triggered
3. Wait 10 seconds for indexing
4. `get_item_by_path()` to find item
5. `update_item_metadata()` with WordPress data ← **This test validates this step**
6. Metadata locked and persisted
