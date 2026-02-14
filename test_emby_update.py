#!/usr/bin/env python3
"""Standalone test script for Emby metadata update functionality."""

import logging
import os
from dotenv import load_dotenv
from src.emby_client import EmbyClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('test_emby_update')

def main():
    # Load environment
    load_dotenv()

    # Allow override for testing with public URL
    emby_base_url = os.getenv('EMBY_BASE_URL', '')
    emby_api_key = os.getenv('EMBY_API_KEY', '')

    # If using Docker internal URL, switch to public for testing
    if 'emby_server' in emby_base_url:
        logger.info('Detected Docker internal URL, switching to public URL for testing')
        emby_base_url = 'https://emby.familyhub.id'

    if not emby_base_url or not emby_api_key:
        logger.error('EMBY_BASE_URL or EMBY_API_KEY not set in .env')
        return

    logger.info('Creating Emby client: %s', emby_base_url)
    client = EmbyClient(emby_base_url, emby_api_key)

    # Test with existing item (you can change this ID)
    test_item_id = input('Enter Emby item ID to test (default: 10249): ').strip() or '10249'

    logger.info('Testing with item ID: %s', test_item_id)

    # Step 1: Get current item details
    logger.info('Step 1: Fetching current item details...')
    item = client.get_item_details(test_item_id)

    if not item:
        logger.error('Failed to get item details')
        return

    logger.info('Current item name: %s', item.get('Name'))
    logger.info('Current OriginalTitle: %s', item.get('OriginalTitle'))
    logger.info('Current Overview: %s', item.get('Overview', '')[:100])
    logger.info('Current People: %s', [p.get('Name') for p in item.get('People', [])])

    # Step 2: Create mock metadata (like WordPress would return)
    logger.info('\nStep 2: Creating mock metadata...')
    mock_metadata = {
        'movie_code': 'SONE-760',
        'original_title': 'Test Original Title - 初めての背徳トライアングル',
        'overview': 'Test overview description for this video.',
        'release_date': '2025-01-07',
        'actress': ['Kaede Fua', 'Test Actress 2'],
        'genre': ['Drama', 'Romance'],
        'label': 'S1 NO.1 STYLE',
    }

    logger.info('Mock metadata:')
    for key, value in mock_metadata.items():
        logger.info('  %s: %s', key, value)

    # Step 3: Update item metadata
    logger.info('\nStep 3: Updating Emby item metadata...')
    success = client.update_item_metadata(test_item_id, mock_metadata)

    if not success:
        logger.error('Update failed!')
        return

    logger.info('Update completed!')

    # Step 4: Verify the update
    logger.info('\nStep 4: Verifying the update...')
    updated_item = client.get_item_details(test_item_id)

    if not updated_item:
        logger.error('Failed to fetch updated item')
        return

    logger.info('Updated item name: %s', updated_item.get('Name'))
    logger.info('Updated OriginalTitle: %s', updated_item.get('OriginalTitle'))
    logger.info('Updated Overview: %s', updated_item.get('Overview', '')[:100])
    logger.info('Updated ProductionYear: %s', updated_item.get('ProductionYear'))
    logger.info('Updated PremiereDate: %s', updated_item.get('PremiereDate'))
    logger.info('Updated People: %s', [p.get('Name') for p in updated_item.get('People', [])])
    logger.info('Updated GenreItems: %s', [g.get('Name') for g in updated_item.get('GenreItems', [])])
    logger.info('Updated Studios: %s', [s.get('Name') for s in updated_item.get('Studios', [])])
    logger.info('Updated LockData: %s', updated_item.get('LockData'))

    logger.info('\n✅ Test completed successfully!')

if __name__ == '__main__':
    main()
