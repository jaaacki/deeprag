#!/bin/sh
# Start script for emby-processor with dashboard API

# Load environment variables (properly handle comments and empty lines)
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

# Start FastAPI dashboard in background
# --log-config: Use custom logging (let our app control it)
# --no-access-log: Disable uvicorn access logs (reduce noise)
uvicorn src.api:app --host 0.0.0.0 --port 8000 --no-access-log --log-level info &

# Start main processor (foreground)
exec python main.py
