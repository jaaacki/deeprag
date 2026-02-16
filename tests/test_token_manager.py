"""Tests for TokenManager — JWT token auto-refresh."""

import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.token_manager import TokenManager, load_refresh_token


@pytest.fixture
def mock_pool():
    """Create a mock psycopg2 connection pool."""
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()

    pool.getconn.return_value = conn
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Default: no token in DB
    cursor.fetchone.return_value = None

    return pool, conn, cursor


@pytest.fixture
def token_manager(mock_pool):
    """Create a TokenManager instance with mocked DB."""
    pool, conn, cursor = mock_pool
    tm = TokenManager(
        db_pool=pool,
        refresh_url='http://example.com/refresh',
        refresh_token='test-refresh-token',
        initial_access_token='initial-token',
    )
    return tm


class TestGetToken:
    def test_returns_initial_token_before_init(self, token_manager):
        """Before initialize(), get_token returns the initial token."""
        assert token_manager.get_token() == 'initial-token'

    def test_returns_refreshed_token_after_refresh(self, token_manager):
        """After a successful refresh, get_token returns the new token."""
        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.return_value.json.return_value = {
                'access_token': 'new-token-123',
                'expires_in': 86400,
            }

            result = token_manager._do_refresh()
            assert result is True
            assert token_manager.get_token() == 'new-token-123'

    def test_thread_safety(self, token_manager):
        """get_token is safe to call from multiple threads."""
        results = []

        def read_token():
            for _ in range(100):
                results.append(token_manager.get_token())

        threads = [threading.Thread(target=read_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 500
        assert all(t == 'initial-token' for t in results)


class TestDoRefresh:
    def test_successful_refresh(self, token_manager):
        """Successful refresh updates token and returns True."""
        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.return_value.json.return_value = {
                'access_token': 'refreshed-token',
                'expires_in': 86400,
            }

            assert token_manager._do_refresh() is True
            assert token_manager.get_token() == 'refreshed-token'

            # Verify the request was made correctly
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs['json'] == {'token': 'test-refresh-token'}
            assert 'Bearer initial-token' in call_kwargs.kwargs['headers']['Authorization']

    def test_refresh_failure_returns_false(self, token_manager):
        """Failed refresh returns False and keeps old token."""
        import requests
        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.side_effect = requests.RequestException('Connection error')

            assert token_manager._do_refresh() is False
            assert token_manager.get_token() == 'initial-token'

    def test_refresh_without_refresh_token(self, mock_pool):
        """Cannot refresh without a refresh token."""
        pool, conn, cursor = mock_pool
        tm = TokenManager(
            db_pool=pool,
            refresh_url='http://example.com/refresh',
            refresh_token='',
            initial_access_token='initial-token',
        )
        assert tm._do_refresh() is False

    def test_refresh_persists_to_db(self, token_manager, mock_pool):
        """Successful refresh saves token to DB."""
        pool, conn, cursor = mock_pool

        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.return_value.json.return_value = {
                'access_token': 'db-token',
                'expires_in': 86400,
            }

            token_manager._do_refresh()

            # Verify DB insert was called
            cursor.execute.assert_called()
            # Find the INSERT call
            insert_calls = [
                c for c in cursor.execute.call_args_list
                if 'INSERT INTO auth_tokens' in str(c)
            ]
            assert len(insert_calls) == 1


class TestHandle401:
    def test_triggers_refresh(self, token_manager):
        """handle_401 triggers a token refresh."""
        with patch.object(token_manager, '_do_refresh') as mock_refresh:
            token_manager.handle_401()
            mock_refresh.assert_called_once()

    def test_debounce(self, token_manager):
        """handle_401 is debounced — second call within cooldown is skipped."""
        with patch.object(token_manager, '_do_refresh') as mock_refresh:
            token_manager.handle_401()
            token_manager.handle_401()  # Should be debounced
            assert mock_refresh.call_count == 1


class TestInitialize:
    def test_falls_back_to_env_token_when_no_db_and_refresh_fails(self, mock_pool):
        """If DB is empty and refresh fails, uses initial .env token."""
        pool, conn, cursor = mock_pool
        cursor.fetchone.return_value = None  # No token in DB

        import requests
        tm = TokenManager(
            db_pool=pool,
            refresh_url='http://example.com/refresh',
            refresh_token='test-refresh-token',
            initial_access_token='env-token',
        )

        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.side_effect = requests.RequestException('fail')
            tm.initialize()

        assert tm.get_token() == 'env-token'
        tm.stop()

    def test_loads_valid_token_from_db(self, mock_pool):
        """If DB has a valid token, use it."""
        pool, conn, cursor = mock_pool
        future_time = datetime.now(timezone.utc) + timedelta(hours=12)
        cursor.fetchone.return_value = ('db-stored-token', future_time)

        tm = TokenManager(
            db_pool=pool,
            refresh_url='http://example.com/refresh',
            refresh_token='test-refresh-token',
            initial_access_token='env-token',
        )
        tm.initialize()

        assert tm.get_token() == 'db-stored-token'
        tm.stop()

    def test_refreshes_when_db_token_near_expiry(self, mock_pool):
        """If DB token is close to expiry, proactively refreshes."""
        pool, conn, cursor = mock_pool
        # Token expires in 2 hours (within the 4-hour refresh window)
        near_expiry = datetime.now(timezone.utc) + timedelta(hours=2)
        cursor.fetchone.return_value = ('near-expiry-token', near_expiry)

        tm = TokenManager(
            db_pool=pool,
            refresh_url='http://example.com/refresh',
            refresh_token='test-refresh-token',
            initial_access_token='env-token',
        )

        with patch('src.token_manager.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.return_value.json.return_value = {
                'access_token': 'proactively-refreshed',
                'expires_in': 86400,
            }
            tm.initialize()

        assert tm.get_token() == 'proactively-refreshed'
        tm.stop()


class TestLoadRefreshToken:
    def test_loads_from_file(self, tmp_path):
        """Loads refresh token from file."""
        token_file = tmp_path / '.refresh_token'
        token_file.write_text('file-refresh-token\n')

        result = load_refresh_token(str(token_file))
        assert result == 'file-refresh-token'

    def test_falls_back_to_env(self, tmp_path):
        """Falls back to env var if file doesn't exist."""
        missing_file = tmp_path / 'nonexistent'

        with patch.dict('os.environ', {'API_REFRESH_TOKEN': 'env-refresh-token'}):
            result = load_refresh_token(str(missing_file))
            assert result == 'env-refresh-token'

    def test_returns_empty_when_nothing_configured(self, tmp_path):
        """Returns empty string if neither file nor env var exists."""
        missing_file = tmp_path / 'nonexistent'

        with patch.dict('os.environ', {}, clear=True):
            result = load_refresh_token(str(missing_file))
            assert result == ''


class TestBackgroundLoop:
    def test_stop_terminates_thread(self, token_manager):
        """stop() terminates the background thread."""
        token_manager._thread = threading.Thread(
            target=token_manager._background_loop,
            daemon=True,
        )
        token_manager._thread.start()
        assert token_manager._thread.is_alive()

        token_manager.stop()
        assert not token_manager._thread.is_alive()
