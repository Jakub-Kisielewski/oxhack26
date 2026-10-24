from __future__ import annotations

from typing import Any

PLATFORM_CATALOG: dict[str, dict[str, str]] = {
    "met_police": {
        "platform_id": "met_police",
        "platform_name": "Met Police Newsroom",
        "platform_url": "https://news.met.police.uk",
    },
    "osac": {
        "platform_id": "osac",
        "platform_name": "US OSAC (Embassy Demonstration Alerts)",
        "platform_url": "https://www.osac.gov",
    },
    "tfl_road_disruption": {
        "platform_id": "tfl_road_disruption",
        "platform_name": "TfL Unified API (Road Disruptions)",
        "platform_url": "https://api.tfl.gov.uk",
    },
}


def platform_meta(platform_id: str) -> dict[str, str]:
    return PLATFORM_CATALOG.get(
        platform_id,
        {
            "platform_id": platform_id,
            "platform_name": platform_id,
            "platform_url": "",
        },
    )


def record_export_dict(record: Any) -> dict[str, Any]:
    payload = record.to_dict()
    meta = platform_meta(payload["source"])
    payload["platform_id"] = meta["platform_id"]
    payload["platform_name"] = meta["platform_name"]
    payload["platform_url"] = meta["platform_url"]
    return payload
