#!/bin/sh
# Start script for emby-processor with dashboard API

# Load environment variables (properly handle comments and empty lines)
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

# Start FastAPI dashboard in background using custom runner
python /app/run_api.py &

# Start main processor (foreground)
exec python main.py
