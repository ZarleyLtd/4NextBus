"""Local PoC: next DART trains at a named station.

Usage:  python tools/poc_next_dart.py Pearse southbound
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv

from ingest.gtfs_static import GtfsStatic, ensure_gtfs
from src.common.gtfs_time import now_dublin
from src.common.predictions import predict, select_for_speech
from src.common.realtime import RealtimeError, fetch_trip_updates
from src.common.speech import next_trains_speech
from src.modes.dart.stations import (
    catalog_from_dicts, find_station, matching_headsigns, match_platforms,
    say_headsign, split_station_and_direction, spoken_name,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("station")
    ap.add_argument("direction", nargs="?")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    args = ap.parse_args()
    gtfs = GtfsStatic(ensure_gtfs(Path(args.cache)))
    catalog = catalog_from_dicts(gtfs.dart_station_catalog())
    name, direction = split_station_and_direction(args.station, args.direction)
    station = find_station(catalog, name)
    if not station:
        print(f"unknown DART station: {args.station}")
        return 1
    matches = match_platforms(station, direction)
    usable = station.usable_platforms()
    if direction and not matches:
        print(f"bad direction for {station.spoken}: {direction}")
        return 1
    if not direction and len(usable) > 1:
        print(f"need direction for {station.spoken}")
        return 1
    chosen = matches[0] if matches else usable[0]
    heads = set(matching_headsigns(chosen, direction) or [])
    stop = None
    for item in gtfs.all_dart_stop_timetables():
        if item.stop_id == chosen.stop_id:
            stop = item
            break
    now = now_dublin()
    cal = gtfs.service_calendar(now.date() - timedelta(days=1), days=5)
    try:
        rt = fetch_trip_updates(os.environ["NTA_API_KEY"])
    except (RealtimeError, KeyError):
        rt = None
    preds = predict(stop, cal, rt, now) if stop else []
    if heads:
        preds = [p for p in preds if p.headsign in heads]
    print(next_trains_speech(spoken_name(chosen.stop_name), select_for_speech(preds, now), now,
                             dest_fn=say_headsign))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
