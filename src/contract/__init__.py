"""Single entry point for the visual layer: `from src.contract import get_predictor`.

PREDICTOR environment variable: "mock", "real", or "auto" (default). "auto" uses the
real model when its artefacts exist (src.models.predictor.RealPredictor.available()),
otherwise the mock.
"""
from __future__ import annotations

import os

from src.contract.api import Predictor
from src.contract.types import CONTRACT_VERSION


def get_predictor() -> Predictor:
    choice = os.environ.get("PREDICTOR", "auto").lower()
    if choice in ("real", "auto"):
        try:
            from src.models.predictor import RealPredictor
            if choice == "real" or RealPredictor.available():
                return RealPredictor()
        except ImportError:
            if choice == "real":
                raise
    from src.contract.mock import MockPredictor
    return MockPredictor()


__all__ = ["get_predictor", "Predictor", "CONTRACT_VERSION"]
