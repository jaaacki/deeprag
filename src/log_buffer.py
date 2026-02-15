"""In-memory log buffer for dashboard access."""

import logging
from collections import deque
from datetime import datetime
from typing import List


class LogBuffer(logging.Handler):
    """Custom logging handler that stores recent log messages in memory."""

    def __init__(self, maxlen: int = 500):
        """Initialize the log buffer.

        Args:
            maxlen: Maximum number of log messages to store (default 500)
        """
        super().__init__()
        self.buffer = deque(maxlen=maxlen)
        self.formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def emit(self, record: logging.LogRecord):
        """Add a log record to the buffer."""
        try:
            msg = self.format(record)
            self.buffer.append({
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'formatted': msg,
            })
        except Exception:
            self.handleError(record)

    def get_recent_logs(self, lines: int = 100) -> List[str]:
        """Get recent log messages as formatted strings.

        Args:
            lines: Number of recent log lines to return

        Returns:
            List of formatted log message strings
        """
        # Get last N entries from the buffer
        recent = list(self.buffer)[-lines:]
        return [entry['formatted'] for entry in recent]

    def clear(self):
        """Clear all buffered logs."""
        self.buffer.clear()


# Global log buffer instance
_log_buffer = None


def get_log_buffer() -> LogBuffer:
    """Get or create the global log buffer instance."""
    global _log_buffer
    if _log_buffer is None:
        _log_buffer = LogBuffer(maxlen=500)
        # Add to root logger to capture all logs
        logging.getLogger().addHandler(_log_buffer)
    return _log_buffer
