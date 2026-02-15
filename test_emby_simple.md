# Test: Emby API Simple Verification

## Purpose
Verify Emby API endpoints are accessible and responding correctly using curl commands.

## Prerequisites
- Emby server running and accessible
- Valid API key configured
- Item ID to test with

## Test Environment
- **Emby URL**: `https://emby.familyhub.id`
- **API Key**: From `.env` (EMBY_API_KEY)
- **Test Item ID**: Provide an existing item ID

## Test Checklist

| # | Test Case | Command | Expected Result | Status | Notes |
|---|-----------|---------|-----------------|--------|-------|
| 1 | System connectivity | `curl -s 'https://emby.familyhub.id/System/Info' -H 'X-Emby-Token: {API_KEY}'` | HTTP 200, JSON with system info | ⬜ | Validates API key and connectivity |
| 2 | Get item details | `curl -s 'https://emby.familyhub.id/Items/{ITEM_ID}' -H 'X-Emby-Token: {API_KEY}'` | HTTP 200, JSON with item metadata | ⬜ | Item must exist in Emby |
| 3 | Verify item fields | Check response for: `Name`, `OriginalTitle`, `Overview`, `People`, `Studios`, `GenreItems` | All fields present (may be empty) | ⬜ | Validates item structure |
| 4 | Get full item JSON | Save item to file: `curl -s '...' > /tmp/item.json` | File created with valid JSON | ⬜ | Needed for update test |
| 5 | Modify item metadata | `jq '.OriginalTitle = "Test" \| .LockData = true' /tmp/item.json > /tmp/update.json` | Modified JSON file created | ⬜ | Prepares update payload |
| 6 | POST updated metadata | `curl -X POST 'https://emby.familyhub.id/Items/{ITEM_ID}' -H 'X-Emby-Token: {API_KEY}' -H 'Content-Type: application/json' -d @/tmp/update.json` | HTTP 204 (No Content) or 200 | ⬜ | Update accepted by Emby |
| 7 | Verify update applied | `curl -s 'https://emby.familyhub.id/Items/{ITEM_ID}' -H 'X-Emby-Token: {API_KEY}' \| jq '.OriginalTitle, .LockData'` | Shows updated values | ⬜ | Confirms metadata persisted |
| 8 | Check LockData flag | Verify `.LockData` is `true` | `true` | ⬜ | Prevents Emby from overwriting |

## Passing Criteria

### Required (Must Pass)
- ✅ Tests 1-4: API connectivity and item retrieval working
- ✅ Test 6: POST request accepted (HTTP 2xx)
- ✅ Test 7: Updated values visible in subsequent GET

### Optional (Should Pass)
- ✅ Test 5: jq successfully modifies JSON
- ✅ Test 8: LockData flag set correctly

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| HTTP 401 Unauthorized | Invalid API key | Check EMBY_API_KEY in .env |
| HTTP 404 Not Found | Item doesn't exist | Use existing item ID or trigger scan |
| Invalid JSON in response | Wrong endpoint or API version | Check Emby server version |
| POST returns 400 | Malformed JSON payload | Validate JSON with `jq '.' file.json` |
| Update not persisting | LockData not set | Ensure `"LockData": true` in payload |

## Running the Tests

```bash
# Set variables
export EMBY_URL="https://emby.familyhub.id"
export API_KEY="your-api-key-here"
export ITEM_ID="10249"  # Use actual item ID

# Run test script
python3 test_emby_simple.py

# Or run manually:
# Test 1: System Info
curl -s "$EMBY_URL/System/Info" -H "X-Emby-Token: $API_KEY" | jq .

# Test 2: Get Item
curl -s "$EMBY_URL/Items/$ITEM_ID" -H "X-Emby-Token: $API_KEY" | jq .

# Test 6: Update Item
curl -s "$EMBY_URL/Items/$ITEM_ID" -H "X-Emby-Token: $API_KEY" > /tmp/item.json
jq '.OriginalTitle = "Test Title" | .LockData = true' /tmp/item.json > /tmp/update.json
curl -X POST "$EMBY_URL/Items/$ITEM_ID" \
  -H "X-Emby-Token: $API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/update.json
```

## Test Results

| Date | Tester | Pass/Fail | Item ID | Notes |
|------|--------|-----------|---------|-------|
| YYYY-MM-DD | | ⬜ PASS / ❌ FAIL | | |
