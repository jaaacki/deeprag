# Emby Processor

[![GitHub](https://img.shields.io/badge/github-jaaacki%2Femby--processor-blue)](https://github.com/jaaacki/emby-processor)

Automated file processing pipeline that watches for new video files, fetches metadata from the emby-service WordPress plugin, renames files with structured names, organizes them into actress folders, and triggers Emby library scans.

## What It Does

- Watches a download folder for new video files (`.mp4`, `.mkv`, `.avi`, `.wmv`)
- Extracts movie code and subtitle language from the filename
- Searches the WP REST API for metadata (actress, title, etc.)
- Renames to: `{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}`
- Moves to `{destination}/{Actress}/` (creates folder if needed, matches case-insensitively)
- Triggers Emby server to scan and import the new file
- Writes metadata to Emby (title, actress, genre, studios) with LockData to prevent overwrites

### Example

```
Input:  SONE-760 English subbed The same commute train as always.mp4
Output: Ruri Saijo - [English Sub] SONE-760 The Same Commute Train As Always.mp4
Moved:  /destination/Ruri Saijo/
```

## Requirements

- Docker and Docker Compose
- The emby-service WordPress plugin running on the same Docker network
- Emby server with API access
- A watch directory where yt-dlp (or similar) drops files

## Setup

### 1. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
nano .env
```

Key settings to update:

```bash
# WordPress REST API (use Docker internal hostname)
API_BASE_URL=http://wpfamilyhubid_nginx/wp-json/emby/v1
API_TOKEN=your-wordpress-access-token  # JWT access token (expires in 24h)

# Emby Server (use Docker internal hostname)
# Find your Emby container: docker ps | grep -i emby
EMBY_BASE_URL=http://emby_server:8096
EMBY_API_KEY=your-emby-api-key
```

**Important**: Also create `.refresh_token` file with your WordPress refresh token:
```bash
echo "your-refresh-token-here" > .refresh_token
chmod 600 .refresh_token
```

The container will automatically refresh the access token every 20 hours using the refresh token.

See `.env.example` for all available options.

### 2. Deploy

For local development:
```bash
docker compose up -d
```

For production deployment on Synology NAS, see [DEPLOY.md](DEPLOY.md) for detailed instructions.

The `docker-compose.yml` mounts:
- `/volume3/docker/yt_dlp/downloads` → `/watch` (input)
- `/volume2/system32/linux/systemd/jpv` → `/destination` (output)
- `./.env` → `/app/.env` (read-only configuration)
- `./.refresh_token` → `/app/.refresh_token` (WordPress refresh token)

### Automatic Token Refresh

WordPress JWT tokens expire every 24 hours. The container automatically refreshes them:

- **Cron job** runs inside container every 20 hours
- Uses refresh token to get new access token
- Updates `.env` file automatically
- **No manual intervention needed** after initial setup

See [scripts/README.md](scripts/README.md) for technical details.

### 3. Verify

Check logs:

```bash
docker compose logs -f emby-processor
```

Drop a test file in the watch directory and confirm it gets processed:

```
2026-02-15 10:00:00 [INFO] emby-processor: Watching for new files...
2026-02-15 10:00:05 [INFO] src.watcher: New file detected: SONE-760 English subbed title.mp4
2026-02-15 10:00:15 [INFO] src.watcher: File stable: /watch/SONE-760 English subbed title.mp4 (524288000 bytes)
2026-02-15 10:00:16 [INFO] src.pipeline: Extracted: code=SONE-760, subtitle=English Sub
2026-02-15 10:00:17 [INFO] src.metadata: Found metadata for SONE-760 via missav
2026-02-15 10:00:17 [INFO] src.renamer: Moving /watch/... -> /destination/Ruri Saijo/...
```

## Pipeline Flow

```
New file appears in /watch
  │
  ├─ Stability check (wait for yt-dlp to finish writing)
  │
  ├─ Extract movie code: regex [A-Za-z]{2,6}-\d{1,5}
  │   └─ No code found → move to errors/
  │
  ├─ Detect subtitle: scan for 'english'/'chinese' keywords
  │
  ├─ Search API: POST /missav/search → fallback: /javguru/search
  │   └─ No result after retry → move to errors/
  │
  ├─ Build filename: {Actress} - [{Sub}] {CODE} {Title}.{ext}
  │
  ├─ Move to /destination/{Actress}/
  │   └─ Creates actress folder if needed
  │   └─ Matches existing folders case-insensitively
  │
  ├─ Trigger Emby library scan
  │   └─ Wait for Emby to index the file (10s)
  │
  └─ Update Emby metadata
      └─ Find item by path
      └─ Write WordPress metadata (actress, title, genre, studios)
      └─ Set LockData: true to prevent overwrites
```

## Error Handling

Files that can't be processed are moved to `{watch_dir}/errors/`:
- No movie code found in filename
- API search returned no results (after one retry)
- File move failed

Check the error directory and logs to diagnose failures.

## Development

### Run tests locally

```bash
cd emby-processor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

**Note**: Tests run in CI and locally. 45 tests covering extractor, renamer, and Emby client.

### Test Emby Integration

Manual testing scripts for Emby API integration:

- **[test_emby_simple.md](test_emby_simple.md)** — curl commands to test Emby API endpoints
- **[test_emby_update.md](test_emby_update.md)** — Python test script for metadata updates

```bash
# Run Python test (requires .env configuration)
python3 test_emby_update.py

# Or use curl commands from test_emby_simple.md
```

See test documentation for detailed checklists and passing criteria.

### Project structure

```
emby-processor/
├── main.py                  # Entry point: load env, start watcher
├── .env                     # Environment configuration (not tracked)
├── .env.example             # Template for .env
├── src/
│   ├── watcher.py           # watchdog folder monitor + stability check
│   ├── extractor.py         # Movie code + subtitle detection
│   ├── metadata.py          # WP REST API client
│   ├── emby_client.py       # Emby server API client
│   ├── renamer.py           # Filename builder + sanitizer + file move
│   └── pipeline.py          # Orchestrates the full flow per file
├── tests/
│   ├── test_extractor.py    # Extractor unit tests
│   ├── test_renamer.py      # Renamer unit tests
│   └── test_emby_client.py  # Emby client unit tests
├── test_emby_update.py      # Standalone Emby metadata test
├── test_emby_simple.py      # Curl command generator for testing
├── test_emby_update.md      # Python test documentation + checklist
├── test_emby_simple.md      # Curl test documentation + checklist
├── googlescript_legacy/     # Reference JavaScript implementation
├── Dockerfile
├── docker-compose.yml
├── DEPLOY.md                # Deployment guide for Synology NAS
└── requirements.txt
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component diagram and data flow.

See [ROADMAP.md](ROADMAP.md) for planned work and [CHANGELOG.md](CHANGELOG.md) for history.
