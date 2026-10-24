from __future__ import annotations

from typing import Any

from ingestion.crawler.sources.organizers.sites import ORGANIZER_SITES

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
    "marble_arch_security": {
        "platform_id": "marble_arch_security",
        "platform_name": "Marble Arch London (Security Updates)",
        "platform_url": "https://marble-arch.london/security-updates/",
    },
}

for _site in ORGANIZER_SITES:
    PLATFORM_CATALOG[_site.platform_id] = {
        "platform_id": _site.platform_id,
        "platform_name": _site.platform_name,
        "platform_url": _site.platform_url,
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
    if hasattr(record, "to_dict"):
        data = record.to_dict()
    elif hasattr(record, "model_dump"):
        data = record.model_dump()
    else:
        data = dict(record)
    data.update(platform_meta(data.get("source", "")))
    return data
