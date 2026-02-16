"""Centralized Prometheus metric definitions for emby-processor.

All metric objects are defined here and imported by other modules.
Uses multiprocess mode so both main.py workers and FastAPI share metrics
through a shared directory (PROMETHEUS_MULTIPROC_DIR).
"""

from prometheus_client import Counter, Gauge, Histogram

# ---- Counters ----

PIPELINE_ITEMS_TOTAL = Counter(
    'emby_pipeline_items_total',
    'Total pipeline items processed by stage and result',
    ['stage', 'result'],
)

API_REQUESTS_TOTAL = Counter(
    'emby_api_requests_total',
    'Total external API requests by service and status',
    ['service', 'status'],
)

TOKEN_REFRESH_TOTAL = Counter(
    'emby_token_refresh_total',
    'Total token refresh attempts by result',
    ['result'],
)

FILES_DETECTED_TOTAL = Counter(
    'emby_files_detected_total',
    'Total new video files detected by the watcher',
)

# ---- Histograms ----

API_REQUEST_DURATION = Histogram(
    'emby_api_request_duration_seconds',
    'Duration of external API requests',
    ['service', 'operation'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

DASHBOARD_REQUEST_DURATION = Histogram(
    'emby_dashboard_request_duration_seconds',
    'Duration of dashboard HTTP requests',
    ['method', 'endpoint', 'status_code'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# ---- Gauges ----
# Use multiprocess_mode='liveall' so each process reports its own value.

QUEUE_DEPTH = Gauge(
    'emby_queue_depth',
    'Current queue depth by status',
    ['status'],
    multiprocess_mode='liveall',
)

DOWNLOADS_DEPTH = Gauge(
    'emby_downloads_depth',
    'Current download jobs depth by status',
    ['status'],
    multiprocess_mode='liveall',
)

WORKER_LAST_ACTIVE = Gauge(
    'emby_worker_last_active_timestamp',
    'Unix timestamp of last worker activity',
    ['worker'],
    multiprocess_mode='liveall',
)

# ---- Info (via gauge, multiprocess-compatible) ----

PROCESSOR_VERSION = Gauge(
    'emby_processor_build_info',
    'Emby processor build information (value is always 1)',
    ['version'],
    multiprocess_mode='liveall',
)
PROCESSOR_VERSION.labels(version='0.5.0').set(1)
