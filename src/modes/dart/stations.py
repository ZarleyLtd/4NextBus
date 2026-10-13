"""DART station names, direction aliases, and north/south matching.

Irish Rail GTFS gives one stop_id per station (not one per platform). Trips in
both directions share that id; we split them into virtual platforms by whether
each headsign is north or south of the station on the DART line.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.modes.direction import parse_direction, peel_direction_suffix, split_station_and_direction

# North (small) -> south (large). Howth and Malahide branches both sit north of
# Howth Junction so "northbound" there covers both spurs.
LINE_ORDER = {
    "Howth": 10,
    "Malahide": 15,
    "Sutton": 20,
    "Portmarnock": 25,
    "Bayside": 30,
    "Clongriffin": 35,
    "Howth Junction and Donaghmede": 40,
    "Kilbarrack": 50,
    "Raheny": 60,
    "Harmonstown": 70,
    "Killester": 80,
    "Clontarf Road": 90,
    "Connolly": 100,
    "Tara Street": 110,
    "Dublin Pearse": 120,
    "Grand Canal Dock": 130,
    "Lansdowne Road": 140,
    "Sandymount": 150,
    "Sydney Parade": 160,
    "Booterstown": 170,
    "Blackrock": 180,
    "Seapoint": 190,
    "Salthill and Monkstown": 200,
    "Dun Laoghaire (Mallin)": 210,
    "Sandycove and Glasthule": 220,
    "Glenageary": 230,
    "Dalkey": 240,
    "Killiney": 250,
    "Shankill": 260,
    "Woodbrook": 270,
    "Bray (Daly)": 280,
    "Greystones": 290,
}

CONNOLLY_ORDER = LINE_ORDER["Connolly"]
PEARSE_ORDER = LINE_ORDER["Dublin Pearse"]

CITY_CENTRE = frozenset({"Connolly", "Tara Street", "Dublin Pearse"})

# Headsigns in GTFS that do not match stop_name exactly.
HEADSIGN_TO_STOP = {
    "Dublin Connolly": "Connolly",
    "Dublin Pearse": "Dublin Pearse",
    "Bray (Daly)": "Bray (Daly)",
    "Dun Laoghaire (Mallin)": "Dun Laoghaire (Mallin)",
    "Howth Junction and Donaghmede": "Howth Junction and Donaghmede",
}

# Spoken names Alexa should prefer, mapped to the GTFS stop_name.
SPOKEN_TO_GTFS = {
    "Pearse": "Dublin Pearse",
    "Dublin Pearse": "Dublin Pearse",
    "Bray": "Bray (Daly)",
    "Bray Daly": "Bray (Daly)",
    "Dun Laoghaire": "Dun Laoghaire (Mallin)",
    "Dun Laoghaire Mallin": "Dun Laoghaire (Mallin)",
    "Howth Junction": "Howth Junction and Donaghmede",
    "Salthill": "Salthill and Monkstown",
    "Sandycove": "Sandycove and Glasthule",
    "Lansdowne": "Lansdowne Road",
}

EXTRA_ALIASES = {
    "pearse station": "Dublin Pearse",
    "dublin pearse": "Dublin Pearse",
    "pearse street": "Dublin Pearse",
    "westland row": "Dublin Pearse",
    "connolly station": "Connolly",
    "dublin connolly": "Connolly",
    "tara": "Tara Street",
    "tara st": "Tara Street",
    "grand canal": "Grand Canal Dock",
    "gcd": "Grand Canal Dock",
    "lansdowne": "Lansdowne Road",
    "lansdowne rd": "Lansdowne Road",
    "aviva": "Lansdowne Road",
    "aviva stadium": "Lansdowne Road",
    "dunleary": "Dun Laoghaire (Mallin)",
    "dun laoire": "Dun Laoghaire (Mallin)",
    "dun laoghaire": "Dun Laoghaire (Mallin)",
    "mallin": "Dun Laoghaire (Mallin)",
    "howth junction": "Howth Junction and Donaghmede",
    "donaghmede": "Howth Junction and Donaghmede",
    "salthill": "Salthill and Monkstown",
    "monkstown": "Salthill and Monkstown",
    "sandycove": "Sandycove and Glasthule",
    "glasthule": "Sandycove and Glasthule",
    "bray": "Bray (Daly)",
    "bray daly": "Bray (Daly)",
    "daly": "Bray (Daly)",
    "clontarf": "Clontarf Road",
    "sydney parade": "Sydney Parade",
}

MAIN_TERMINI_SPOKEN = ("Howth", "Malahide", "Bray", "Greystones")

def normalize_name(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.casefold().replace("&", " and ").replace("'", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(dart|train|stop|station|irish rail|iarnrod eireann)\b", " ", t)
    t = re.sub(r"\b(st|saint)\b", "st", t)
    return " ".join(t.split())


def dest_stop_name(headsign: str) -> str | None:
    h = (headsign or "").strip()
    if not h:
        return None
    if h in LINE_ORDER:
        return h
    if h in HEADSIGN_TO_STOP:
        return HEADSIGN_TO_STOP[h]
    spoken = SPOKEN_TO_GTFS.get(h)
    if spoken:
        return spoken
    key = normalize_name(h)
    return alias_index_static().get(key)


def line_order(gtfs_name: str) -> int | None:
    return LINE_ORDER.get(gtfs_name)


def cardinal_for(station_name: str, headsign: str) -> str | None:
    dest = dest_stop_name(headsign)
    a, b = line_order(station_name), line_order(dest) if dest else None
    if a is None or b is None or a == b:
        return None
    return "northbound" if b < a else "southbound"


def classify_headsigns(station_name: str, headsigns: set[str]) -> list[str]:
    found: set[str] = set()
    for h in headsigns:
        card = cardinal_for(station_name, h)
        if card:
            found.add(card)
    return [c for c in ("northbound", "southbound") if c in found]


def is_city_centre(gtfs_name: str) -> bool:
    return gtfs_name in CITY_CENTRE


def is_citybound(gtfs_name: str, cardinals: list[str]) -> bool:
    if is_city_centre(gtfs_name):
        return False
    order = line_order(gtfs_name)
    if order is None:
        return False
    if order < CONNOLLY_ORDER:
        return "southbound" in cardinals
    if order > PEARSE_ORDER:
        return "northbound" in cardinals
    return False


def is_terminus_arrival(gtfs_name: str, headsigns: list[str]) -> bool:
    dests = {dest_stop_name(h) or h.strip() for h in headsigns if h.strip()}
    return bool(dests) and dests <= {gtfs_name}


def spoken_name(gtfs_name: str) -> str:
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        if gtfs == gtfs_name and spoken != gtfs_name:
            # Prefer the short spoken form (Pearse, Bray, …).
            if len(spoken) < len(gtfs_name):
                return spoken
    compact = {
        "Dublin Pearse": "Pearse",
        "Bray (Daly)": "Bray",
        "Dun Laoghaire (Mallin)": "Dun Laoghaire",
        "Howth Junction and Donaghmede": "Howth Junction",
        "Salthill and Monkstown": "Salthill and Monkstown",
        "Sandycove and Glasthule": "Sandycove and Glasthule",
    }
    return compact.get(gtfs_name, gtfs_name)


def say_headsign(headsign: str) -> str:
    dest = dest_stop_name(headsign)
    if dest:
        return spoken_name(dest)
    return (headsign or "").strip()


def platform_towards(headsigns: list[str]) -> list[str]:
    """Headsigns worth saying as 'towards X', termini first."""
    spoken_heads = [say_headsign(h) for h in headsigns if h and h.strip()]
    seen: list[str] = []
    for name in MAIN_TERMINI_SPOKEN:
        if name in spoken_heads and name not in seen:
            seen.append(name)
    for h in spoken_heads:
        if h not in seen:
            seen.append(h)
    return seen


def brief_platform(cardinals: list[str], towards: list[str]) -> str:
    termini = [t for t in towards if t in MAIN_TERMINI_SPOKEN]
    if len(termini) >= 2:
        dest = f"towards {termini[0]} or {termini[1]}"
    elif towards:
        dest = f"towards {towards[0]}"
    else:
        dest = ""
    card = cardinals[0] if cardinals else ""
    if card and dest:
        return f"{card} {dest}"
    if card:
        return card
    if dest:
        return dest
    return "that platform"


@dataclass
class Platform:
    stop_id: str
    stop_code: str
    stop_name: str
    headsigns: list[str]
    cardinals: list[str]
    citybound: bool
    towards: list[str]
    arrival_only: bool = False

    def as_dict(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "stop_code": self.stop_code,
            "stop_name": self.stop_name,
            "headsigns": self.headsigns,
            "cardinals": self.cardinals,
            "citybound": self.citybound,
            "towards": self.towards,
            "arrival_only": self.arrival_only,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Platform":
        return cls(
            stop_id=d["stop_id"], stop_code=d.get("stop_code") or "",
            stop_name=d["stop_name"], headsigns=list(d.get("headsigns") or []),
            cardinals=list(d.get("cardinals") or []),
            citybound=bool(d.get("citybound")),
            towards=list(d.get("towards") or []),
            arrival_only=bool(d.get("arrival_only")),
        )

    @property
    def label(self) -> str:
        spoken = spoken_name(self.stop_name)
        extra = brief_platform(self.cardinals, self.towards)
        if extra == "that platform":
            return spoken
        return f"{spoken}, {extra}"


@dataclass
class Station:
    name: str
    spoken: str
    city_centre: bool
    platforms: list[Platform] = field(default_factory=list)

    def usable_platforms(self) -> list[Platform]:
        usable = [p for p in self.platforms if not p.arrival_only]
        return usable or list(self.platforms)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "spoken": self.spoken,
            "city_centre": self.city_centre,
            "platforms": [p.as_dict() for p in self.platforms],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Station":
        return cls(
            name=d["name"], spoken=d.get("spoken") or spoken_name(d["name"]),
            city_centre=bool(d.get("city_centre")),
            platforms=[Platform.from_dict(p) for p in d.get("platforms") or []],
        )


def build_station(gtfs_name: str, raw_platforms: list[dict]) -> Station:
    platforms = []
    for raw in raw_platforms:
        heads = sorted({h.strip() for h in raw.get("headsigns") or [] if h and h.strip()})
        cardinals = list(raw.get("cardinals") or []) or classify_headsigns(gtfs_name, set(heads))
        towards = platform_towards(heads)
        platforms.append(Platform(
            stop_id=raw["stop_id"],
            stop_code=raw.get("stop_code") or "",
            stop_name=gtfs_name,
            headsigns=heads,
            cardinals=cardinals,
            citybound=is_citybound(gtfs_name, cardinals),
            towards=towards,
            arrival_only=is_terminus_arrival(gtfs_name, heads),
        ))
    return Station(
        name=gtfs_name,
        spoken=spoken_name(gtfs_name),
        city_centre=is_city_centre(gtfs_name),
        platforms=platforms,
    )


def split_raw_platforms(stop_id: str, stop_code: str, stop_name: str, headsigns: list[str]) -> list[dict]:
    """Turn mixed headsigns at one GTFS stop into north and/or south virtual platforms."""
    grouped: dict[str, list[str]] = {"northbound": [], "southbound": []}
    for h in headsigns:
        card = cardinal_for(stop_name, h)
        if card:
            grouped[card].append(h)
    out = []
    for card in ("northbound", "southbound"):
        heads = grouped[card]
        if heads:
            out.append({
                "stop_id": stop_id,
                "stop_code": stop_code,
                "headsigns": heads,
                "cardinals": [card],
            })
    return out


def catalog_from_dicts(rows: list[dict]) -> list[Station]:
    return [Station.from_dict(r) for r in rows]


def alias_index_static() -> dict[str, str]:
    idx: dict[str, str] = {}
    for gtfs in LINE_ORDER:
        idx.setdefault(normalize_name(gtfs), gtfs)
        idx.setdefault(normalize_name(spoken_name(gtfs)), gtfs)
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        idx[normalize_name(spoken)] = gtfs
    for k, v in EXTRA_ALIASES.items():
        idx[normalize_name(k)] = v
    return idx


def alias_index(stations: list[Station]) -> dict[str, str]:
    idx = alias_index_static()
    for st in stations:
        idx.setdefault(normalize_name(st.name), st.name)
        idx.setdefault(normalize_name(st.spoken), st.name)
    return idx


def find_station(stations: list[Station], spoken: str | None) -> Station | None:
    if not spoken:
        return None
    key = normalize_name(spoken)
    if not key:
        return None
    gtfs = alias_index(stations).get(key)
    if not gtfs:
        return None
    for st in stations:
        if st.name == gtfs:
            return st
    return None


def _headsign_key(name: str) -> str:
    return normalize_name(say_headsign(name) if name else name)


def headsign_matches(headsign: str, direction_key: str) -> bool:
    spoken = _headsign_key(headsign)
    return spoken == direction_key


def matching_headsigns(platform: Platform, direction: str | None) -> list[str]:
    """Headsigns to keep after resolving a direction (empty direction = all on the platform)."""
    if not direction or direction in ("northbound", "southbound", "eastbound", "westbound", "city"):
        return list(platform.headsigns)
    return [h for h in platform.headsigns if headsign_matches(h, direction)]


def match_platforms(station: Station, direction: str | None) -> list[Platform]:
    usable = station.usable_platforms()
    if not direction:
        return usable
    if direction in ("northbound", "southbound", "eastbound", "westbound"):
        return [p for p in usable if direction in p.cardinals]
    if direction == "city":
        if station.city_centre:
            return []
        return [p for p in usable if p.citybound]
    return [p for p in usable if any(headsign_matches(h, direction) for h in p.headsigns)
            or any(normalize_name(t) == direction for t in p.towards)]


def options_speech(station: Station) -> str:
    parts = [brief_platform(p.cardinals, p.towards) for p in station.usable_platforms()]
    if not parts:
        return f"Which direction at {station.spoken}?"
    if len(parts) == 1:
        return f"I only have {parts[0]} at {station.spoken}."
    if len(parts) == 2:
        return f"Which direction at {station.spoken}? {parts[0]}, or {parts[1]}?"
    return (f"Which direction at {station.spoken}? "
            + ", ".join(parts[:-1]) + ", or " + parts[-1] + "?")


def bad_direction_speech(station: Station, direction: str) -> str:
    if direction == "city" and station.city_centre:
        return (f"Towards the city is ambiguous at {station.spoken}. "
                + options_speech(station))
    pretty = {
        "northbound": "northbound", "southbound": "southbound",
        "eastbound": "eastbound", "westbound": "westbound",
        "city": "towards the city",
    }.get(direction, f"towards {direction}")
    return f"{station.spoken} doesn't have a {pretty} platform. {options_speech(station)}"


def alexa_station_values(stations: list[Station]) -> list[dict]:
    values = []
    seen: set[str] = set()
    for st in stations:
        name = st.spoken
        if name in seen:
            continue
        seen.add(name)
        synonyms = []
        if st.name != st.spoken:
            synonyms.append(st.name)
        for spoken, gtfs in SPOKEN_TO_GTFS.items():
            if gtfs == st.name and spoken != name:
                synonyms.append(spoken)
        for phrase, gtfs in EXTRA_ALIASES.items():
            if gtfs == st.name:
                synonyms.append(phrase)
        syns: list[str] = []
        for s in synonyms:
            if s and s.casefold() != name.casefold() and s not in syns:
                syns.append(s)
        values.append({"name": {"value": name, "synonyms": syns[:20]}})
    values.sort(key=lambda v: v["name"]["value"])
    return values


def alexa_direction_values() -> list[dict]:
    values = [
        {"name": {"value": "northbound", "synonyms": [
            "north", "north bound", "going north", "heading north", "going northbound",
            "nortbound", "norbound",
            "heading northbound", "northward", "northwards", "to the north",
        ]}},
        {"name": {"value": "southbound", "synonyms": [
            "south", "south bound", "going south", "heading south", "going southbound",
            "heading southbound", "southward", "southwards", "to the south",
        ]}},
        {"name": {"value": "the city", "synonyms": [
            "city", "city centre", "city center", "into town", "town",
            "towards the city", "toward the city", "to the city",
        ]}},
    ]
    for term in ("Howth", "Malahide", "Bray", "Greystones", "Howth Junction",
                 "Grand Canal Dock", "Dun Laoghaire", "Connolly", "Pearse",
                 "Lansdowne Road"):
        values.append({"name": {"value": term, "synonyms": [
            f"towards {term}", f"toward {term}", f"to {term}",
        ]}})
    return values
