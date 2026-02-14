#!/bin/bash
# Auto-refresh WordPress JWT token for emby-processor
# Run this script every 20 hours via cron

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
REFRESH_TOKEN_FILE="$PROJECT_DIR/.refresh_token"

# WordPress API endpoint (adjust if needed)
WP_API_URL="http://wpfamilyhubid_nginx/wp-json/jwt-auth/v1/token/refresh"

# Read refresh token
if [ ! -f "$REFRESH_TOKEN_FILE" ]; then
    echo "Error: Refresh token file not found at $REFRESH_TOKEN_FILE"
    exit 1
fi

REFRESH_TOKEN=$(cat "$REFRESH_TOKEN_FILE")

# Request new access token
RESPONSE=$(curl -s -X POST "$WP_API_URL" \
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

# Restart container if running
if docker ps --format '{{.Names}}' | grep -q '^emby-processor$'; then
    docker restart emby-processor > /dev/null 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Token refreshed and container restarted"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Token refreshed (container not running)"
fi
