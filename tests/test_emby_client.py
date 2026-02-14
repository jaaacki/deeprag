"""Tests for the Emby client module."""

from unittest.mock import Mock, patch

import pytest
import requests
from src.emby_client import EmbyClient


class TestEmbyClient:
    """Tests for EmbyClient."""

    def test_init(self):
        client = EmbyClient('https://emby.example.com', 'test-key-123')
        assert client.base_url == 'https://emby.example.com'
        assert client.api_key == 'test-key-123'

    def test_init_strips_trailing_slash(self):
        client = EmbyClient('https://emby.example.com/', 'test-key')
        assert client.base_url == 'https://emby.example.com'

    @patch('src.emby_client.requests.post')
    def test_trigger_library_scan_success(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.trigger_library_scan()

        assert result is True
        mock_post.assert_called_once_with(
            'https://emby.example.com/Library/Refresh',
            headers={'X-Emby-Token': 'test-key'},
            params={},
            timeout=10,
        )

    @patch('src.emby_client.requests.post')
    def test_trigger_library_scan_with_path(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.trigger_library_scan('/path/to/library')

        assert result is True
        mock_post.assert_called_once_with(
            'https://emby.example.com/Library/Refresh',
            headers={'X-Emby-Token': 'test-key'},
            params={'path': '/path/to/library'},
            timeout=10,
        )

    @patch('src.emby_client.requests.post')
    def test_trigger_library_scan_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException('Connection failed')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.trigger_library_scan()

        assert result is False

    @patch('src.emby_client.requests.get')
    def test_get_libraries_success(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = [
            {'Name': 'Movies', 'Id': 'lib-123'},
            {'Name': 'TV Shows', 'Id': 'lib-456'},
        ]
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.get_libraries()

        assert len(result) == 2
        assert result[0]['Name'] == 'Movies'
        assert result[1]['Name'] == 'TV Shows'
        mock_get.assert_called_once_with(
            'https://emby.example.com/Library/VirtualFolders',
            headers={'X-Emby-Token': 'test-key'},
            timeout=10,
        )

    @patch('src.emby_client.requests.get')
    def test_get_libraries_failure(self, mock_get):
        mock_get.side_effect = requests.RequestException('Connection failed')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.get_libraries()

        assert result is None

    @patch('src.emby_client.requests.post')
    def test_scan_library_by_id_success(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.scan_library_by_id('lib-123')

        assert result is True
        mock_post.assert_called_once_with(
            'https://emby.example.com/Items/lib-123/Refresh',
            headers={'X-Emby-Token': 'test-key'},
            params={
                'Recursive': 'true',
                'ImageRefreshMode': 'Default',
                'MetadataRefreshMode': 'Default',
            },
            timeout=10,
        )

    @patch('src.emby_client.requests.post')
    def test_scan_library_by_id_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException('Connection failed')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.scan_library_by_id('lib-123')

        assert result is False
