# Architecture

## Component Map

```
┌─────────────────────────────────────────────────────────────┐
│                      Watch Directory                         │
│              /volume3/docker/yt_dlp/downloads/               │
└──────────────────────────┬──────────────────────────────────┘
                           │ (watchdog inotify)
              ┌────────────▼─────────────┐
              │  watcher.py              │
              │  - FileCreated events    │
              │  - StabilityChecker      │
              │    (polls file size)     │
              └────────────┬─────────────┘
                           │ (callback)
              ┌────────────▼─────────────┐
              │  pipeline.py             │
              │  (orchestrator)          │
              └──┬──────┬──────────┬─────┘
                 │      │          │
     ┌───────────▼──┐ ┌─▼────────┐ ┌▼──────────────┐
     │ extractor.py │ │metadata.py│ │  renamer.py   │
     │              │ │           │ │               │
     │ movie code   │ │ WP REST   │ │ build name    │
     │ subtitle     │ │ API client│ │ sanitize      │
     │ detection    │ │           │ │ folder match  │
     └──────────────┘ └─────┬─────┘ │ file move     │
                            │       └───────┬───────┘
                   ┌────────▼────────┐      │
                   │ emby-service    │      │
                   │ WordPress plugin│      │
                   │                 │      │
                   │ /missav/search  │      │
                   │ /javguru/search │      │
                   └─────────────────┘      │
                                            │
              ┌─────────────────────────────▼──────────────────┐
              │              Destination Directory              │
              │    /volume2/system32/linux/systemd/jpv/         │
              │    ├── Ruri Saijo/                              │
              │    ├── Yua Mikami/                              │
              │    └── {Actress}/                               │
              └────────────────────────────────────────────────┘
```

## Data Flow

### File Processing (per file)

```
1. watcher.py detects new .mp4/.mkv/.avi/.wmv in /watch
   │
2. StabilityChecker polls file size (5s interval × 2 checks)
   │ File still changing → wait and re-poll
   │ File disappeared → abort
   │
3. pipeline.process(file_path)
   │
4. extractor.extract_movie_code(filename)
   │ regex: [A-Za-z]{2,6}-\d{1,5}
   │ No match → move to errors/, return
   │
5. extractor.detect_subtitle(filename)
   │ Keyword scan → 'English Sub' / 'Chinese Sub' / 'No Sub'
   │
6. metadata_client.search(movie_code)
   │ POST /emby/v1/missav/search {moviecode: "SONE-760"}
   │ If no result → POST /emby/v1/javguru/search (fallback)
   │ If still no result → retry once → if still nothing → errors/
   │
7. renamer.build_filename(actress, subtitle, code, title, ext)
   │ → "Ruri Saijo - [English Sub] SONE-760 The Same Commute.mp4"
   │
8. renamer.move_file(source, destination, actress, filename)
   │ find_matching_folder() → case-insensitive folder lookup
   │ Create actress folder if needed
   │ Handle name collisions with (1), (2), etc.
   │
9. Done. File is at /destination/{Actress}/{new_name}.{ext}
```

### API Response Format

The metadata client expects the emby-service search endpoint to return:

```json
{
  "success": true,
  "data": {
    "movie_code": "SONE-760",
    "title": "The Same Commute Train As Always...",
    "actress": ["Ruri Saijo"],
    "genre": ["Drama", "Romance"],
    "release_date": "2026-01-15",
    "raw_image_url": "https://...",
    "series": null,
    "maker": "S1 NO.1 STYLE",
    "label": "S1 NO.1 STYLE"
  }
}
```

The pipeline uses: `actress[0]` (first actress), `title`, and `movie_code`.

## Docker Network

```
┌─────────────────────────────────────────────────┐
│             wpfamilyhubid_default                │
│                (Docker network)                  │
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │emby-processor│───▶│wpfamilyhubid_nginx   │   │
│  │  (Python)    │HTTP│  (WordPress + Nginx) │   │
│  └──────────────┘    └──────────┬───────────┘   │
│                                 │               │
│                      ┌──────────▼───────────┐   │
│                      │  crawl4ai            │   │
│                      │  (headless browser)  │   │
│                      └──────────────────────┘   │
└─────────────────────────────────────────────────┘

Volumes:
  /volume3/docker/yt_dlp/downloads  →  /watch        (emby-processor)
  /volume2/system32/linux/systemd/jpv  →  /destination  (emby-processor)
```

## Configuration

All configuration lives in `config.yaml`, mounted into the container at `/app/config.yaml`.

| Key | Type | Description |
|-----|------|-------------|
| `watch_dir` | string | Directory to watch for new files |
| `destination_dir` | string | Root directory for actress folders |
| `error_dir` | string | Where failed files are moved |
| `video_extensions` | list | File extensions to process |
| `api.base_url` | string | WP REST API base URL |
| `api.token` | string | JWT bearer token (if auth required) |
| `api.search_order` | list | Sources to try in order |
| `stability.check_interval_seconds` | int | Seconds between size polls |
| `stability.min_stable_checks` | int | Consecutive stable checks required |
