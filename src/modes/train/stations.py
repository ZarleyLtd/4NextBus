"""Commuter station names, direction aliases, and corridor matching.

Irish Rail GTFS gives one stop_id per station (not one per platform). Trips in
both directions share that id; we split them into virtual platforms by corridor
(northern, western, south-western, south-eastern, Cork, Waterford–Limerick Junction)
and whether the headsign is towards a city hub or an outer terminus.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.modes.direction import parse_direction, peel_direction_suffix, split_station_and_direction

# Ordered city -> outer on each Commuter corridor. Names are GTFS-ish; aliases
# and dest_stop_name map spoken/headsign variants onto these.
CORRIDORS: dict[str, dict] = {
    "northern": {
        "cardinal_out": "northbound",
        "cardinal_in": "southbound",
        "city": "dublin",
        "stops": [
            "Dublin Pearse", "Tara Street", "Connolly",
            "Howth Junction and Donaghmede", "Clongriffin", "Portmarnock",
            "Malahide", "Donabate", "Rush and Lusk", "Skerries", "Balbriggan",
            "Gormanston", "Laytown", "Drogheda (MacBride)", "Dundalk (Clarke)",
        ],
    },
    "western": {
        "cardinal_out": "westbound",
        "cardinal_in": "eastbound",
        "city": "dublin",
        "stops": [
            "Dublin Pearse", "Tara Street", "Connolly", "Docklands", "Drumcondra",
            "Broombridge", "Pelletstown", "Ashtown", "Navan Road Parkway",
            "Castleknock", "Coolmine", "Clonsilla", "Leixlip Confey",
            "Leixlip Louisa Bridge", "Maynooth", "Kilcock", "Enfield",
            "Mullingar", "Edgeworthstown", "Longford",
        ],
    },
    "m3": {
        "cardinal_out": "northbound",
        "cardinal_in": "southbound",
        "city": "dublin",
        "stops": [
            "Docklands", "Connolly", "Drumcondra", "Broombridge", "Pelletstown",
            "Ashtown", "Navan Road Parkway", "Castleknock", "Coolmine",
            "Clonsilla", "Hansfield", "Dunboyne", "M3 Parkway",
        ],
    },
    "southwestern": {
        "cardinal_out": "westbound",
        "cardinal_in": "eastbound",
        "city": "dublin",
        "stops": [
            "Grand Canal Dock", "Dublin Pearse", "Tara Street", "Connolly",
            "Drumcondra", "Dublin Heuston", "Park West and Cherry Orchard",
            "Clondalkin Fonthill", "Kishoge", "Adamstown",
            "Hazelhatch and Celbridge", "Sallins and Naas", "Newbridge",
            "Kildare", "Monasterevin", "Portarlington", "Portlaoise",
        ],
    },
    "southeastern": {
        "cardinal_out": "southbound",
        "cardinal_in": "northbound",
        "city": "dublin",
        "stops": [
            "Connolly", "Tara Street", "Dublin Pearse", "Lansdowne Road",
            "Sydney Parade", "Blackrock", "Dun Laoghaire (Mallin)",
            "Bray (Daly)", "Greystones", "Kilcoole", "Wicklow", "Rathdrum",
            "Arklow", "Gorey",
        ],
    },
    "cork_cobh": {
        "cardinal_out": "eastbound",
        "cardinal_in": "westbound",
        "city": "cork",
        "stops": [
            "Cork (Kent)", "Little Island", "Glounthaune", "Fota",
            "Carrigaloe", "Rushbrooke", "Cobh",
        ],
    },
    "cork_midleton": {
        "cardinal_out": "eastbound",
        "cardinal_in": "westbound",
        "city": "cork",
        "stops": [
            "Cork (Kent)", "Little Island", "Glounthaune", "Carrigtwohill", "Midleton",
        ],
    },
    "cork_mallow": {
        "cardinal_out": "northbound",
        "cardinal_in": "southbound",
        "city": "cork",
        "stops": ["Cork (Kent)", "Mallow"],
    },
    "waterford_lj": {
        "cardinal_out": "westbound",
        "cardinal_in": "eastbound",
        "city": "waterford",
        "stops": [
            "Waterford", "Carrick-on-Suir", "Clonmel", "Cahir", "Tipperary",
            "Limerick Junction",
        ],
    },
}

DUBLIN_CITY = frozenset({
    "Connolly", "Tara Street", "Dublin Pearse", "Grand Canal Dock",
    "Dublin Heuston", "Docklands",
})
CORK_CITY = frozenset({"Cork (Kent)"})
WATERFORD_CITY = frozenset({"Waterford"})
CITY_CENTRE = DUBLIN_CITY | CORK_CITY | WATERFORD_CITY

HEADSIGN_TO_STOP = {
    "Dublin Connolly": "Connolly",
    "Connolly": "Connolly",
    "Dublin Pearse": "Dublin Pearse",
    "Pearse": "Dublin Pearse",
    "Dublin Heuston": "Dublin Heuston",
    "Heuston": "Dublin Heuston",
    "Tara St": "Tara Street",
    "Bray (Daly)": "Bray (Daly)",
    "Dun Laoghaire (Mallin)": "Dun Laoghaire (Mallin)",
    "Howth Junction and Donaghmede": "Howth Junction and Donaghmede",
    "Drogheda": "Drogheda (MacBride)",
    "Drogheda MacBride": "Drogheda (MacBride)",
    "Dundalk": "Dundalk (Clarke)",
    "Dundalk Clarke": "Dundalk (Clarke)",
    "Cork": "Cork (Kent)",
    "Cork Kent": "Cork (Kent)",
    "Kent": "Cork (Kent)",
    "Hazelhatch": "Hazelhatch and Celbridge",
    "Hazelhatch and Celbridge": "Hazelhatch and Celbridge",
    "Sallins": "Sallins and Naas",
    "Sallins and Naas": "Sallins and Naas",
    "Park West": "Park West and Cherry Orchard",
    "Clondalkin": "Clondalkin Fonthill",
    "Rush & Lusk": "Rush and Lusk",
    "Leixlip Confey": "Leixlip Confey",
    "Leixlip Louisa Bridge": "Leixlip Louisa Bridge",
    "M3 Parkway": "M3 Parkway",
    "Grand Canal Dock": "Grand Canal Dock",
    "Limerick Jct": "Limerick Junction",
    "Limerick Junction": "Limerick Junction",
}

SPOKEN_TO_GTFS = {
    "Pearse": "Dublin Pearse",
    "Dublin Pearse": "Dublin Pearse",
    "Connolly": "Connolly",
    "Heuston": "Dublin Heuston",
    "Dublin Heuston": "Dublin Heuston",
    "Bray": "Bray (Daly)",
    "Bray Daly": "Bray (Daly)",
    "Dun Laoghaire": "Dun Laoghaire (Mallin)",
    "Dun Laoghaire Mallin": "Dun Laoghaire (Mallin)",
    "Howth Junction": "Howth Junction and Donaghmede",
    "Lansdowne": "Lansdowne Road",
    "Drogheda": "Drogheda (MacBride)",
    "Dundalk": "Dundalk (Clarke)",
    "Kent": "Cork (Kent)",
    "Cork": "Cork (Kent)",
    "Cork Kent": "Cork (Kent)",
    "Hazelhatch": "Hazelhatch and Celbridge",
    "Sallins": "Sallins and Naas",
    "Park West": "Park West and Cherry Orchard",
    "Clondalkin": "Clondalkin Fonthill",
}

EXTRA_ALIASES = {
    "pearse station": "Dublin Pearse",
    "dublin pearse": "Dublin Pearse",
    "pearse street": "Dublin Pearse",
    "westland row": "Dublin Pearse",
    "connolly station": "Connolly",
    "dublin connolly": "Connolly",
    "heuston station": "Dublin Heuston",
    "dublin heuston": "Dublin Heuston",
    "kingsbridge": "Dublin Heuston",
    "tara": "Tara Street",
    "tara st": "Tara Street",
    "grand canal": "Grand Canal Dock",
    "gcd": "Grand Canal Dock",
    "docklands": "Docklands",
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
    "bray": "Bray (Daly)",
    "bray daly": "Bray (Daly)",
    "daly": "Bray (Daly)",
    "drogheda": "Drogheda (MacBride)",
    "macbride": "Drogheda (MacBride)",
    "dundalk": "Dundalk (Clarke)",
    "clarke": "Dundalk (Clarke)",
    "kent": "Cork (Kent)",
    "kent station": "Cork (Kent)",
    "cork kent": "Cork (Kent)",
    "cork station": "Cork (Kent)",
    "hazelhatch": "Hazelhatch and Celbridge",
    "celbridge": "Hazelhatch and Celbridge",
    "sallins": "Sallins and Naas",
    "naas": "Sallins and Naas",
    "park west": "Park West and Cherry Orchard",
    "cherry orchard": "Park West and Cherry Orchard",
    "clondalkin": "Clondalkin Fonthill",
    "fonthill": "Clondalkin Fonthill",
    "m3": "M3 Parkway",
    "m3 parkway": "M3 Parkway",
    "louisa bridge": "Leixlip Louisa Bridge",
    "confey": "Leixlip Confey",
    "rush and lusk": "Rush and Lusk",
    "lusk": "Rush and Lusk",
    "limerick junction": "Limerick Junction",
    "limerick jct": "Limerick Junction",
    "carrick on suir": "Carrick-on-Suir",
    "fota": "Fota",
    "fota wildlife park": "Fota",
}

MAIN_TERMINI_SPOKEN = (
    "Dundalk", "Drogheda", "Maynooth", "Longford", "M3 Parkway",
    "Portlaoise", "Hazelhatch", "Gorey", "Cobh", "Midleton", "Mallow",
    "Limerick Junction", "Waterford", "Heuston", "Connolly", "Pearse",
    "Kent", "Bray", "Greystones",
)

_CORRIDOR_INDEX: dict[str, list[tuple[str, int, str, str, str]]] | None = None


def normalize_name(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.casefold().replace("&", " and ").replace("'", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(dart|commuter|train|trains|stop|station|irish rail|iarnrod eireann|local)\b", " ", t)
    t = re.sub(r"\b(st|saint)\b", "st", t)
    return " ".join(t.split())


def all_corridor_stops() -> list[str]:
    seen: list[str] = []
    for spec in CORRIDORS.values():
        for name in spec["stops"]:
            if name not in seen:
                seen.append(name)
    return seen


def _corridor_index() -> dict[str, list[tuple[str, int, str, str, str]]]:
    global _CORRIDOR_INDEX
    if _CORRIDOR_INDEX is not None:
        return _CORRIDOR_INDEX
    idx: dict[str, list[tuple[str, int, str, str, str]]] = {}
    for cid, spec in CORRIDORS.items():
        for i, name in enumerate(spec["stops"]):
            rec = (cid, i, spec["cardinal_out"], spec["cardinal_in"], spec["city"])
            for key in (normalize_name(name), normalize_name(spoken_name(name))):
                if key:
                    idx.setdefault(key, [])
                    if rec not in idx[key]:
                        idx[key].append(rec)
    _CORRIDOR_INDEX = idx
    return idx


def dest_stop_name(headsign: str) -> str | None:
    h = (headsign or "").strip()
    if not h:
        return None
    if h in HEADSIGN_TO_STOP:
        return HEADSIGN_TO_STOP[h]
    spoken = SPOKEN_TO_GTFS.get(h)
    if spoken:
        return spoken
    key = normalize_name(h)
    return alias_index_static().get(key)


def _positions(gtfs_name: str) -> list[tuple[str, int, str, str, str]]:
    names = [gtfs_name]
    mapped = dest_stop_name(gtfs_name)
    if mapped:
        names.append(mapped)
    found: list[tuple[str, int, str, str, str]] = []
    idx = _corridor_index()
    for name in names:
        for rec in idx.get(normalize_name(name), []):
            if rec not in found:
                found.append(rec)
    return found


def cardinal_for(station_name: str, headsign: str) -> str | None:
    dest = dest_stop_name(headsign)
    here = _positions(station_name)
    there = _positions(dest) if dest else []
    cards: set[str] = set()
    here_by = {c[0]: c for c in here}
    for cid, order, card_out, card_in, _city in there:
        if cid not in here_by:
            continue
        a = here_by[cid][1]
        if order == a:
            continue
        cards.add(card_out if order > a else card_in)
    if len(cards) == 1:
        return next(iter(cards))
    return None


def corridor_for(station_name: str, headsign: str) -> str | None:
    dest = dest_stop_name(headsign)
    here = {c[0] for c in _positions(station_name)}
    there = {c[0] for c in _positions(dest)} if dest else set()
    shared = here & there
    if len(shared) == 1:
        return next(iter(shared))
    if not shared:
        return None
    best, best_span = None, -1
    here_by = {c[0]: c[1] for c in _positions(station_name)}
    there_by = {c[0]: c[1] for c in _positions(dest)} if dest else {}
    for cid in shared:
        span = abs(here_by[cid] - there_by[cid])
        if span > best_span:
            best, best_span = cid, span
    return best


def classify_headsigns(station_name: str, headsigns: set[str]) -> list[str]:
    found: set[str] = set()
    for h in headsigns:
        card = cardinal_for(station_name, h)
        if card:
            found.add(card)
    return [c for c in ("northbound", "southbound", "eastbound", "westbound") if c in found]


def is_city_centre(gtfs_name: str) -> bool:
    mapped = dest_stop_name(gtfs_name) or gtfs_name
    return gtfs_name in CITY_CENTRE or mapped in CITY_CENTRE


def _city_for_station(gtfs_name: str) -> str | None:
    cities = {c[4] for c in _positions(gtfs_name)}
    if len(cities) == 1:
        return next(iter(cities))
    if "dublin" in cities:
        return "dublin"
    return next(iter(cities), None)


def is_citybound(gtfs_name: str, headsigns: list[str] | None = None, cardinals: list[str] | None = None) -> bool:
    if is_city_centre(gtfs_name):
        return False
    dests = [dest_stop_name(h) or h for h in (headsigns or []) if h]
    if dests:
        city = _city_for_station(gtfs_name)
        hubs = {"dublin": DUBLIN_CITY, "cork": CORK_CITY, "waterford": WATERFORD_CITY}.get(city or "", frozenset())
        return any((d in hubs) or (dest_stop_name(d) in hubs) for d in dests)
    return False


def is_terminus_arrival(gtfs_name: str, headsigns: list[str]) -> bool:
    dests = {dest_stop_name(h) or h.strip() for h in headsigns if h.strip()}
    mapped = dest_stop_name(gtfs_name) or gtfs_name
    return bool(dests) and dests <= {gtfs_name, mapped}


def spoken_name(gtfs_name: str) -> str:
    compact = {
        "Dublin Pearse": "Pearse",
        "Dublin Heuston": "Heuston",
        "Bray (Daly)": "Bray",
        "Dun Laoghaire (Mallin)": "Dun Laoghaire",
        "Howth Junction and Donaghmede": "Howth Junction",
        "Drogheda (MacBride)": "Drogheda",
        "Dundalk (Clarke)": "Dundalk",
        "Cork (Kent)": "Kent",
        "Hazelhatch and Celbridge": "Hazelhatch",
        "Sallins and Naas": "Sallins",
        "Park West and Cherry Orchard": "Park West",
        "Clondalkin Fonthill": "Clondalkin",
        "Rush and Lusk": "Rush and Lusk",
    }
    if gtfs_name in compact:
        return compact[gtfs_name]
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        if gtfs == gtfs_name and spoken != gtfs_name and len(spoken) < len(gtfs_name):
            return spoken
    return gtfs_name


def say_headsign(headsign: str) -> str:
    dest = dest_stop_name(headsign)
    if dest:
        return spoken_name(dest)
    return (headsign or "").strip()


def platform_towards(headsigns: list[str]) -> list[str]:
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
    corridor: str = ""

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
            "corridor": self.corridor,
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
            corridor=d.get("corridor") or "",
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
            citybound=bool(raw.get("citybound")) if "citybound" in raw else is_citybound(gtfs_name, heads, cardinals),
            towards=towards,
            arrival_only=is_terminus_arrival(gtfs_name, heads),
            corridor=raw.get("corridor") or "",
        ))
    return Station(
        name=gtfs_name,
        spoken=spoken_name(gtfs_name),
        city_centre=is_city_centre(gtfs_name),
        platforms=platforms,
    )


def split_raw_platforms(stop_id: str, stop_code: str, stop_name: str, headsigns: list[str]) -> list[dict]:
    """Turn mixed headsigns at one GTFS stop into virtual platforms by corridor / city."""
    grouped: dict[str, dict] = {}
    for h in headsigns:
        if not h or not h.strip():
            continue
        dest = dest_stop_name(h) or h.strip()
        if is_citybound(stop_name, [h]):
            key = "city"
            card = cardinal_for(stop_name, h)
            corridor = corridor_for(stop_name, h) or ""
        else:
            corridor = corridor_for(stop_name, h) or normalize_name(say_headsign(h) or dest) or "other"
            key = f"out:{corridor}"
            card = cardinal_for(stop_name, h)
        bucket = grouped.setdefault(key, {
            "stop_id": stop_id,
            "stop_code": stop_code,
            "headsigns": [],
            "cardinals": [],
            "citybound": key == "city",
            "corridor": corridor if key != "city" else (corridor or "city"),
        })
        bucket["headsigns"].append(h)
        if card and card not in bucket["cardinals"]:
            bucket["cardinals"].append(card)
    order = ["city"] + [f"out:{cid}" for cid in CORRIDORS]
    keys = [k for k in order if k in grouped] + [k for k in grouped if k not in order]
    return [grouped[k] for k in keys]


def catalog_from_dicts(rows: list[dict]) -> list[Station]:
    return [Station.from_dict(r) for r in rows]


def alias_index_static() -> dict[str, str]:
    idx: dict[str, str] = {}
    for gtfs in all_corridor_stops():
        idx.setdefault(normalize_name(gtfs), gtfs)
        idx.setdefault(normalize_name(spoken_name(gtfs)), gtfs)
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        idx[normalize_name(spoken)] = gtfs
    for k, v in EXTRA_ALIASES.items():
        idx[normalize_name(k)] = v
    for h, gtfs in HEADSIGN_TO_STOP.items():
        idx.setdefault(normalize_name(h), gtfs)
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
    idx = alias_index(stations)
    gtfs = idx.get(key)
    if not gtfs:
        return None
    for st in stations:
        if st.name == gtfs or st.spoken == gtfs:
            return st
        if dest_stop_name(st.name) == gtfs or spoken_name(st.name) == spoken_name(gtfs):
            return st
    return None


def _headsign_key(name: str) -> str:
    return normalize_name(say_headsign(name) if name else name)


def headsign_matches(headsign: str, direction_key: str) -> bool:
    spoken = _headsign_key(headsign)
    return spoken == direction_key or spoken.startswith(direction_key) or direction_key.startswith(spoken)


def matching_headsigns(platform: Platform, direction: str | None) -> list[str]:
    """Headsigns to keep after resolving a direction (empty direction = all on the platform)."""
    if not direction or direction in ("northbound", "southbound", "eastbound", "westbound", "city"):
        return list(platform.headsigns)
    return [h for h in platform.headsigns if headsign_matches(h, direction)]


def collect_headsigns(platforms: list[Platform], direction: str | None) -> list[str]:
    """Union of headsigns across platforms that share a direction (e.g. Cobh and Midleton)."""
    seen: set[str] = set()
    out: list[str] = []
    for platform in platforms:
        for head in matching_headsigns(platform, direction):
            if head not in seen:
                seen.add(head)
                out.append(head)
    return out


def merged_platform_label(station: Station, direction: str | None, platforms: list[Platform]) -> str:
    if len(platforms) == 1:
        return platforms[0].label
    pretty = {
        "northbound": "northbound", "southbound": "southbound",
        "eastbound": "eastbound", "westbound": "westbound",
        "city": "towards the city",
    }.get(direction or "")
    if pretty:
        return f"{station.spoken}, {pretty}"
    return station.spoken


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


def alexa_direction_values(stations: list[Station] | None = None) -> list[dict]:
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
        {"name": {"value": "eastbound", "synonyms": [
            "east", "east bound", "going east", "heading east", "going eastbound",
            "heading eastbound", "eastward", "eastwards", "to the east",
        ]}},
        {"name": {"value": "westbound", "synonyms": [
            "west", "west bound", "going west", "heading west", "going westbound",
            "heading westbound", "westward", "westwards", "to the west",
        ]}},
        {"name": {"value": "the city", "synonyms": [
            "city", "city centre", "city center", "into town", "town",
            "towards the city", "toward the city", "to the city",
        ]}},
    ]
    terms: list[str] = list(MAIN_TERMINI_SPOKEN)
    if stations:
        for st in stations:
            terms.append(st.spoken)
            for p in st.platforms:
                terms.extend(p.towards)
    seen: set[str] = set()
    for term in terms:
        if not term or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        values.append({"name": {"value": term, "synonyms": [
            f"towards {term}", f"toward {term}", f"to {term}",
        ]}})
    return values
