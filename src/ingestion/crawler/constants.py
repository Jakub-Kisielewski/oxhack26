"""Named tuning constants for discovery crawler and CLI."""

from __future__ import annotations

SUPPRESSION_SCAN_CHARS = 800
MAX_ARCHIVE_PAGES = 20
MIN_PARAGRAPH_CHARS = 25
MIN_PARAGRAPH_CHARS_SHORT = 15
MIN_DIV_CHUNK_CHARS = 20

DEFAULT_MET_LIMIT = 8

DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_MIN_INTERVAL_SEC = 0.35

DISCOVERY_USER_AGENT = (
    "LondonProtestPredictor/0.1 (academic research; "
    "contact via https://github.com/crislu05/london-protest-predictor)"
)
