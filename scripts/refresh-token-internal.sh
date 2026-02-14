#!/bin/bash
# Auto-refresh WordPress JWT token (runs INSIDE container)

set -e

ENV_FILE="/app/.env"
REFRESH_TOKEN_FILE="/app/.refresh_token"
WP_API_URL="http://wpfamilyhubid_nginx/wp-json/api-bearer-auth/v1/tokens/refresh"

# Read refresh token
if [ ! -f "$REFRESH_TOKEN_FILE" ]; then
    echo "Error: Refresh token file not found at $REFRESH_TOKEN_FILE"
    exit 1
fi

REFRESH_TOKEN=$(cat "$REFRESH_TOKEN_FILE")

# Get current access token from .env
CURRENT_TOKEN=$(grep "^API_TOKEN=" "$ENV_FILE" | cut -d'=' -f2)

# Request new access token
RESPONSE=$(curl -s -X POST "$WP_API_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $CURRENT_TOKEN" \
    -d "{\"token\":\"$REFRESH_TOKEN\"}")

# Extract new access token
NEW_ACCESS_TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$NEW_ACCESS_TOKEN" ]; then
    echo "Error: Failed to refresh token"
    echo "Response: $RESPONSE"
    exit 1
fi

# Update .env file (in-place)
sed -i "s|API_TOKEN=.*|API_TOKEN=$NEW_ACCESS_TOKEN|" "$ENV_FILE"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Token refreshed successfully"

# Note: Container restart not needed - main.py will use new token on next API call
