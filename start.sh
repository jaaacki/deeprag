#!/bin/sh
# Start script for emby-processor with dashboard API

# Load environment variables (properly handle comments and empty lines)
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

# Set up Prometheus multiprocess directory (shared between FastAPI and workers)
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_metrics
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"

# Start FastAPI dashboard in background using custom runner
python /app/run_api.py &

# Start main processor (foreground)
exec python main.py
