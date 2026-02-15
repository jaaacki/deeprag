#!/bin/sh
# Start script for emby-processor with dashboard API

# Load environment variables
if [ -f /app/.env ]; then
    export $(grep -v '^#' /app/.env | xargs)
fi

# Start FastAPI dashboard in background
uvicorn src.api:app --host 0.0.0.0 --port 8000 &

# Start main processor (foreground)
exec python main.py
