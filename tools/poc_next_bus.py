"""Phase 1 proof of concept: next buses at a stop, from the static timetable + NTA realtime.

Usage:  python tools/poc_next_bus.py [STOP_CODE] [--no-realtime] [--at HH:MM]

Reads NTA_API_KEY from .env. Prints timings so we can size the Lambda path.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # Behind Avast/corporate TLS inspection: trust the Windows certificate store.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv

from ingest.gtfs_static import GtfsStatic, ensure_gtfs
from src.common.gtfs_time import now_dublin
from src.common.predictions import predict, select_for_speech
from src.common.realtime import RealtimeError, fetch_trip_updates
from src.common.speech import next_buses_speech

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("poc")


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("stop_code", nargs="?", default=os.getenv("POC_STOP_CODE", "184"))
    ap.add_argument("--no-realtime", action="store_true", help="timetable only, don't call NTA")
    ap.add_argument("--at", help="pretend the time is HH:MM today (timetable only)")
    ap.add_argument("--all", action="store_true", help="print every upcoming prediction, not just the spoken set")
    args = ap.parse_args()

    now = now_dublin()
    if args.at:
        hh, mm = args.at.split(":")
        now = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        args.no_realtime = True

    t0 = time.perf_counter()
    gtfs_dir = ensure_gtfs(ROOT / ".cache")
    gtfs = GtfsStatic(gtfs_dir)
    log.info("GTFS feed version %s ready in %.1fs", gtfs.feed_version(), time.perf_counter() - t0)

    t1 = time.perf_counter()
    codes = gtfs.stop_code_map()
    entry = codes.get(args.stop_code)
    if not entry:
        print(f"Stop code {args.stop_code!r} not found ({len(codes)} bus stop codes known).")
        return 2
    stop = gtfs.stop_timetable(entry["stop_id"])
    calendar = gtfs.service_calendar(now.date() - timedelta(days=1), days=3)
    log.info("stop %s = %s (%s): %d scheduled departures across all services; static lookups %.1fs",
             stop.stop_code, stop.stop_name, stop.stop_id, len(stop.departures), time.perf_counter() - t1)
    today = now.strftime("%Y%m%d")
    log.info("services active today (%s): %d", today, len(calendar.get(today, ())))

    feed = None
    realtime_ok = False
    if not args.no_realtime:
        key = os.getenv("NTA_API_KEY", "").strip()
        if not key:
            print("NTA_API_KEY missing in .env; running timetable-only. Copy .env.example to .env and set it.")
        else:
            t2 = time.perf_counter()
            try:
                feed = fetch_trip_updates(key, timeout=15)
                realtime_ok = True
                age = int(time.time() - feed.feed_timestamp) if feed.feed_timestamp else -1
                log.info("realtime: %d trips, %.0f KB, feed age %ss, total %.2fs",
                         len(feed.trips), feed.raw_bytes / 1024, age, time.perf_counter() - t2)
                # Coverage diagnostics for this stop.
                trip_ids = {d.trip_id for d in stop.departures if d.service_id in calendar.get(today, set())}
                hit = [feed.trips[t] for t in trip_ids if t in feed.trips]
                log.info("realtime coverage: %d of today's %d trips at this stop have an update", len(hit), len(trip_ids))
                if hit:
                    sample = hit[0]
                    log.info("sample trip %s rel=%s updates=%d first=%s", sample.trip_id, sample.relationship,
                             len(sample.updates), sample.updates[0] if sample.updates else None)
                    with_time = sum(1 for tu in hit for u in tu.updates if u.arrival_time or u.departure_time)
                    with_delay = sum(1 for tu in hit for u in tu.updates if u.arrival_delay is not None or u.departure_delay is not None)
                    log.info("stop_time_updates with absolute time: %d, with delay: %d", with_time, with_delay)
            except RealtimeError as exc:
                log.error("realtime fetch failed: %s", exc)

    t3 = time.perf_counter()
    preds = predict(stop, calendar, feed, now)
    chosen = select_for_speech(preds, now)
    log.info("prediction join %.3fs; %d upcoming, %d selected", time.perf_counter() - t3, len(preds), len(chosen))

    print()
    print(f"Now: {now:%a %d %b %H:%M} (Europe/Dublin)")
    for p in (preds if args.all else chosen):
        flag = "RT " if p.realtime else "sch"
        print(f"  {flag} {p.predicted:%H:%M}  {p.route:5s} {p.headsign:28s} sched {p.scheduled:%H:%M}  delay {p.delay_seconds:+d}s")
    print()
    print("Alexa would say:")
    print("  " + next_buses_speech(stop.stop_code, stop.stop_name, chosen, now, realtime_available=realtime_ok or args.no_realtime))
    print(f"\nTotal wall time {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
