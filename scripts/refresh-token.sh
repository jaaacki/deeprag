#!/bin/bash
# Auto-refresh WordPress JWT token for emby-processor
# Run this script every 20 hours via cron on the Docker host

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
REFRESH_TOKEN_FILE="$PROJECT_DIR/.refresh_token"
CONTAINER_NAME="emby-processor"

# WordPress API endpoint (api-bearer-auth plugin)
WP_API_URL="http://wpfamilyhubid_nginx/wp-json/api-bearer-auth/v1/tokens/refresh"

# Read refresh token
if [ ! -f "$REFRESH_TOKEN_FILE" ]; then
    echo "Error: Refresh token file not found at $REFRESH_TOKEN_FILE"
    exit 1
fi

REFRESH_TOKEN=$(cat "$REFRESH_TOKEN_FILE")

# Docker command (use full path on Synology)
DOCKER_CMD="/usr/local/bin/docker"

# Check if container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Error: Container $CONTAINER_NAME is not running"
    exit 1
fi

# Request new access token from INSIDE the container (on Docker network)
RESPONSE=$($DOCKER_CMD exec "$CONTAINER_NAME" curl -s -X POST "$WP_API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}")

# Extract new access token
NEW_ACCESS_TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$NEW_ACCESS_TOKEN" ]; then
    echo "Error: Failed to refresh token"
    echo "Response: $RESPONSE"
    exit 1
fi

# Update .env file
sed -i.bak "s|API_TOKEN=.*|API_TOKEN=$NEW_ACCESS_TOKEN|" "$ENV_FILE"

# Restart container to load new token
$DOCKER_CMD restart "$CONTAINER_NAME" > /dev/null 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') - Token refreshed successfully"
