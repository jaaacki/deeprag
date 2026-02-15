# FastAPI Dashboard for Queue Monitoring and Manual Controls

## Overview
Add a web-based dashboard for real-time monitoring and manual control of the emby-processor queue and operations.

## Requirements

### Backend (FastAPI)
- **Framework**: FastAPI with uvicorn
- **Listen**: `0.0.0.0:8000` (LAN accessible, no auth needed)
- **Endpoints**:
  - `GET /` - Serve single-page HTML dashboard
  - `GET /api/health` - System health (workers status, DB connection)
  - `GET /api/stats` - Queue statistics (total, completed, pending, error, processing)
  - `GET /api/queue` - List queue items with pagination and filters (status, movie_code, actress)
  - `GET /api/queue/{id}` - Get specific item details (full metadata JSON)
  - `POST /api/queue/{id}/retry` - Manually retry failed item
  - `POST /api/queue/{id}/reprocess-metadata` - Re-fetch metadata and update Emby
  - `GET /api/logs` - Stream recent logs (SSE or WebSocket)
  - `POST /api/cleanup` - Trigger cleanup of old completed items

### Frontend (Single HTML Page)
- **Auto-refresh**: Poll `/api/stats` and `/api/queue` every 5 seconds
- **Dashboard sections**:
  1. **Health Status**: Worker status, DB connection, system info
  2. **Stats Cards**: Total processed, Completed, Pending, Errors, Currently processing
  3. **Queue Table**:
     - Columns: ID, Movie Code, Actress, Status, Emby ID, Created, Actions
     - Filters: Status dropdown, search by movie code/actress
     - Pagination: 50 items per page
     - Action buttons: Retry (for errors), View Details
  4. **Item Detail Modal**: Shows full metadata JSON, file paths, error messages
  5. **Live Logs**: Scrollable log viewer with auto-scroll, last 100 lines
  6. **Manual Actions Panel**: Cleanup button, refresh all button

### Design
- **Styling**: Simple, clean (Bootstrap or Tailwind via CDN)
- **Charts**: Optional simple bar chart for status distribution (Chart.js via CDN)
- **Responsive**: Works on desktop and tablet
- **No build step**: Pure HTML/CSS/JS (no npm, no webpack)

## Implementation Plan

### Phase 1: Backend API
1. Add dependencies: `fastapi`, `uvicorn[standard]`, `python-multipart`
2. Create `src/api.py`:
   - FastAPI app initialization
   - All API endpoints
   - Database queries using existing `QueueDB` class
   - CORS middleware (if needed)
3. Create health check logic:
   - Check if workers are running (via threading)
   - Check DB connection
   - Get system metrics

### Phase 2: Frontend Dashboard
1. Create `src/static/dashboard.html`:
   - Embedded HTML/CSS/JS (no external files)
   - Use CDN for Bootstrap, Chart.js
   - Fetch API for polling
   - Modal for item details
   - Action buttons with confirmation
2. Implement auto-refresh logic
3. Add error handling for API failures

### Phase 3: Log Streaming
1. Implement log capture mechanism:
   - Option A: Read from docker logs via subprocess
   - Option B: Custom log handler that stores in memory buffer
2. Stream logs via SSE (Server-Sent Events)

### Phase 4: Docker Integration
1. Update `docker-compose.yml`:
   - Add port mapping `8000:8000`
   - Add environment variables for API config
2. Update `Dockerfile`:
   - Install FastAPI dependencies
   - Add uvicorn as service
3. Create startup script that runs both:
   - Main processor (python main.py)
   - API server (uvicorn src.api:app)

### Phase 5: Testing & Documentation
1. Test all endpoints manually
2. Update README.md with dashboard access instructions
3. Add screenshots
4. Document API endpoints

## Acceptance Criteria
- [ ] Dashboard accessible at `http://<server-ip>:8000`
- [ ] Shows real-time queue statistics (auto-refresh every 5s)
- [ ] Can view queue items with filters
- [ ] Can manually retry failed items via button click
- [ ] Can view full item details including metadata JSON
- [ ] Live logs visible and auto-scrolling
- [ ] All actions work without page refresh (AJAX)
- [ ] No authentication required (LAN-only access)
- [ ] Deployed to production server

## Technical Details

### API Response Examples

**GET /api/stats**
```json
{
  "total": 150,
  "completed": 145,
  "pending": 2,
  "processing": 1,
  "error": 2,
  "by_actress": {"Kaede Fua": 5, "Hitomi": 3}
}
```

**GET /api/queue?status=error&limit=10**
```json
{
  "items": [
    {
      "id": 1,
      "file_path": "/watch/TEST-123.mp4",
      "movie_code": "TEST-123",
      "actress": null,
      "status": "error",
      "error_message": "No metadata found",
      "retry_count": 4,
      "created_at": "2026-02-15T10:00:00Z"
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 10
}
```

**GET /api/health**
```json
{
  "status": "healthy",
  "workers": {
    "FileProcessor": "running",
    "EmbyUpdater": "running",
    "RetryHandler": "running"
  },
  "database": "connected",
  "uptime": "5h 32m"
}
```

## Files to Create/Modify
- `src/api.py` (new)
- `src/static/dashboard.html` (new)
- `requirements.txt` (add FastAPI, uvicorn)
- `docker-compose.yml` (add port 8000)
- `Dockerfile` (update CMD to run both services)
- `README.md` (add dashboard documentation)

## Dependencies
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
python-multipart==0.0.12
```

## Deployment
```bash
# Local development
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000

# Production (docker-compose)
docker compose up -d
# Access: http://192.168.2.198:8000
```

## Future Enhancements (Not in this issue)
- WebSocket for real-time updates (instead of polling)
- Bulk actions (retry all errors, cleanup all completed)
- Export queue data as CSV
- Historical statistics graphs
- Search functionality with autocomplete
- Dark mode toggle
