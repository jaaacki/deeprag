#!/bin/sh
# Start script for emby-processor with dashboard API

# Load environment variables (properly handle comments and empty lines)
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

# Start FastAPI dashboard in background
uvicorn src.api:app --host 0.0.0.0 --port 8000 &

# Start main processor (foreground)
exec python main.py
