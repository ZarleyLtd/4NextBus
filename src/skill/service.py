"""Application service used by the Alexa handlers. Holds per-container caches."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.common.gtfs_time import now_dublin
from src.common.models import Prediction, ServiceCalendar
from src.common.predictions import predict, select_for_speech
from src.common.rt_cache import RealtimeCache
from src.common.speech import humanise, next_buses_speech, say_route
from src.common.store import Store

log = logging.getLogger(__name__)

META_TTL_SECONDS = 60 * 60   # stop-code map and calendar are refreshed hourly per container


@dataclass
class StopRef:
    stop_id: str
    stop_code: str
    stop_name: str

    @property
    def spoken_name(self) -> str:
        return humanise(self.stop_name)


@dataclass
class NextBusesResult:
    speech: str
    card_title: str
    card_text: str
    predictions: list[Prediction]
    realtime_status: str


class TimetableNotLoaded(RuntimeError):
    """The ingest job has not populated the table yet."""


class BusService:
    def __init__(self, store: Store, realtime: RealtimeCache):
        self.store = store
        self.realtime = realtime
        self._codes: dict[str, dict] | None = None
        self._calendar: ServiceCalendar | None = None
        self._meta_loaded = 0.0

    # ---- metadata caches ----------------------------------------------------------

    def _ensure_meta(self) -> None:
        if self._codes is not None and time.time() - self._meta_loaded < META_TTL_SECONDS:
            return
        t0 = time.perf_counter()
        codes = self.store.get_stop_codes()
        calendar = self.store.get_calendar()
        if not codes or not calendar:
            raise TimetableNotLoaded("STOPCODES/CALENDAR missing; run the ingest job")
        self._codes, self._calendar = codes, calendar
        self._meta_loaded = time.time()
        log.info("loaded %d stop codes and %d calendar days in %.2fs", len(codes), len(calendar), time.perf_counter() - t0)

    def resolve_stop(self, stop_code: str | None) -> StopRef | None:
        if not stop_code:
            return None
        self._ensure_meta()
        code = str(stop_code).strip().lstrip("0") or "0"
        entry = self._codes.get(code)
        if not entry:
            return None
        return StopRef(entry["stop_id"], code, entry["stop_name"])

    # ---- main query -----------------------------------------------------------------

    def next_buses(self, ref: StopRef) -> NextBusesResult:
        self._ensure_meta()
        now = now_dublin()
        t0 = time.perf_counter()
        stop = self.store.get_stop(ref.stop_id)
        if stop is None:
            raise TimetableNotLoaded(f"no timetable item for {ref.stop_id}")
        rt = self.realtime.get(int(now.timestamp()))
        preds = predict(stop, self._calendar, rt.feed, now)
        chosen = select_for_speech(preds, now)
        log.info("stop %s: %d upcoming, %d chosen, realtime=%s(age %ss), %.2fs",
                 ref.stop_code, len(preds), len(chosen), rt.status, rt.age_seconds, time.perf_counter() - t0)
        speech = next_buses_speech(stop.stop_code, stop.stop_name, chosen, now,
                                   realtime_available=rt.feed is not None)
        lines = []
        for p in chosen:
            mins = p.minutes_from(now)
            when = "Due" if mins <= 0 else f"{mins} min"
            lines.append(f"{p.route:<5} {humanise(p.headsign):<26} {when}{'' if p.realtime else ' (timetable)'}")
        card_text = "\n".join(lines) if lines else "No buses due in the next two hours."
        if rt.feed is None:
            card_text += "\n\nLive times unavailable; showing timetable."
        return NextBusesResult(speech, f"Stop {stop.stop_code} - {humanise(stop.stop_name)}", card_text, chosen, rt.status)

    # ---- favourites -------------------------------------------------------------------

    def get_favourite(self, user_id: str) -> StopRef | None:
        fav = self.store.get_favourite(user_id)
        return StopRef(fav["stop_id"], fav["stop_code"], fav["stop_name"]) if fav else None

    def set_favourite(self, user_id: str, ref: StopRef) -> None:
        self.store.set_favourite(user_id, ref.stop_id, ref.stop_code, ref.stop_name)
