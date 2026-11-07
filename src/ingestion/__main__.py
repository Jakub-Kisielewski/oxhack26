"""Run protest ingestion: ``python -m ingestion`` after ``pip install -e .``."""

from __future__ import annotations

from ingestion.crawler.cli import main

raise SystemExit(main())
