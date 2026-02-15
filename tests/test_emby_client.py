"""Tests for the Emby client module."""

from unittest.mock import Mock, call, patch

import pytest
import requests
from src.emby_client import EmbyClient, DEFAULT_RETRY_DELAYS, IMAGE_TYPES


class TestEmbyClient:
    """Tests for EmbyClient."""

    def test_init(self):
        client = EmbyClient('https://emby.example.com', 'test-key-123')
        assert client.base_url == 'https://emby.example.com'
        assert client.api_key == 'test-key-123'
        assert client.parent_folder_id == ''
        assert client.retry_delays == DEFAULT_RETRY_DELAYS

    def test_init_with_parent_folder_and_retry(self):
        client = EmbyClient('https://emby.example.com', 'test-key', parent_folder_id='4',
                            retry_delays=[1, 2, 3])
        assert client.parent_folder_id == '4'
        assert client.retry_delays == [1, 2, 3]

    def test_init_strips_trailing_slash(self):
        client = EmbyClient('https://emby.example.com/', 'test-key')
        assert client.base_url == 'https://emby.example.com'

    @patch('src.emby_client.requests.post')
    def test_trigger_library_scan_success(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.status_code = 204
        mock_resp.text = ''
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
        mock_resp.status_code = 204
        mock_resp.text = ''
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
        result = client.scan_library_by_id('4')

        assert result is True
        mock_post.assert_called_once_with(
            'https://emby.example.com/emby/Items/4/Refresh',
            headers={'X-Emby-Token': 'test-key', 'Content-Type': 'application/json'},
            params={'Recursive': 'true'},
            timeout=30,
        )

    @patch('src.emby_client.requests.post')
    def test_scan_library_by_id_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException('Connection failed')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.scan_library_by_id('4')

        assert result is False


class TestGetItemByPathWithRetry:
    """Tests for the polling retry mechanism."""

    @patch('src.emby_client.requests.get')
    def test_found_immediately(self, mock_get):
        """Item found on first try, no retries needed."""
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'Items': [{'Id': 'item-1', 'Path': '/dest/Actress/video.mp4'}],
        }
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key', retry_delays=[1, 2])
        result = client.get_item_by_path_with_retry('/dest/Actress/video.mp4')

        assert result is not None
        assert result['Id'] == 'item-1'
        # Only one call - no retries
        assert mock_get.call_count == 1

    @patch('src.emby_client.time.sleep')
    @patch('src.emby_client.requests.get')
    def test_found_after_retry(self, mock_get, mock_sleep):
        """Item found after one retry."""
        not_found = Mock()
        not_found.raise_for_status = Mock()
        not_found.json.return_value = {'Items': []}

        found = Mock()
        found.raise_for_status = Mock()
        found.json.return_value = {
            'Items': [{'Id': 'item-1', 'Path': '/dest/Actress/video.mp4'}],
        }

        # First call: not found, second call (after retry): found
        mock_get.side_effect = [not_found, found]

        client = EmbyClient('https://emby.example.com', 'test-key', retry_delays=[2, 4])
        result = client.get_item_by_path_with_retry('/dest/Actress/video.mp4')

        assert result is not None
        assert result['Id'] == 'item-1'
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch('src.emby_client.time.sleep')
    @patch('src.emby_client.requests.get')
    def test_not_found_falls_back_to_filename(self, mock_get, mock_sleep):
        """All path retries fail, falls back to filename search and succeeds."""
        not_found = Mock()
        not_found.raise_for_status = Mock()
        not_found.json.return_value = {'Items': []}

        found_by_name = Mock()
        found_by_name.raise_for_status = Mock()
        found_by_name.json.return_value = {
            'Items': [{'Id': 'item-2', 'Path': '/dest/Actress/video.mp4'}],
        }

        # 3 path lookups fail (initial + 2 retries), then filename search succeeds
        mock_get.side_effect = [not_found, not_found, not_found, found_by_name]

        client = EmbyClient('https://emby.example.com', 'test-key',
                            parent_folder_id='4', retry_delays=[1, 1])
        result = client.get_item_by_path_with_retry('/dest/Actress/video.mp4')

        assert result is not None
        assert result['Id'] == 'item-2'
        # 3 path lookups + 1 filename search = 4 calls
        assert mock_get.call_count == 4
        assert mock_sleep.call_count == 2

    @patch('src.emby_client.time.sleep')
    @patch('src.emby_client.requests.get')
    def test_not_found_after_all_retries(self, mock_get, mock_sleep):
        """Item never found, returns None after all retries and fallback."""
        not_found = Mock()
        not_found.raise_for_status = Mock()
        not_found.json.return_value = {'Items': []}
        mock_get.return_value = not_found

        client = EmbyClient('https://emby.example.com', 'test-key', retry_delays=[1, 1])
        result = client.get_item_by_path_with_retry('/dest/Actress/video.mp4')

        assert result is None
        # 1 initial + 2 retries + 1 filename fallback = 4
        assert mock_get.call_count == 4

    @patch('src.emby_client.time.sleep')
    @patch('src.emby_client.requests.get')
    def test_exponential_backoff_delays(self, mock_get, mock_sleep):
        """Verify the sleep delays match the configured schedule."""
        not_found = Mock()
        not_found.raise_for_status = Mock()
        not_found.json.return_value = {'Items': []}
        mock_get.return_value = not_found

        delays = [2, 4, 8]
        client = EmbyClient('https://emby.example.com', 'test-key', retry_delays=delays)
        client.get_item_by_path_with_retry('/dest/Actress/video.mp4')

        assert mock_sleep.call_args_list == [call(2), call(4), call(8)]


class TestFindItemByFilename:
    """Tests for filename-based fallback search."""

    @patch('src.emby_client.requests.get')
    def test_found_by_exact_path_match(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'Items': [
                {'Id': 'item-1', 'Path': '/other/path/video.mp4'},
                {'Id': 'item-2', 'Path': '/dest/Actress/video.mp4'},
            ],
        }
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key', parent_folder_id='4')
        result = client.find_item_by_filename('video.mp4')

        assert result is not None
        assert result['Id'] == 'item-1'  # First match that ends with filename

        # Verify ParentId is included in the request
        call_args = mock_get.call_args
        assert call_args[1]['params']['ParentId'] == '4'
        assert call_args[1]['params']['SearchTerm'] == 'video.mp4'

    @patch('src.emby_client.requests.get')
    def test_found_without_parent_folder(self, mock_get):
        """Search works without parent_folder_id (no ParentId param)."""
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'Items': [{'Id': 'item-1', 'Path': '/dest/video.mp4'}],
        }
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.find_item_by_filename('video.mp4')

        assert result is not None
        call_args = mock_get.call_args
        assert 'ParentId' not in call_args[1]['params']

    @patch('src.emby_client.requests.get')
    def test_not_found(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {'Items': []}
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key', parent_folder_id='4')
        result = client.find_item_by_filename('nonexistent.mp4')

        assert result is None

    @patch('src.emby_client.requests.get')
    def test_network_error(self, mock_get):
        mock_get.side_effect = requests.RequestException('timeout')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.find_item_by_filename('video.mp4')

        assert result is None

    @patch('src.emby_client.requests.get')
    def test_no_exact_match_uses_first_result(self, mock_get):
        """When no path ends with filename, returns first search result."""
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'Items': [{'Id': 'item-1', 'Path': '/dest/different_name.mp4'}],
        }
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.find_item_by_filename('video.mp4')

        assert result is not None
        assert result['Id'] == 'item-1'


class TestDownloadImage:
    """Tests for image download methods."""

    @patch('src.emby_client.requests.get')
    def test_download_image_success(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.content = b'\xff\xd8\xff\xe0fake-jpeg-data'
        mock_resp.headers = {'Content-Type': 'image/jpeg'}
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.download_image('https://images.example.com/poster.jpg')

        assert result is not None
        data, ct = result
        assert data == b'\xff\xd8\xff\xe0fake-jpeg-data'
        assert ct == 'image/jpeg'
        mock_get.assert_called_once_with(
            'https://images.example.com/poster.jpg',
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*,*/*;q=0.8'},
            timeout=30,
            allow_redirects=True,
        )

    @patch('src.emby_client.requests.get')
    def test_download_image_not_an_image(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.headers = {'Content-Type': 'text/html'}
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.download_image('https://example.com/not-an-image')

        assert result is None

    @patch('src.emby_client.requests.get')
    def test_download_image_network_error(self, mock_get):
        mock_get.side_effect = requests.RequestException('Timeout')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.download_image('https://images.example.com/poster.jpg')

        assert result is None

    def test_download_image_empty_url(self):
        client = EmbyClient('https://emby.example.com', 'test-key')
        assert client.download_image('') is None
        assert client.download_image('   ') is None

    def test_make_w800_url_adds_width(self):
        result = EmbyClient._make_w800_url('https://images.example.com/poster.jpg')
        assert 'w=800' in result

    def test_make_w800_url_replaces_existing_width(self):
        result = EmbyClient._make_w800_url('https://images.example.com/poster.jpg?w=1200&q=90')
        assert 'w=800' in result
        assert 'w=1200' not in result
        assert 'q=90' in result

    def test_make_w800_url_removes_horizontal(self):
        result = EmbyClient._make_w800_url('https://images.example.com/poster.jpg?horizontal=true&w=400')
        assert 'w=800' in result
        assert 'horizontal' not in result

    @patch('src.emby_client.requests.get')
    def test_download_image_w800_transforms_url(self, mock_get):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.content = b'w800-image-data'
        mock_resp.headers = {'Content-Type': 'image/jpeg'}
        mock_get.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.download_image_w800('https://images.example.com/poster.jpg?q=90')

        assert result is not None
        data, ct = result
        assert data == b'w800-image-data'
        # Verify the URL was transformed
        called_url = mock_get.call_args[0][0]
        assert 'w=800' in called_url
        assert 'q=90' in called_url


class TestDeleteImage:
    """Tests for image deletion."""

    @patch('src.emby_client.requests.delete')
    def test_delete_image_success(self, mock_delete):
        mock_resp = Mock()
        mock_resp.status_code = 204
        mock_delete.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.delete_image('item-123', 'Primary')

        assert result is True
        mock_delete.assert_called_once_with(
            'https://emby.example.com/Items/item-123/Images/Primary/0',
            headers={'X-Emby-Token': 'test-key'},
            timeout=10,
        )

    @patch('src.emby_client.requests.delete')
    def test_delete_image_with_index(self, mock_delete):
        mock_resp = Mock()
        mock_resp.status_code = 204
        mock_delete.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.delete_image('item-123', 'Backdrop', 3)

        assert result is True
        mock_delete.assert_called_once_with(
            'https://emby.example.com/Items/item-123/Images/Backdrop/3',
            headers={'X-Emby-Token': 'test-key'},
            timeout=10,
        )

    @patch('src.emby_client.requests.delete')
    def test_delete_image_404_is_ok(self, mock_delete):
        mock_resp = Mock()
        mock_resp.status_code = 404
        mock_delete.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.delete_image('item-123', 'Logo')

        assert result is True

    @patch('src.emby_client.requests.delete')
    def test_delete_image_network_error(self, mock_delete):
        mock_delete.side_effect = requests.RequestException('Connection refused')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.delete_image('item-123', 'Primary')

        assert result is False


class TestUploadImage:
    """Tests for image upload."""

    @patch('src.emby_client.requests.post')
    def test_upload_image_success(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        image_data = b'\xff\xd8\xff\xe0fake-jpeg'
        result = client.upload_image('item-123', 'Primary', image_data, 'image/jpeg')

        assert result is True
        # Verify the call was made with base64-encoded data
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]['params'] == {'api_key': 'test-key'}
        assert 'Items/item-123/Images/Primary' in call_kwargs[0][0]
        assert call_kwargs[1]['headers'] == {'Content-Type': 'image/jpeg'}
        # Verify data is base64 encoded
        import base64
        expected_b64 = base64.b64encode(image_data).decode('ascii')
        assert call_kwargs[1]['data'] == expected_b64

    @patch('src.emby_client.requests.post')
    def test_upload_image_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException('Upload failed')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_image('item-123', 'Backdrop', b'data', 'image/jpeg')

        assert result is False

    @patch('src.emby_client.requests.post')
    def test_upload_image_default_content_type(self, mock_post):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_image('item-123', 'Banner', b'data')

        assert result is True
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]['headers'] == {'Content-Type': 'image/jpeg'}


class TestUploadItemImages:
    """Tests for the full image upload orchestration."""

    def test_upload_item_images_no_url(self):
        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_item_images('item-123', '')
        assert result is False

    @patch.object(EmbyClient, 'upload_image', return_value=True)
    @patch.object(EmbyClient, 'download_image')
    @patch.object(EmbyClient, 'download_image_w800')
    @patch.object(EmbyClient, 'delete_image', return_value=True)
    def test_upload_item_images_full_success(self, mock_delete, mock_dl_w800, mock_dl_orig, mock_upload):
        mock_dl_w800.return_value = (b'w800-data', 'image/jpeg')
        mock_dl_orig.return_value = (b'orig-data', 'image/jpeg')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_item_images('item-123', 'https://images.example.com/poster.jpg')

        assert result is True

        # Verify deletions: 5 Backdrop indices + Banner + Primary + Logo = 8 calls
        assert mock_delete.call_count == 8

        # Verify uploads: Backdrop + Banner (w800) + Primary (original) = 3 calls
        assert mock_upload.call_count == 3
        upload_calls = mock_upload.call_args_list
        assert upload_calls[0] == call('item-123', 'Backdrop', b'w800-data', 'image/jpeg')
        assert upload_calls[1] == call('item-123', 'Banner', b'w800-data', 'image/jpeg')
        assert upload_calls[2] == call('item-123', 'Primary', b'orig-data', 'image/jpeg')

    @patch.object(EmbyClient, 'upload_image', return_value=True)
    @patch.object(EmbyClient, 'download_image')
    @patch.object(EmbyClient, 'download_image_w800', return_value=None)
    @patch.object(EmbyClient, 'delete_image', return_value=True)
    def test_upload_item_images_w800_fails_primary_succeeds(self, mock_delete, mock_dl_w800, mock_dl_orig, mock_upload):
        mock_dl_orig.return_value = (b'orig-data', 'image/jpeg')

        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_item_images('item-123', 'https://images.example.com/poster.jpg')

        # Still True because Primary succeeded
        assert result is True
        # Only 1 upload (Primary), no Backdrop/Banner
        assert mock_upload.call_count == 1

    @patch.object(EmbyClient, 'upload_image', return_value=False)
    @patch.object(EmbyClient, 'download_image', return_value=(b'data', 'image/jpeg'))
    @patch.object(EmbyClient, 'download_image_w800', return_value=(b'data', 'image/jpeg'))
    @patch.object(EmbyClient, 'delete_image', return_value=True)
    def test_upload_item_images_all_uploads_fail(self, mock_delete, mock_dl_w800, mock_dl_orig, mock_upload):
        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_item_images('item-123', 'https://images.example.com/poster.jpg')

        assert result is False

    @patch.object(EmbyClient, 'upload_image', return_value=True)
    @patch.object(EmbyClient, 'download_image', return_value=None)
    @patch.object(EmbyClient, 'download_image_w800', return_value=None)
    @patch.object(EmbyClient, 'delete_image', return_value=True)
    def test_upload_item_images_all_downloads_fail(self, mock_delete, mock_dl_w800, mock_dl_orig, mock_upload):
        client = EmbyClient('https://emby.example.com', 'test-key')
        result = client.upload_item_images('item-123', 'https://images.example.com/poster.jpg')

        assert result is False
        # No uploads should have been attempted
        assert mock_upload.call_count == 0


class TestImageTypes:
    """Test the IMAGE_TYPES constant."""

    def test_image_types_contains_expected(self):
        assert 'Primary' in IMAGE_TYPES
        assert 'Backdrop' in IMAGE_TYPES
        assert 'Banner' in IMAGE_TYPES
        assert len(IMAGE_TYPES) == 3
