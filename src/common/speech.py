"""Turn predictions into something pleasant for Alexa to say."""
from __future__ import annotations

import re
from datetime import datetime

from .models import Prediction

# Common abbreviations in NTA stop names / headsigns.
_ABBREV = {
    r"\bRd\b": "Road", r"\bSt\b": "Street", r"\bAve\b": "Avenue", r"\bSq\b": "Square",
    r"\bPk\b": "Park", r"\bStn\b": "Station", r"\bTce\b": "Terrace", r"\bCres\b": "Crescent",
    r"\bDr\b": "Drive", r"\bGdns\b": "Gardens", r"\bLwr\b": "Lower", r"\bUpr\b": "Upper",
    r"\bNth\b": "North", r"\bSth\b": "South", r"\bBr\b": "Bridge", r"\bCtr\b": "Centre",
    r"\bHosp\b": "Hospital", r"\bUni\b": "University", r"\bBus\b(?=\s*$)": "Bus Station",
}


def humanise(text: str) -> str:
    out = text.replace("�", "")
    for pat, rep in _ABBREV.items():
        out = re.sub(pat, rep, out)
    out = re.sub(r"\s*,\s*stop\s+\d+\s*$", "", out, flags=re.I)   # "Parnell Square West, stop 2"
    return out.strip()


def say_route(route: str) -> str:
    """'46A' -> '46 A' so Alexa says 'forty six A' rather than 'forty six-a'."""
    m = re.fullmatch(r"(\d+)([A-Za-z]+)", route)
    if m:
        return f"{m.group(1)} {m.group(2).upper()}"
    return route


def say_minutes(p: Prediction, now: datetime) -> str:
    mins = p.minutes_from(now)
    if mins <= 0:
        return "due now"
    if mins == 1:
        return "in 1 minute"
    return f"in {mins} minutes"


def describe(p: Prediction, now: datetime, with_headsign: bool = True) -> str:
    base = f"the {say_route(p.route)}"
    if with_headsign and p.headsign:
        base += f" towards {humanise(p.headsign)}"
    when = say_minutes(p, now)
    if not p.realtime:
        when = f"scheduled {when}" if when != "due now" else "scheduled now"
    return f"{base} {when}"


def join_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + ", and " + items[-1]


def next_buses_speech(stop_code: str, stop_name: str, preds: list[Prediction], now: datetime,
                      realtime_available: bool = True) -> str:
    name = humanise(stop_name)
    if not preds:
        return f"I can't find any buses due at stop {stop_code}, {name}, in the next two hours."
    # Only repeat the headsign when the same route appears with different destinations.
    routes_multi_dest = {r for r in {p.route for p in preds}
                         if len({p.headsign for p in preds if p.route == r}) > 1}
    parts = []
    seen_routes: set[str] = set()
    for p in preds:
        with_head = p.route in routes_multi_dest or p.route not in seen_routes
        parts.append(describe(p, now, with_headsign=with_head))
        seen_routes.add(p.route)
    text = f"At stop {stop_code}, {name}: {join_list(parts)}."
    if not realtime_available:
        text += " Live times are unavailable right now, so these are timetable times."
    return text
