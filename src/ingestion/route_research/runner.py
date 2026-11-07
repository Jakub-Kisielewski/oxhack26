"""Run a step CLI in the pipeline workspace (no ``sys.argv`` mutation)."""

from __future__ import annotations

import os
from collections.abc import Callable

from src.ingestion.route_research.context import StepContext

# Steps default to paths relative to workdir; chdir is confined here (not sys.argv).

StepMain = Callable[[list[str] | None], int | None]


def run_cli_step(main: StepMain, context: StepContext, argv: list[str] | None = None) -> int:
    previous = os.getcwd()
    os.chdir(context.workdir)
    try:
        try:
            outcome = main(argv)
            return 0 if outcome is None else int(outcome)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            return int(code) if isinstance(code, int) else 1
    finally:
        os.chdir(previous)
