"""JWT token auto-refresh manager for WordPress API Bearer Auth.

Keeps the access token valid across both processes (main.py workers + FastAPI)
by sharing state through PostgreSQL and refreshing proactively in a background thread.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from .metrics import TOKEN_REFRESH_TOTAL

logger = logging.getLogger(__name__)

# Refresh when within this many hours of expiry (tokens last 24h)
PROACTIVE_REFRESH_HOURS = 4

# Minimum seconds between reactive refresh attempts (debounce)
REACTIVE_REFRESH_COOLDOWN = 60

# Background thread check interval in seconds
CHECK_INTERVAL = 300  # 5 minutes


class TokenManager:
    """Manages WordPress JWT token lifecycle with DB persistence and auto-refresh."""

    def __init__(
        self,
        db_pool,
        refresh_url: str,
        refresh_token: str,
        initial_access_token: str,
    ):
        """Initialize token manager.

        Args:
            db_pool: psycopg2 ThreadedConnectionPool (from QueueDB._pool)
            refresh_url: WordPress token refresh endpoint URL
            refresh_token: Long-lived refresh token for obtaining new access tokens
            initial_access_token: Current access token from .env (fallback)
        """
        self._pool = db_pool
        self._refresh_url = refresh_url
        self._refresh_token = refresh_token
        self._initial_token = initial_access_token

        self._access_token: str = initial_access_token
        self._expires_at: Optional[datetime] = None
        self._lock = threading.Lock()
        self._last_reactive_refresh: float = 0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def initialize(self):
        """Load token from DB, refresh if needed, start background thread."""
        # Try to load the latest valid token from DB
        db_token, db_expires = self._load_from_db()

        if db_token and db_expires and db_expires > datetime.now(timezone.utc):
            self._access_token = db_token
            self._expires_at = db_expires
            remaining = db_expires - datetime.now(timezone.utc)
            logger.info(
                'Loaded token from DB (expires in %.1f hours)',
                remaining.total_seconds() / 3600,
            )

            # Proactively refresh if close to expiry
            if remaining < timedelta(hours=PROACTIVE_REFRESH_HOURS):
                logger.info('Token close to expiry, refreshing proactively')
                self._do_refresh()
        else:
            # No valid DB token — try immediate refresh using initial token
            logger.info('No valid token in DB, attempting refresh')
            if not self._do_refresh():
                # Refresh failed — fall back to .env token
                logger.warning('Token refresh failed, using initial .env token')
                self._access_token = self._initial_token

        # Start background thread
        self._thread = threading.Thread(
            target=self._background_loop,
            name='token-refresh',
            daemon=True,
        )
        self._thread.start()
        logger.info('Token manager initialized, background thread started')

    def get_token(self) -> str:
        """Get the current access token (thread-safe)."""
        with self._lock:
            return self._access_token

    def handle_401(self):
        """Handle a 401 response by reactively refreshing the token.

        Debounced: won't attempt more than once per REACTIVE_REFRESH_COOLDOWN seconds.
        """
        now = time.monotonic()
        with self._lock:
            if now - self._last_reactive_refresh < REACTIVE_REFRESH_COOLDOWN:
                logger.debug('Reactive refresh skipped (cooldown)')
                return
            self._last_reactive_refresh = now

        logger.info('401 received, attempting reactive token refresh')
        self._do_refresh()

    def stop(self):
        """Stop the background refresh thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info('Token manager stopped')

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _do_refresh(self) -> bool:
        """Call the WordPress refresh endpoint and update the token.

        Returns True on success, False on failure.
        """
        if not self._refresh_token:
            logger.warning('No refresh token available, cannot refresh')
            return False

        try:
            headers = {
                'Authorization': f'Bearer {self._access_token}',
                'Content-Type': 'application/json',
            }
            payload = {'token': self._refresh_token}

            resp = requests.post(
                self._refresh_url,
                json=payload,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            new_token = data.get('access_token')
            expires_in = data.get('expires_in', 86400)  # default 24h

            if not new_token:
                logger.error('Refresh response missing access_token: %s', data)
                return False

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            with self._lock:
                self._access_token = new_token
                self._expires_at = expires_at

            # Persist to DB
            self._save_to_db(new_token, expires_at)

            TOKEN_REFRESH_TOTAL.labels(result='success').inc()
            logger.info(
                'Token refreshed successfully (expires in %.1f hours)',
                expires_in / 3600,
            )
            return True

        except requests.RequestException as e:
            TOKEN_REFRESH_TOTAL.labels(result='error').inc()
            logger.error('Token refresh failed: %s', e)
            return False
        except Exception as e:
            TOKEN_REFRESH_TOTAL.labels(result='error').inc()
            logger.error('Unexpected error during token refresh: %s', e)
            return False

    def _background_loop(self):
        """Background thread: check token expiry periodically."""
        while not self._stop_event.is_set():
            self._stop_event.wait(CHECK_INTERVAL)
            if self._stop_event.is_set():
                break

            try:
                # Also reload from DB in case the other process refreshed
                db_token, db_expires = self._load_from_db()
                if db_token and db_expires:
                    with self._lock:
                        # Use the DB token if it expires later than ours
                        if self._expires_at is None or db_expires > self._expires_at:
                            self._access_token = db_token
                            self._expires_at = db_expires
                            logger.info('Picked up newer token from DB')

                with self._lock:
                    expires_at = self._expires_at

                if expires_at is None:
                    # Unknown expiry — try refresh
                    logger.info('Token expiry unknown, attempting refresh')
                    self._do_refresh()
                    continue

                remaining = expires_at - datetime.now(timezone.utc)
                if remaining < timedelta(hours=PROACTIVE_REFRESH_HOURS):
                    logger.info(
                        'Token expires in %.1f hours, refreshing proactively',
                        remaining.total_seconds() / 3600,
                    )
                    self._do_refresh()
                else:
                    logger.debug(
                        'Token OK, expires in %.1f hours',
                        remaining.total_seconds() / 3600,
                    )
            except Exception as e:
                logger.error('Error in token refresh background loop: %s', e)

    def _load_from_db(self) -> tuple[Optional[str], Optional[datetime]]:
        """Load the latest token from the auth_tokens table."""
        conn = None
        try:
            conn = self._pool.getconn()
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT access_token, expires_at
                       FROM auth_tokens
                       ORDER BY created_at DESC
                       LIMIT 1"""
                )
                row = cur.fetchone()
            if row:
                return row[0], row[1]
            return None, None
        except Exception as e:
            logger.error('Failed to load token from DB: %s', e)
            return None, None
        finally:
            if conn:
                self._pool.putconn(conn)

    def _save_to_db(self, access_token: str, expires_at: datetime):
        """Persist a new token to the auth_tokens table."""
        conn = None
        try:
            conn = self._pool.getconn()
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO auth_tokens (access_token, expires_at)
                       VALUES (%s, %s)""",
                    (access_token, expires_at),
                )
            conn.commit()
            logger.debug('Token persisted to DB')
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error('Failed to save token to DB: %s', e)
        finally:
            if conn:
                self._pool.putconn(conn)


def load_refresh_token(file_path: str = '/app/.refresh_token') -> str:
    """Load the refresh token from file or environment variable.

    Args:
        file_path: Path to the .refresh_token file

    Returns:
        The refresh token string, or empty string if not found.
    """
    # Try file first
    path = Path(file_path)
    if path.exists():
        token = path.read_text().strip()
        if token:
            logger.info('Refresh token loaded from file: %s', file_path)
            return token

    # Fall back to environment variable
    import os
    token = os.getenv('API_REFRESH_TOKEN', '').strip()
    if token:
        logger.info('Refresh token loaded from API_REFRESH_TOKEN env var')
        return token

    logger.warning('No refresh token found (checked %s and API_REFRESH_TOKEN)', file_path)
    return ''
