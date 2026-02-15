#!/usr/bin/env python3
"""Custom uvicorn runner with proper logging configuration."""

import logging
import uvicorn

from src.log_buffer import get_log_buffer

if __name__ == "__main__":
    # Configure logging BEFORE starting uvicorn
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Initialize log buffer to capture all logs
    log_buffer = get_log_buffer()

    print(f"Log buffer initialized with {len(log_buffer.buffer)} entries")
    print(f"Starting uvicorn on 0.0.0.0:8000...")

    # Run uvicorn with custom log config
    uvicorn.run(
        "src.api:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=False,  # Disable access logs to reduce noise
    )
