"""Shared direction parsing for LUAS, DART, and commuter utterances."""
from __future__ import annotations

import re
import unicodedata

CARDINALS = {
    "northbound": "northbound", "north": "northbound", "nb": "northbound",
    "northward": "northbound", "northwards": "northbound",
    "nortbound": "northbound", "norbound": "northbound", "northboud": "northbound",
    "southbound": "southbound", "south": "southbound", "sb": "southbound",
    "southward": "southbound", "southwards": "southbound",
    "souhbound": "southbound", "southboud": "southbound",
    "eastbound": "eastbound", "east": "eastbound", "eb": "eastbound",
    "eastward": "eastbound", "eastwards": "eastbound",
    "eastboud": "eastbound",
    "westbound": "westbound", "west": "westbound", "wb": "westbound",
    "westward": "westbound", "westwards": "westbound",
    "westboud": "westbound",
}

CITY_PHRASES = frozenset({
    "the city", "city", "city centre", "city center", "into town", "town",
    "into the city", "towards the city", "toward the city",
})

_TOWARDS_PREFIX = re.compile(r"^(?:towards|toward|to|going|heading)\s+", re.I)

# Trailing direction Alexa often glues onto the station slot ("Clontarf Road nortbound").
_DIRECTION_TAIL = re.compile(
    r"[\s,]+("
    r"(?:going|heading)\s+(?:north|nort|south|souh|east|west)(?:\s*bound)?"
    r"|(?:north|nort|nor|south|souh|east|west)\s*bound"
    r"|north\s*bound|south\s*bound|east\s*bound|west\s*bound"
    r"|north|south|east|west"
    r"|(?:towards?|into)\s+the\s+city(?:\s+centre|\s+center)?"
    r"|(?:towards?|into)\s+town"
    r"|the\s+city(?:\s+centre|\s+center)?"
    r"|(?:towards?|toward|to)\s+.+"
    r")\s*$",
    re.I,
)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.casefold()


def parse_direction(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    if not raw or raw == "?":
        return None
    key = _fold(_TOWARDS_PREFIX.sub("", raw))
    key = re.sub(r"[^a-z0-9]+", " ", key)
    key = re.sub(r"\b(north|nort|nor|south|souh|east|west)\s+bound\b", r"\1bound", key)
    key = re.sub(r"^the\s+", "", key)
    key = " ".join(key.split())
    if not key:
        return None
    if key in CARDINALS:
        return CARDINALS[key]
    if key in {_fold(p).replace("&", " and ") for p in CITY_PHRASES} or key in CITY_PHRASES:
        return "city"
    return key


def peel_direction_suffix(text: str) -> tuple[str, str | None]:
    """Split a trailing direction phrase off a station utterance, if present."""
    raw = (text or "").strip()
    if not raw:
        return raw, None
    m = _DIRECTION_TAIL.search(raw)
    if not m:
        return raw, None
    head = raw[:m.start()].strip(" ,")
    suffix = m.group(1).strip()
    if not head or not parse_direction(suffix):
        return raw, None
    return head, suffix


def split_station_and_direction(
    station_text: str | None, direction_text: str | None,
) -> tuple[str | None, str | None]:
    """Return (station name, parsed direction), recovering a direction glued to the station."""
    raw_station = (station_text or "").strip() or None
    explicit = parse_direction(direction_text)
    if not raw_station:
        return None, explicit
    head, suffix = peel_direction_suffix(raw_station)
    peeled = parse_direction(suffix) if suffix else None
    station = head if (peeled and head) else raw_station
    return station, explicit or peeled
