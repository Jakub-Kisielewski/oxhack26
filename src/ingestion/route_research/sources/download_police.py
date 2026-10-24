#!/usr/bin/env python3
"""Download month-level, anonymised UK Police API public-order crime points.

These data ARE NOT identified protest events and ARE NOT crowd trajectories.
Output is suitable only for a historical public-order crime context layer.

Run:
    pip install requests
    python fetch_public_order.py --months 2024-10 2025-03 2025-09 2025-10

API: https://data.police.uk/docs/method/crime-street/
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Approximate centres; the API returns incidents within ~1 mile of each.
# Multiple circles overlap; duplicates removed by month and police record ID.
CENTRES = {
    "Whitehall": (51.5033, -0.1264),
    "Trafalgar Square": (51.5080, -0.1281),
    "Russell Square": (51.5225, -0.1251),
    "Marble Arch": (51.5136, -0.1586),
    "Waterloo": (51.5031, -0.1133),
}
FIELDS = ["month", "category", "latitude", "longitude", "street", "location_type", "police_record_id"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--months", nargs="+", default=["2024-10", "2025-09", "2025-10"],
                   help="Available police data months, YYYY-MM (not protest event dates)")
    p.add_argument("--output", default="raw/police/police_public_order_context.csv")
    args = p.parse_args()

    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    rows, seen = [], set()
    for month in args.months:
        for place, (lat, lng) in CENTRES.items():
            try:
                resp = session.get("https://data.police.uk/api/crimes-street/public-order",
                                   params={"lat": lat, "lng": lng, "date": month}, timeout=35)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise ValueError("Unexpected response shape")
            except (requests.RequestException, ValueError) as e:
                print(f"WARNING: {month} {place}: {e}", file=sys.stderr)
                continue
            before = len(rows)
            for item in data:
                loc = item.get("location") or {}
                record_id = item.get("id")
                key = (item.get("month", month), record_id if record_id is not None else
                       (loc.get("latitude"), loc.get("longitude"), (loc.get("street") or {}).get("name")))
                if key in seen: continue
                seen.add(key)
                rows.append({"month": item.get("month", month),
                             "category": item.get("category"),
                             "latitude": loc.get("latitude"),
                             "longitude": loc.get("longitude"),
                             "street": (loc.get("street") or {}).get("name"),
                             "location_type": item.get("location_type"),
                             "police_record_id": record_id})
            print(f"{month}, {place}: received {len(data)}, new {len(rows)-before}")
            time.sleep(0.25)  # Small courtesy gap; watch API usage guidance
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} deduplicated anonymous public-order crime records to {out}")
    print("IMPORTANT: Record month and anonymised point != incident date, protest route or observed crowd position.")

if __name__ == "__main__":
    main()
