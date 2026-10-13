"""DART lookup used by the Alexa handlers."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.common.gtfs_time import now_dublin
from src.common.models import Prediction, ServiceCalendar
from src.common.predictions import predict, select_for_speech
from src.common.rt_cache import RealtimeCache
from src.common.speech import humanise, next_trains_speech
from src.common.store import DART, Store
from src.modes.dart.stations import (
    Platform, Station, bad_direction_speech, catalog_from_dicts, find_station,
    matching_headsigns, match_platforms, options_speech, say_headsign,
    split_station_and_direction, spoken_name,
)

log = logging.getLogger(__name__)

META_TTL_SECONDS = 60 * 60


@dataclass
class StopRef:
    stop_id: str
    stop_code: str
    stop_name: str
    label: str = ""
    heads: tuple[str, ...] = ()

    @property
    def spoken_name(self) -> str:
        return self.label or humanise(spoken_name(self.stop_name))


@dataclass
class NextTrainsResult:
    speech: str
    card_title: str
    card_text: str
    predictions: list[Prediction]
    realtime_status: str


@dataclass
class ResolveResult:
    status: str
    ref: StopRef | None = None
    prompt: str = ""
    elicit: str | None = None
    spoken: str | None = None


class DartService:
    def __init__(self, store: Store, realtime: RealtimeCache):
        self.store = store
        self.realtime = realtime
        self._stations: list[Station] | None = None
        self._calendar: ServiceCalendar | None = None
        self._meta_loaded = 0.0

    def _ensure_meta(self) -> None:
        if self._stations is not None and time.time() - self._meta_loaded < META_TTL_SECONDS:
            return
        t0 = time.perf_counter()
        rows = self.store.get_stations(DART)
        calendar = self.store.get_calendar()
        if not rows or not calendar:
            from src.skill.service import TimetableNotLoaded
            raise TimetableNotLoaded("STATIONS#DART/CALENDAR missing; run the ingest job")
        self._stations, self._calendar = catalog_from_dicts(rows), calendar
        self._meta_loaded = time.time()
        log.info("loaded %d DART stations and %d calendar days in %.2fs",
                 len(self._stations), len(self._calendar), time.perf_counter() - t0)

    def platform_ref(self, platform: Platform, heads: list[str] | None = None) -> StopRef:
        use_heads = tuple(heads if heads is not None else platform.headsigns)
        return StopRef(platform.stop_id, platform.stop_code, platform.stop_name,
                       platform.label, use_heads)

    def resolve(self, station_text: str | None, direction_text: str | None) -> ResolveResult:
        self._ensure_meta()
        if not station_text:
            return ResolveResult("need_station", prompt="Which DART station?", elicit="station")
        station_name, direction = split_station_and_direction(station_text, direction_text)
        station = find_station(self._stations, station_name)
        if not station:
            return ResolveResult(
                "unknown_station",
                prompt=f"I don't know a DART station called {station_text}. Try the station name, for example Pearse.",
            )
        matches = match_platforms(station, direction)
        usable = station.usable_platforms()
        if direction and not matches:
            return ResolveResult(
                "bad_direction",
                prompt=bad_direction_speech(station, direction),
                elicit="direction",
                spoken=station.spoken,
            )
        if not direction and len(usable) > 1:
            return ResolveResult(
                "need_direction",
                prompt=options_speech(station),
                elicit="direction",
                spoken=station.spoken,
            )
        chosen = matches[0] if matches else usable[0]
        heads = matching_headsigns(chosen, direction)
        return ResolveResult("ok", ref=self.platform_ref(chosen, heads))

    def ref_from_favourite(self, fav: dict) -> StopRef | None:
        self._ensure_meta()
        stop_id = fav.get("stop_id")
        heads = tuple(fav.get("heads") or [])
        for st in self._stations:
            for p in st.platforms:
                if p.stop_id != stop_id:
                    continue
                if heads and set(heads).isdisjoint(set(p.headsigns)):
                    continue
                if heads:
                    return self.platform_ref(p, list(heads))
                return self.platform_ref(p)
        if stop_id:
            return StopRef(stop_id, fav.get("stop_code") or "", fav.get("stop_name") or "",
                           fav.get("label") or fav.get("stop_name") or "", heads)
        return None

    def next_departures(self, ref: StopRef) -> NextTrainsResult:
        self._ensure_meta()
        now = now_dublin()
        t0 = time.perf_counter()
        stop = self.store.get_stop(ref.stop_id, DART)
        if stop is None:
            from src.skill.service import TimetableNotLoaded
            raise TimetableNotLoaded(f"no DART timetable item for {ref.stop_id}")
        rt = self.realtime.get(int(now.timestamp()))
        preds = predict(stop, self._calendar, rt.feed, now)
        if ref.heads:
            allowed = set(ref.heads)
            preds = [p for p in preds if p.headsign in allowed]
        chosen = select_for_speech(preds, now)
        log.info("dart %s: %d upcoming, %d chosen, realtime=%s(age %ss), %.2fs",
                 ref.stop_id, len(preds), len(chosen), rt.status, rt.age_seconds, time.perf_counter() - t0)
        label = spoken_name(ref.stop_name)
        speech = next_trains_speech(label, chosen, now, realtime_available=rt.feed is not None,
                                   empty_kind="DART trains", dest_fn=say_headsign)
        lines = []
        for p in chosen:
            mins = p.minutes_from(now)
            when = "Due" if mins <= 0 else f"{mins} min"
            dest = humanise(say_headsign(p.headsign)) if p.headsign else ""
            extra = "" if p.realtime else " (timetable)"
            lines.append(f"{dest:<26} {when}{extra}".strip())
        card_text = "\n".join(lines) if lines else "No DART trains due in the next two hours."
        if rt.feed is None:
            card_text += "\n\nLive times unavailable; showing timetable."
        return NextTrainsResult(speech, label, card_text, chosen, rt.status)

    def get_favourite(self, user_id: str) -> StopRef | None:
        fav = self.store.get_favourite(user_id, DART)
        if not fav:
            return None
        return self.ref_from_favourite(fav)

    def set_favourite(self, user_id: str, ref: StopRef) -> None:
        self.store.set_favourite(user_id, ref.stop_id, ref.stop_code, ref.stop_name,
                                 mode=DART, heads=list(ref.heads), label=ref.spoken_name)

    def clear_favourite(self, user_id: str) -> None:
        self.store.clear_favourite(user_id, DART)
