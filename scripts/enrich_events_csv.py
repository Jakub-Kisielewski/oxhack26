#!/usr/bin/env python3
"""One-off enricher: add organiser, motivation, starttime, finishtime, turnout to events.csv."""
from __future__ import annotations

import csv
from pathlib import Path

NOT_REPORTED = "not_reported"

# Per-event curation: organiser, motivation, starttime, finishtime, turnout.
ENRICHMENT: dict[str, dict[str, str]] = {
    "2022-06-18-tuc": {
        "organiser": "Trades Union Congress (TUC)",
        "motivation": "Cost-of-living crisis; public services and workers' rights ('Britain Demands Better')",
        "starttime": "11:00",
        "finishtime": "16:00",
        "turnout": "100000",
    },
    "2023-10-21-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Solidarity with Palestine; oppose military action in Gaza",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2023-11-11-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "National march for Palestine; ceasefire and end to occupation",
        "starttime": "12:00",
        "finishtime": "17:00",
        "turnout": NOT_REPORTED,
    },
    "2024-01-13-012": {
        "organiser": "Palestine solidarity coalition (London)",
        "motivation": "Support for Gaza; national Palestine demonstration",
        "starttime": NOT_REPORTED,
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-02-03-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "National march for Palestine; ceasefire now",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-02-17-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Stop the genocide in Gaza; march to Israeli Embassy area",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-03-09-013": {
        "organiser": "Palestine Coalition (with PCS union support)",
        "motivation": "National march for Palestine; US Embassy demonstration",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-03-30-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Ceasefire now; stop the genocide in Gaza",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-05-18-psc": {
        "organiser": "Palestine Coalition",
        "motivation": "Nakba anniversary global day of action for Gaza",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-06-08-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "End the genocide; stop arming Israel",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-06-22-restore": {
        "organiser": "Restore Nature Now coalition",
        "motivation": "Climate and nature restoration; mass lobby of Parliament",
        "starttime": "12:00",
        "finishtime": "16:00",
        "turnout": "60000",
    },
    "2024-10-05-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Palestine solidarity march ahead of 7 October anniversary period",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-10-26-sutr": {
        "organiser": "Stand Up To Racism",
        "motivation": "Anti-racist counter-demonstration on same day as rival marches",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-10-26-utk": {
        "organiser": "Uniting the Kingdom",
        "motivation": "Pro-UK unity march; counter to concurrent demonstrations",
        "starttime": "11:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2024-11-02-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Palestine march via US Embassy Nine Elms area",
        "starttime": "12:45",
        "finishtime": "16:00",
        "turnout": NOT_REPORTED,
    },
    "2024-11-30-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "National demonstration for Palestine",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-03-15-014": {
        "organiser": "Palestine Coalition",
        "motivation": "National march for Palestine",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-03-22-015": {
        "organiser": "For the Children campaign",
        "motivation": "Protest for children affected by conflict (Gaza and wider)",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-03-23-016": {
        "organiser": "Al Quds Day organisers (London)",
        "motivation": "Al Quds (Jerusalem) Day solidarity procession",
        "starttime": "14:30",
        "finishtime": "17:30",
        "turnout": NOT_REPORTED,
    },
    "2025-05-17-nakba": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Nakba 77 national demonstration for Palestine",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-06-21-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "National demonstration for Palestine",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-08-09-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Stop starving Gaza; stop arming Israel",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-09-06-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "National march for Palestine; stop starving Gaza",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-09-13-sutr": {
        "organiser": "Stand Up To Racism",
        "motivation": "Anti-racist counter-march (same day as Unite the Kingdom)",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-09-13-utk": {
        "organiser": "Unite the Kingdom",
        "motivation": "Unity march; concurrent with Stand Up To Racism counter-march",
        "starttime": "11:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-09-17-stoptrump": {
        "organiser": "Stop Trump Coalition",
        "motivation": "Oppose Donald Trump UK state visit and policies",
        "starttime": "13:00",
        "finishtime": "17:00",
        "turnout": NOT_REPORTED,
    },
    "2025-10-11-018": {
        "organiser": "Association of Academics in Exile",
        "motivation": "Rights and visibility for exiled academics",
        "starttime": "11:30",
        "finishtime": NOT_REPORTED,
        "turnout": "300",
    },
    "2025-10-11-pc": {
        "organiser": "Palestine Coalition",
        "motivation": "National Palestine Coalition march",
        "starttime": "12:00",
        "finishtime": "17:30",
        "turnout": NOT_REPORTED,
    },
    "2025-10-18-019": {
        "organiser": "No to Digital ID campaign",
        "motivation": "Oppose mandatory digital identity schemes",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-11-01-020": {
        "organiser": "National Animal Rights March organisers",
        "motivation": "Animal liberation and anti-speciesism",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "2000",
    },
    "2025-11-15-021": {
        "organiser": "Iran Future Kingdom",
        "motivation": "Political change in Iran; march to Iranian Embassy",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2025-12-20-022": {
        "organiser": "London for Sudan",
        "motivation": "Solidarity with Sudan; oppose conflict and humanitarian crisis",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "250",
    },
    "2026-01-31-023": {
        "organiser": "Palestine solidarity organisers (London)",
        "motivation": "March for Palestine; ceasefire and end to bombardment",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-02-07-024": {
        "organiser": "Stage of Freedom campaign",
        "motivation": "Iran-related 'Stage of Freedom' protest",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-02-28-025": {
        "organiser": "Stage for Freedom campaign",
        "motivation": "Iran political freedom; embassy-directed march",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": "2000",
    },
    "2026-03-07-026": {
        "organiser": "Stage for Freedom campaign",
        "motivation": "Iran political freedom; Whitehall to Iranian Embassy",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": "2000",
    },
    "2026-03-08-027": {
        "organiser": "Amhara Community (London)",
        "motivation": "Amhara community rights and Ethiopia conflict solidarity",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "200",
    },
    "2026-03-21-psc": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Ceasefire; stop bombing Iran; hands off Lebanon; free Palestine",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-03-28-028": {
        "organiser": "Iranian Academics in Exile",
        "motivation": "Support exiled Iranian academics",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "1000-1500",
    },
    "2026-03-28-029": {
        "organiser": "Stand Up To Racism",
        "motivation": "Anti-racism coalition march",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-03-28-together": {
        "organiser": "Together Alliance",
        "motivation": "Anti-racism and inclusive society demonstration",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-04-25-030": {
        "organiser": "Armenian Community (London)",
        "motivation": "Armenian community recognition; march to Cenotaph",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "250",
    },
    "2026-05-16-nakba": {
        "organiser": "Palestine Solidarity Campaign (PSC)",
        "motivation": "Nakba 78 march for Palestine",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-05-23-031": {
        "organiser": "Amhara Association (London)",
        "motivation": "Amhara community advocacy",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": "500",
    },
    "2026-05-23-032": {
        "organiser": "Ichthus Christian Fellowship",
        "motivation": "Religious procession and public witness (non-political protest)",
        "starttime": "14:00",
        "finishtime": NOT_REPORTED,
        "turnout": "10000",
    },
    "2026-05-24-033": {
        "organiser": "International Society for Krishna Consciousness (Rathayatra)",
        "motivation": "Annual Rathayatra Hindu festival procession",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "6000",
    },
    "2026-06-06-034": {
        "organiser": "Stage for Freedom campaign",
        "motivation": "Iran freedom march to Iranian Embassy",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": "200",
    },
    "2026-06-14-035": {
        "organiser": "Ukrainian community (Vyshyvanka March)",
        "motivation": "Cultural Vyshyvanka march; Ukraine solidarity",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-06-20-036": {
        "organiser": "Lesbian Pride Parade organisers",
        "motivation": "Lesbian visibility and pride",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "3000",
    },
    "2026-06-25-037": {
        "organiser": "Hussaini Association",
        "motivation": "Shia religious procession (Ashura period)",
        "starttime": "16:00",
        "finishtime": NOT_REPORTED,
        "turnout": "1000",
    },
    "2026-07-04-pride": {
        "organiser": "Pride in London",
        "motivation": "LGBTQ+ pride parade and equality",
        "starttime": "12:00",
        "finishtime": "18:00",
        "turnout": "30000",
    },
    "2026-07-11-038": {
        "organiser": "Stage for Freedom campaign",
        "motivation": "Iran freedom march to Iranian Embassy",
        "starttime": "13:00",
        "finishtime": NOT_REPORTED,
        "turnout": "200",
    },
    "2026-07-18-017": {
        "organiser": "Palestine Coalition",
        "motivation": "National march for Palestine (Met conditions route)",
        "starttime": "12:45",
        "finishtime": "17:30",
        "turnout": NOT_REPORTED,
    },
    "2026-07-18-039": {
        "organiser": "Sindhi Association (London)",
        "motivation": "Sindhi cultural and community procession",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "200",
    },
    "2026-07-25-transpride": {
        "organiser": "London Trans+ Pride",
        "motivation": "Trans rights and visibility",
        "starttime": "13:00",
        "finishtime": "17:00",
        "turnout": NOT_REPORTED,
    },
    "2026-07-30-040": {
        "organiser": "Joint Awami Action Committee",
        "motivation": "Pakistan political solidarity; march to High Commission",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "3000",
    },
    "2026-08-08-041": {
        "organiser": "Hussaini Association",
        "motivation": "Shia religious procession",
        "starttime": "16:30",
        "finishtime": NOT_REPORTED,
        "turnout": "1000",
    },
    "2026-08-09-042": {
        "organiser": "Hussaini Association",
        "motivation": "Shia religious procession (Park Lane loop)",
        "starttime": "14:00",
        "finishtime": NOT_REPORTED,
        "turnout": "3000",
    },
    "2026-08-22-043": {
        "organiser": "National Animal Rights March organisers",
        "motivation": "Animal liberation march",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": "2000",
    },
    "2026-09-05-044": {
        "organiser": "Wang Wang campaign",
        "motivation": "Protest related to Wang Wang / China human-rights issue",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-09-19-045": {
        "organiser": "Time to Help UK",
        "motivation": "Charity Walk 2 Water fundraising march",
        "starttime": "14:00",
        "finishtime": NOT_REPORTED,
        "turnout": "100",
    },
    "2026-09-20-046": {
        "organiser": "Stage of Freedom campaign",
        "motivation": "Iran freedom protest march",
        "starttime": "14:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-10-04-cable": {
        "organiser": "Cable Street commemoration organisers",
        "motivation": "Commemorate 1936 Battle of Cable Street; anti-fascism",
        "starttime": "12:00",
        "finishtime": NOT_REPORTED,
        "turnout": NOT_REPORTED,
    },
    "2026-10-07-student": {
        "organiser": "University of London Coalition",
        "motivation": "Student protest (Section 12 conditions route)",
        "starttime": "12:30",
        "finishtime": "14:00",
        "turnout": NOT_REPORTED,
    },
    "2026-10-10-pc": {
        "organiser": "Palestine Coalition",
        "motivation": "National Palestine Coalition demonstration",
        "starttime": "12:00",
        "finishtime": "18:30",
        "turnout": NOT_REPORTED,
    },
}

OUT_FIELDS = [
    "event_id",
    "event_date",
    "event_name",
    "event_category",
    "organiser",
    "motivation",
    "official_planned_waypoints",
    "starttime",
    "finishtime",
    "turnout",
    "route_detail",
    "source_url",
    "evidence_type",
    "observed_route_verified",
    "notes",
]


def merge_row(row: dict[str, str]) -> dict[str, str]:
    eid = row["event_id"]
    if eid not in ENRICHMENT:
        raise KeyError(f"Missing enrichment for {eid}")
    extra = ENRICHMENT[eid]
    # Prefer explicit source times/turnout when present in legacy columns.
    start = row.get("start_or_assembly_time") or extra["starttime"]
    finish = row.get("end_or_rally_finish_time") or extra["finishtime"]
    turnout = row.get("attendance_estimate_pre_event") or extra["turnout"]
    if not start:
        start = extra["starttime"]
    if not finish:
        finish = extra["finishtime"]
    if not turnout:
        turnout = extra["turnout"]
    return {
        "event_id": row["event_id"],
        "event_date": row["event_date"],
        "event_name": row["event_name"],
        "event_category": row["event_category"],
        "organiser": extra["organiser"],
        "motivation": extra["motivation"],
        "official_planned_waypoints": row["official_planned_waypoints"],
        "starttime": start,
        "finishtime": finish,
        "turnout": turnout,
        "route_detail": row["route_detail"],
        "source_url": row["source_url"],
        "evidence_type": row["evidence_type"],
        "observed_route_verified": row["observed_route_verified"],
        "notes": row["notes"],
    }


def main() -> None:
    path = Path("src/ingestion/protest_routes/seed/events.csv")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out_rows = [merge_row(r) for r in rows]
    assert len(out_rows) == 65
    for r in out_rows:
        for key in ("organiser", "motivation", "starttime", "finishtime", "turnout"):
            assert r[key], f"{r['event_id']}: empty {key}"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows)} rows to {path}")


if __name__ == "__main__":
    main()
