"""DuckDB connection, loader, and read-only mapdata for the training pipeline."""

from src.database import mapdata
from src.database.db import get_connection, init_schema
from src.database.load import load

__all__ = ["get_connection", "init_schema", "load", "mapdata"]
