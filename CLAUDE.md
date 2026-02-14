# Emby Processor — Automated File Processing Pipeline

## Project Overview

A Python Docker service that watches for new video files, fetches metadata from the emby-service WordPress plugin REST API, renames files with structured names, and organizes them into actress folders. Runs on the same Docker network as the WordPress stack.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full component map and data flow.

## Key Paths

```
emby-processor/
├── main.py                     # Entry point: load env vars, start watcher
├── .env                        # Environment variables (not tracked)
├── .env.example                # Template for .env
├── src/
│   ├── watcher.py              # watchdog folder monitor + file stability check
│   ├── extractor.py            # Movie code regex + subtitle keyword detection
│   ├── metadata.py             # WP REST API client (search endpoints)
│   ├── renamer.py              # Filename builder, sanitizer, folder match, file move
│   └── pipeline.py             # Orchestrates the full flow per file
├── tests/
│   ├── test_extractor.py       # Extractor unit tests (11 tests)
│   └── test_renamer.py         # Renamer unit tests (12 tests)
├── Dockerfile                  # Python 3.12-slim
├── docker-compose.yml          # Service definition with volume mounts
└── requirements.txt            # watchdog, requests, python-dotenv, pytest
```

## Remote Server

- **Host**: `noonoon@192.168.2.198` (Synology NAS)
- **Watch path**: `/volume3/docker/yt_dlp/downloads/`
- **Destination path**: `/volume2/system32/linux/systemd/jpv/`
- **Note**: Synology auto-blocks SSH after rapid connections. Space SSH commands at least 10s apart.

## Development Notes

- Python 3.12 (Docker runtime)
- Dependencies: watchdog, requests, python-dotenv
- Testing: pytest
- No framework — simple module structure with watchdog for file events
- API base URL uses Docker internal hostname: `http://wpfamilyhubid_nginx/wp-json/emby/v1`
- All config via environment variables in `.env` (not tracked in git)
- `.env.example` provides template for required environment variables

## Workflow Rules

Follow the rules in `.agent-rules/`:

- **`prompt_git-workflow-rules.md`** — Issues-first, milestone branches, squash merges
- **`prompt_docs-versioning-rules.md`** — Living docs (ROADMAP, CHANGELOG, LEARNING_LOG, README) updated with every issue
- **`prompt_agent-team-rules.md`** — Architect / Builder / Critic perspectives
- **`prompt_testing-rules.md`** — Co-located tests, test-with-code, always report results

## Living Documents

- `ROADMAP.md` — Phased plan with issues
- `CHANGELOG.md` — Reverse chronological history
- `LEARNING_LOG.md` — Decisions, patterns, lessons
- `README.md` — Setup and usage

## Conventions

- Python coding standards (PEP 8, snake_case, type hints)
- File naming: `{module}.py` for source, `test_{module}.py` for tests
- Tests live in `tests/` directory (Python convention; co-located approach adapted)
- Error handling via logging + file moves to `errors/` directory
- Every change starts with an issue — no code without an issue
- Tests adapt with code — every PR that changes code updates its tests
