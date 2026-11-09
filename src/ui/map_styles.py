"""Map route line styles (audit palette)."""

from __future__ import annotations

MAP_LAYER_STYLES: dict[str, dict] = {
    "actual_casing": {"hex": "#1F2937", "width": 9, "alpha": 130, "dash": None},
    "route_model": {"hex": "#1D4ED8", "width": 4, "alpha": 255, "dash": None},
    "shortest_path": {"hex": "#DC2626", "width": 3, "alpha": 255, "dash": [10, 6]},
    "random_walk": {"hex": "#7C3AED", "width": 3, "alpha": 255, "dash": [4, 6]},
}

LAYER_PILL_COLORS: dict[str, str] = {
    "Actual": "#1F2937",
    "Route model": "#1D4ED8",
    "Shortest path": "#DC2626",
    "Random walk": "#7C3AED",
    "Zone boundary": "#94A3B8",
    "Restricted zones": "#FECACA",
}
