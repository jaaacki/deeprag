#!/usr/bin/env python3
"""Simple test to verify Emby API endpoints work."""

import json

# Test data - you can run these with curl
EMBY_URL = "https://emby.familyhub.id"
API_KEY = "YOUR_EMBY_API_KEY"  # Replace with your actual Emby API key
TEST_ITEM_ID = "10249"

print("=" * 60)
print("EMBY API TEST COMMANDS")
print("=" * 60)

print("\n1. Get item details:")
print(f"curl -s '{EMBY_URL}/Items/{TEST_ITEM_ID}' \\")
print(f"  -H 'X-Emby-Token: {API_KEY}' | jq .")

print("\n2. Update item metadata (POST):")
update_data = {
    "OriginalTitle": "Test Title",
    "Overview": "Test overview",
    "PreferredMetadataLanguage": "en",
    "PreferredMetadataCountryCode": "JP",
    "ProductionYear": 2025,
    "PremiereDate": "2025-01-07",
    "People": [
        {"Name": "Kaede Fua", "Type": "Actor"}
    ],
    "GenreItems": [
        {"Name": "Drama"}
    ],
    "Studios": [
        {"Name": "S1 NO.1 STYLE"}
    ],
    "LockData": True
}

print(f"# First get the existing item:")
print(f"ITEM=$(curl -s '{EMBY_URL}/Items/{TEST_ITEM_ID}' -H 'X-Emby-Token: {API_KEY}')")
print(f"\n# Then update specific fields and POST back:")
print(f"echo $ITEM | jq '.OriginalTitle = \"Test Title\" | .Overview = \"Test overview\" | .LockData = true' > /tmp/update.json")
print(f"curl -X POST '{EMBY_URL}/Items/{TEST_ITEM_ID}' \\")
print(f"  -H 'X-Emby-Token: {API_KEY}' \\")
print(f"  -H 'Content-Type: application/json' \\")
print(f"  -d @/tmp/update.json")

print("\n3. Verify the update:")
print(f"curl -s '{EMBY_URL}/Items/{TEST_ITEM_ID}' \\")
print(f"  -H 'X-Emby-Token: {API_KEY}' | jq '.OriginalTitle, .Overview, .LockData'")

print("\n" + "=" * 60)
print("Copy and run these commands to test the Emby API")
print("=" * 60)
