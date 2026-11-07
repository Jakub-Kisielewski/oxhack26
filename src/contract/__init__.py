"""Visual-layer entry points; map reads delegate to ``src.database``."""

from src.database import mapdata

__all__ = ["mapdata"]
