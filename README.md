# Emby Processor

Automated file processing pipeline that watches for new video files, fetches metadata from the [emby-service](../emby-helper/emby-service/) WordPress plugin, renames files with structured names, and organizes them into actress folders.

## What It Does

- Watches a download folder for new video files (`.mp4`, `.mkv`, `.avi`, `.wmv`)
- Extracts movie code and subtitle language from the filename
- Searches the WP REST API for metadata (actress, title, etc.)
- Renames to: `{Actress} - [{Sub}] {MOVIE-CODE} {Title}.{ext}`
- Moves to `{destination}/{Actress}/`

### Example

```
Input:  SONE-760 English subbed The same commute train as always.mp4
Output: Ruri Saijo - [English Sub] SONE-760 The Same Commute Train As Always.mp4
Moved:  /destination/Ruri Saijo/
```

## Requirements

- Docker and Docker Compose
- The [emby-service](../emby-helper/emby-service/) WordPress plugin running on the same Docker network
- A watch directory where yt-dlp (or similar) drops files

## Setup

### 1. Configure

Edit `config.yaml`:

```yaml
watch_dir: /watch
destination_dir: /destination
error_dir: /watch/errors
video_extensions: [.mp4, .mkv, .avi, .wmv]

api:
  base_url: http://wpfamilyhubid_nginx/wp-json/emby/v1
  token: ""                          # JWT token if auth is required
  search_order: [missav, javguru]    # MissAV first, JavGuru fallback

stability:
  check_interval_seconds: 5          # seconds between file size checks
  min_stable_checks: 2               # consecutive identical sizes before processing
```

The `base_url` uses the Docker internal hostname. Adjust if your WP container has a different name.

### 2. Deploy

```bash
cd emby-processor
docker compose up -d
```

The `docker-compose.yml` mounts:
- `/volume3/docker/yt_dlp/downloads` → `/watch` (input)
- `/volume2/system32/linux/systemd/jpv` → `/destination` (output)
- `./config.yaml` → `/app/config.yaml`

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
  └─ Move to /destination/{Actress}/
      └─ Creates actress folder if needed
      └─ Matches existing folders case-insensitively
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

### Project structure

```
emby-processor/
├── main.py                  # Entry point: load config, start watcher
├── config.yaml              # Configuration
├── src/
│   ├── watcher.py           # watchdog folder monitor + stability check
│   ├── extractor.py         # Movie code + subtitle detection
│   ├── metadata.py          # WP REST API client
│   ├── renamer.py           # Filename builder + sanitizer + file move
│   └── pipeline.py          # Orchestrates the full flow per file
├── tests/
│   ├── test_extractor.py    # Extractor unit tests
│   └── test_renamer.py      # Renamer unit tests
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component diagram and data flow.

See [ROADMAP.md](ROADMAP.md) for planned work and [CHANGELOG.md](CHANGELOG.md) for history.
