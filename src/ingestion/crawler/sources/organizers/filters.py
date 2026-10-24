from __future__ import annotations

import re

LONDON_TERMS: tuple[str, ...] = (
    "london",
    "westminster",
    "whitehall",
    "trafalgar",
    "hyde park",
    "parliament square",
    "embankment",
    "marble arch",
    "grosvenor square",
    "new scotland yard",
    "central london",
    "city of london",
    "lewisham",
    "brixton",
    "camden",
    "islington",
    "hackney",
    "greenwich",
    "croydon",
    "southwark",
    "lambeth",
    "tower hamlets",
    "newham",
    "waltham forest",
    "haringey",
    "ealing",
    "hounslow",
    "brent",
    "hammersmith",
    "kensington",
    "chelsea",
    "wandsworth",
    "stratford",
    "oxford circus",
    "piccadilly",
)

# Primary action vocabulary — title or body must match one of these (see is_london_protest_event).
PRIMARY_PROTEST_TERMS: tuple[str, ...] = (
    "demonstration",
    " demo ",
    "demo,",
    " demo.",
    "national demo",
    "march",
    "rally",
    "protest",
    "day of action",
    "national march",
    "mass march",
    "counter-protest",
    "counter protest",
    "blockade",
    "sit-in",
    "sit in",
    "swarm",
    "swarming",
    "disrupt",
    "occupation",
    "picket",
    "vigil",
    "court support",
    "arrest",
)

NON_PROTEST_MEETING: tuple[str, ...] = (
    "public meeting",
    "annual general meeting",
    " agm",
    "craft fair",
    "webinar",
    "volunteer meeting",
    "training day",
    "workshop",
    "fundraising",
    "conference",
    "summit",
    "ticketed event",
)

UK_NON_LONDON: tuple[str, ...] = (
    "manchester",
    "birmingham",
    "brighton",
    "nottingham",
    "leeds",
    "liverpool",
    "sheffield",
    "bristol",
    "newcastle",
    "glasgow",
    "edinburgh",
    "cardiff",
    "belfast",
    "bradford",
    "lancashire",
    "scottish",
    "batley",
    "blackburn",
)


def _pad(text: str) -> str:
    return f" {text.lower()} "


def mentions_london(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in LONDON_TERMS)


def has_primary_protest_language(title: str, body: str) -> bool:
    title_padded = _pad(title)
    body_padded = _pad(body)
    for term in PRIMARY_PROTEST_TERMS:
        if term in title_padded or term in body_padded:
            return True
    combined = f"{title} {body}".lower().replace("-", " ")
    if "demo" in combined:
        return True
    return False


def looks_like_non_protest_meeting(text: str) -> bool:
    padded = _pad(text)
    return any(term in padded for term in NON_PROTEST_MEETING)


def is_london_protest_event(*, title: str, body: str, url: str) -> bool:
    combined = f"{title} {body} {url}"
    lowered = combined.lower()

    if not mentions_london(lowered):
        return False

    body_lower = body.lower()
    title_lower = title.lower()
    url_lower = url.lower()
    for city in UK_NON_LONDON:
        if city not in lowered:
            continue
        if "london" in lowered or "westminster" in lowered:
            continue
        if city in title_lower or city in url_lower or city in body_lower:
            return False

    if not has_primary_protest_language(title, body):
        return False

    if looks_like_non_protest_meeting(lowered) and not has_primary_protest_language(
        title, body
    ):
        return False

    return True


EVENT_SLUG_SKIP: frozenset[str] = frozenset(
    {"list", "category", "tags", "tag", "page", "feed"}
)
EVENT_SLUG_RE = re.compile(r"/events/([a-z0-9][a-z0-9-]{2,})/?", re.I)


def event_slug_pattern(prefix: str) -> re.Pattern[str]:
    segment = prefix.strip("/")
    return re.compile(rf"/{re.escape(segment)}/([a-z0-9][a-z0-9-]{{2,}})/?", re.I)
DATE_POST_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/", re.I)
ACTIONNETWORK_EVENT_RE = re.compile(
    r"actionnetwork\.org/(?:events|ticketed_events)/([a-z0-9_-]+)",
    re.I,
)
AN_EVENT_QUERY_RE = re.compile(r"[?&]an_event=([a-f0-9-]{36})", re.I)
