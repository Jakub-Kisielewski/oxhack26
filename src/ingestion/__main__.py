"""Run protest ingestion: ``python -m src.ingestion`` from repo root."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ingestion.crawler.cli import _ensure_project_python, main

_ensure_project_python()
main()
