"""Tests for the queue management CLI."""

import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from src.cli import (
    _format_age,
    build_parser,
    cmd_cleanup,
    cmd_list,
    cmd_reset,
    cmd_retry,
    cmd_retry_all,
    cmd_status,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_args(**kwargs):
    """Create a simple namespace object to simulate parsed args."""
    from argparse import Namespace
    return Namespace(**kwargs)


@pytest.fixture
def mock_conn():
    """Create a mock database connection with a cursor."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_status_command(self):
        parser = build_parser()
        args = parser.parse_args(['status'])
        assert args.command == 'status'

    def test_list_command_no_filter(self):
        parser = build_parser()
        args = parser.parse_args(['list'])
        assert args.command == 'list'
        assert args.status is None
        assert args.limit is None
        assert args.verbose is False

    def test_list_command_with_status(self):
        parser = build_parser()
        args = parser.parse_args(['list', '--status', 'error'])
        assert args.command == 'list'
        assert args.status == 'error'

    def test_list_command_with_short_status(self):
        parser = build_parser()
        args = parser.parse_args(['list', '-s', 'pending'])
        assert args.status == 'pending'

    def test_list_command_with_limit(self):
        parser = build_parser()
        args = parser.parse_args(['list', '--limit', '10'])
        assert args.limit == 10

    def test_list_command_with_verbose(self):
        parser = build_parser()
        args = parser.parse_args(['list', '-v'])
        assert args.verbose is True

    def test_list_invalid_status(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['list', '--status', 'invalid'])

    def test_retry_command(self):
        parser = build_parser()
        args = parser.parse_args(['retry', '42'])
        assert args.command == 'retry'
        assert args.id == 42

    def test_retry_all_command(self):
        parser = build_parser()
        args = parser.parse_args(['retry-all'])
        assert args.command == 'retry-all'

    def test_cleanup_command(self):
        parser = build_parser()
        args = parser.parse_args(['cleanup', '--days', '30'])
        assert args.command == 'cleanup'
        assert args.days == 30
        assert args.yes is False

    def test_cleanup_command_with_yes(self):
        parser = build_parser()
        args = parser.parse_args(['cleanup', '--days', '7', '-y'])
        assert args.days == 7
        assert args.yes is True

    def test_cleanup_requires_days(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['cleanup'])

    def test_reset_command(self):
        parser = build_parser()
        args = parser.parse_args(['reset', '5'])
        assert args.command == 'reset'
        assert args.id == 5

    def test_no_command_shows_help(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_list_all_valid_statuses(self):
        parser = build_parser()
        for status in ['pending', 'processing', 'moved', 'emby_pending', 'completed', 'error']:
            args = parser.parse_args(['list', '-s', status])
            assert args.status == status


# ---------------------------------------------------------------------------
# cmd_status tests
# ---------------------------------------------------------------------------

class TestCmdStatus:
    @patch('src.cli.get_db_connection')
    def test_status_with_items(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        # Counts by status
        cursor.fetchall.return_value = [
            ('completed', 10),
            ('error', 3),
            ('pending', 5),
        ]
        # Oldest pending
        cursor.fetchone.side_effect = [
            (datetime.now(timezone.utc) - timedelta(hours=2),),  # oldest pending
            (2,),  # retryable count
        ]

        cmd_status(make_args())
        output = capsys.readouterr().out

        assert 'Queue Status (18 total)' in output
        assert 'completed' in output
        assert 'error' in output
        assert 'pending' in output
        assert 'total' in output
        assert '10' in output
        assert '3' in output
        assert '5' in output
        assert '18' in output

    @patch('src.cli.get_db_connection')
    def test_status_empty_queue(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = []

        cmd_status(make_args())
        output = capsys.readouterr().out

        assert 'Queue Status (0 total)' in output
        assert '(empty queue)' in output

    @patch('src.cli.get_db_connection')
    def test_status_no_pending_no_retryable(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = [('completed', 5)]
        cursor.fetchone.side_effect = [
            None,  # no oldest pending
            (0,),  # no retryable
        ]

        cmd_status(make_args())
        output = capsys.readouterr().out

        assert 'Oldest pending' not in output
        assert 'Retryable' not in output

    @patch('src.cli.get_db_connection')
    def test_status_shows_retryable(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = [('error', 5)]
        cursor.fetchone.side_effect = [
            None,  # no oldest pending
            (3,),  # 3 retryable
        ]

        cmd_status(make_args())
        output = capsys.readouterr().out

        assert 'Retryable errors: 3' in output


# ---------------------------------------------------------------------------
# cmd_list tests
# ---------------------------------------------------------------------------

class TestCmdList:
    @patch('src.cli.get_db_connection')
    def test_list_all_items(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        now = datetime.now(timezone.utc)
        cursor.fetchall.return_value = [
            (1, '/watch/test.mp4', 'SONE-760', 'Ruri Saijo', 'completed', None, 0, now),
            (2, '/watch/another.mp4', 'ABC-123', 'Yua Mikami', 'error', 'API timeout', 2, now),
        ]

        cmd_list(make_args(status=None, limit=None, verbose=False))
        output = capsys.readouterr().out

        assert 'SONE-760' in output
        assert 'ABC-123' in output
        assert 'Ruri Saijo' in output
        assert 'Yua Mikami' in output
        assert '2 item(s) shown' in output

    @patch('src.cli.get_db_connection')
    def test_list_filtered_by_status(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = []

        cmd_list(make_args(status='pending', limit=None, verbose=False))
        output = capsys.readouterr().out

        assert "No items found with status 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_list_verbose_shows_errors(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        now = datetime.now(timezone.utc)
        cursor.fetchall.return_value = [
            (2, '/watch/fail.mp4', 'XYZ-999', None, 'error', 'Connection refused', 3, now),
        ]

        cmd_list(make_args(status='error', limit=None, verbose=True))
        output = capsys.readouterr().out

        assert 'Connection refused' in output

    @patch('src.cli.get_db_connection')
    def test_list_verbose_no_error_msg(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        now = datetime.now(timezone.utc)
        cursor.fetchall.return_value = [
            (1, '/watch/ok.mp4', 'ABC-001', 'Test', 'completed', None, 0, now),
        ]

        cmd_list(make_args(status=None, limit=None, verbose=True))
        output = capsys.readouterr().out

        assert 'Error:' not in output

    @patch('src.cli.get_db_connection')
    def test_list_truncates_long_filenames(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        long_name = 'a' * 60 + '.mp4'
        now = datetime.now(timezone.utc)
        cursor.fetchall.return_value = [
            (1, f'/watch/{long_name}', 'ABC-001', 'Test', 'pending', None, 0, now),
        ]

        cmd_list(make_args(status=None, limit=None, verbose=False))
        output = capsys.readouterr().out

        assert '...' in output

    @patch('src.cli.get_db_connection')
    def test_list_no_items(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = []

        cmd_list(make_args(status=None, limit=None, verbose=False))
        output = capsys.readouterr().out

        assert 'No items found' in output

    @patch('src.cli.get_db_connection')
    def test_list_handles_null_fields(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        now = datetime.now(timezone.utc)
        cursor.fetchall.return_value = [
            (1, '/watch/test.mp4', None, None, 'pending', None, 0, now),
        ]

        cmd_list(make_args(status=None, limit=None, verbose=False))
        output = capsys.readouterr().out

        assert '-' in output  # null fields show as '-'


# ---------------------------------------------------------------------------
# cmd_retry tests
# ---------------------------------------------------------------------------

class TestCmdRetry:
    @patch('src.cli.get_db_connection')
    def test_retry_error_item(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (42, '/watch/test.mp4', 'error')

        cmd_retry(make_args(id=42))
        output = capsys.readouterr().out

        cursor.execute.assert_called()
        conn.commit.assert_called_once()
        assert "Item 42 reset to 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_retry_nonexistent_item(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = None

        with pytest.raises(SystemExit) as exc_info:
            cmd_retry(make_args(id=999))
        assert exc_info.value.code == 1

    @patch('src.cli.get_db_connection')
    def test_retry_non_error_item(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (42, '/watch/test.mp4', 'completed')

        with pytest.raises(SystemExit) as exc_info:
            cmd_retry(make_args(id=42))
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_retry_all tests
# ---------------------------------------------------------------------------

class TestCmdRetryAll:
    @patch('src.cli.get_db_connection')
    def test_retry_all_with_errors(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = [(1,), (2,), (3,)]

        cmd_retry_all(make_args())
        output = capsys.readouterr().out

        conn.commit.assert_called_once()
        assert "3 item(s) reset to 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_retry_all_no_errors(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = []

        cmd_retry_all(make_args())
        output = capsys.readouterr().out

        assert 'No error items to retry' in output


# ---------------------------------------------------------------------------
# cmd_cleanup tests
# ---------------------------------------------------------------------------

class TestCmdCleanup:
    @patch('src.cli.get_db_connection')
    def test_cleanup_with_confirmation(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (5,)

        with patch('builtins.input', return_value='y'):
            cmd_cleanup(make_args(days=30, yes=False))

        output = capsys.readouterr().out
        conn.commit.assert_called_once()
        assert 'Deleted 5 completed item(s)' in output

    @patch('src.cli.get_db_connection')
    def test_cleanup_cancelled(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (5,)

        with patch('builtins.input', return_value='n'):
            cmd_cleanup(make_args(days=30, yes=False))

        output = capsys.readouterr().out
        conn.commit.assert_not_called()
        assert 'Cancelled' in output

    @patch('src.cli.get_db_connection')
    def test_cleanup_with_yes_flag(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (3,)

        cmd_cleanup(make_args(days=7, yes=True))
        output = capsys.readouterr().out

        conn.commit.assert_called_once()
        assert 'Deleted 3 completed item(s)' in output

    @patch('src.cli.get_db_connection')
    def test_cleanup_nothing_to_delete(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (0,)

        cmd_cleanup(make_args(days=30, yes=False))
        output = capsys.readouterr().out

        assert 'No completed items older than 30 days' in output


# ---------------------------------------------------------------------------
# cmd_reset tests
# ---------------------------------------------------------------------------

class TestCmdReset:
    @patch('src.cli.get_db_connection')
    def test_reset_error_item(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (5, '/watch/test.mp4', 'error')

        cmd_reset(make_args(id=5))
        output = capsys.readouterr().out

        conn.commit.assert_called_once()
        assert "Item 5 reset from 'error' to 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_reset_completed_item(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (5, '/watch/test.mp4', 'completed')

        cmd_reset(make_args(id=5))
        output = capsys.readouterr().out

        conn.commit.assert_called_once()
        assert "Item 5 reset from 'completed' to 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_reset_already_pending(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = (5, '/watch/test.mp4', 'pending')

        cmd_reset(make_args(id=5))
        output = capsys.readouterr().out

        conn.commit.assert_not_called()
        assert "already 'pending'" in output

    @patch('src.cli.get_db_connection')
    def test_reset_nonexistent_item(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchone.return_value = None

        with pytest.raises(SystemExit) as exc_info:
            cmd_reset(make_args(id=999))
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _format_age tests
# ---------------------------------------------------------------------------

class TestFormatAge:
    def test_seconds(self):
        assert _format_age(timedelta(seconds=30)) == '30s'

    def test_minutes(self):
        assert _format_age(timedelta(minutes=15)) == '15m'

    def test_hours_and_minutes(self):
        assert _format_age(timedelta(hours=2, minutes=30)) == '2h 30m'

    def test_days_and_hours(self):
        assert _format_age(timedelta(days=3, hours=5)) == '3d 5h'

    def test_zero(self):
        assert _format_age(timedelta(0)) == '0s'


# ---------------------------------------------------------------------------
# main() entry point tests
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_command_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    @patch('src.cli.get_db_connection')
    def test_status_dispatches(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        cursor.fetchall.return_value = []

        main(['status'])
        output = capsys.readouterr().out
        assert 'Queue Status' in output

    @patch('src.cli.get_db_connection')
    def test_db_connection_error(self, mock_get_conn, capsys):
        import psycopg2
        mock_get_conn.side_effect = psycopg2.OperationalError('connection refused')

        with pytest.raises(SystemExit) as exc_info:
            main(['status'])
        assert exc_info.value.code == 1

        stderr = capsys.readouterr().err
        assert 'Database connection error' in stderr

    @patch('src.cli.get_db_connection')
    def test_retry_all_dispatches(self, mock_get_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn
        cursor.fetchall.return_value = []

        main(['retry-all'])
        output = capsys.readouterr().out
        assert 'No error items' in output


# ---------------------------------------------------------------------------
# get_db_connection tests
# ---------------------------------------------------------------------------

class TestGetDbConnection:
    @patch('src.cli.psycopg2.connect')
    @patch('src.cli.load_dotenv')
    @patch.dict('os.environ', {'DATABASE_URL': 'postgresql://user:pass@host/db'}, clear=False)
    def test_uses_database_url(self, mock_dotenv, mock_connect):
        from src.cli import get_db_connection
        get_db_connection()
        mock_connect.assert_called_once_with('postgresql://user:pass@host/db')

    @patch('src.cli.psycopg2.connect')
    @patch('src.cli.load_dotenv')
    @patch.dict('os.environ', {
        'DB_HOST': 'myhost',
        'DB_PORT': '5433',
        'DB_NAME': 'mydb',
        'DB_USER': 'myuser',
        'DB_PASSWORD': 'mypass',
    }, clear=False)
    def test_uses_individual_vars(self, mock_dotenv, mock_connect):
        from src.cli import get_db_connection
        # Remove DATABASE_URL if set
        import os
        os.environ.pop('DATABASE_URL', None)

        get_db_connection()
        mock_connect.assert_called_once_with(
            host='myhost',
            port=5433,
            dbname='mydb',
            user='myuser',
            password='mypass',
        )
