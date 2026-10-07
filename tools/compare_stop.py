"""Read-only GTFS / DynamoDB timetable compare. Never writes DynamoDB.

Slot-level (route, headsign, time, sequence) ignores TFI trip_id and service_id.

  # one stop, old extract vs DynamoDB (or vs --new)
  .\\.venv\\Scripts\\python tools\\compare_stop.py 184 --old .cache/gtfs --new .cache/feeds/<ver>

  # all stops: skip-rate if we hashed without service_id / without ids
  .\\.venv\\Scripts\\python tools\\compare_stop.py --all --old .cache/gtfs --new .cache/feeds/<ver>
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv

from ingest.gtfs_static import GtfsStatic
from src.common.gtfs_time import format_gtfs_time
from src.common.models import StopTimetable
from src.common.store import content_hash

WCU_PER_SEC = 18.0


def shape(row: list) -> tuple:
    return (row[1], row[2], int(row[3]), row[4], int(row[5]))


def slot_key(row: list) -> tuple:
    """Passenger-facing slot: not trip_id, not service_id."""
    return (row[1], row[2], int(row[3]), int(row[5]))


def fmt_slot(k: tuple) -> str:
    route, head, secs, seq = k
    return f"{route:6} {format_gtfs_time(int(secs))} {head!r} seq={seq}"


def fmt_row(row: list) -> str:
    return (f"{row[1]:6} {format_gtfs_time(int(row[3]))} {row[2]!r} svc={row[4]} "
            f"seq={row[5]} trip={row[0]}")


def to_rows(stop: StopTimetable) -> list[list]:
    return [d.to_row() for d in stop.departures]


def hash_current(code: str, name: str, rows: list[list]) -> str:
    return content_hash([code, name, rows])


def hash_no_service(code: str, name: str, rows: list[list]) -> str:
    slim = [[r[0], r[1], r[2], int(r[3]), int(r[5])] for r in rows]
    return content_hash([code, name, slim])


def hash_slots_multi(code: str, name: str, rows: list[list]) -> str:
    slots = sorted(slot_key(r) for r in rows)
    return content_hash([code, name, slots])


def hash_slots_unique(code: str, name: str, rows: list[list]) -> str:
    slots = sorted(set(slot_key(r) for r in rows))
    return content_hash([code, name, slots])


def classify_ids(old_rows: list[list], new_rows: list[list]) -> dict:
    old_ids: dict[str, list] = defaultdict(list)
    new_ids: dict[str, list] = defaultdict(list)
    for r in old_rows:
        old_ids[r[0]].append(r)
    for r in new_rows:
        new_ids[r[0]].append(r)

    identical = 0
    same_id_field_change: list[tuple[list, list]] = []
    field_counts = Counter()
    only_old_ids = []
    only_new_ids = []
    labels = ("trip_id", "route", "headsign", "seconds", "service_id", "stop_sequence")
    for tid in sorted(set(old_ids) | set(new_ids)):
        o, n = old_ids.get(tid, []), new_ids.get(tid, [])
        if o and n:
            if o[0] == n[0] and len(o) == 1 and len(n) == 1:
                identical += 1
            else:
                same_id_field_change.append((o[0], n[0]))
                for i, name in enumerate(labels):
                    if o[0][i] != n[0][i]:
                        field_counts[name] += 1
        elif o:
            only_old_ids.append(o[0])
        else:
            only_new_ids.append(n[0])

    old_shapes: dict[tuple, list] = defaultdict(list)
    for r in only_old_ids:
        old_shapes[shape(r)].append(r)
    trip_id_only = 0
    unmatched_old = []
    unmatched_new = []
    used_old: set[int] = set()
    for r in only_new_ids:
        bucket = old_shapes.get(shape(r)) or []
        found = None
        for old in bucket:
            if id(old) not in used_old:
                found = old
                used_old.add(id(old))
                break
        if found is not None:
            trip_id_only += 1
        else:
            unmatched_new.append(r)
    for r in only_old_ids:
        if id(r) not in used_old:
            unmatched_old.append(r)

    return {
        "identical_trip_id": identical,
        "same_trip_id_other_fields": same_id_field_change,
        "field_counts": field_counts,
        "trip_id_only": trip_id_only,
        "removed": unmatched_old,
        "added": unmatched_new,
        "order_only": (Counter(map(tuple, old_rows)) == Counter(map(tuple, new_rows))
                       and old_rows != new_rows),
    }


def classify_slots(old_rows: list[list], new_rows: list[list]) -> dict:
    old_c = Counter(slot_key(r) for r in old_rows)
    new_c = Counter(slot_key(r) for r in new_rows)
    old_s, new_s = set(old_c), set(new_c)
    both = old_s & new_s
    extra_copies = sum(abs(new_c[k] - old_c[k]) for k in both)
    return {
        "unique_old": len(old_s),
        "unique_new": len(new_s),
        "unique_same": len(both),
        "unique_gone": sorted(old_s - new_s),
        "unique_new_slots": sorted(new_s - old_s),
        "multiplicity_churn": extra_copies,
        "rows_old": len(old_rows),
        "rows_new": len(new_rows),
    }


def print_stop_report(label: str, stop_id: str, code: str, old_name: str, new_name: str,
                      old_rows: list[list], new_rows: list[list], examples: int) -> None:
    print(f"\n=== {label} {code} ({stop_id}) ===")
    print(f"  name {old_name!r} -> {new_name!r}")
    print(f"  rows {len(old_rows)} -> {len(new_rows)}")
    print(f"  hash A (current)     {'same' if hash_current(code, new_name, old_rows) == hash_current(code, new_name, new_rows) else 'DIFF'}")
    print(f"  hash B (no service)  {'same' if hash_no_service(code, new_name, old_rows) == hash_no_service(code, new_name, new_rows) else 'DIFF'}")
    print(f"  hash C (slots multi) {'same' if hash_slots_multi(code, new_name, old_rows) == hash_slots_multi(code, new_name, new_rows) else 'DIFF'}")
    print(f"  hash D (slots unique){'same' if hash_slots_unique(code, new_name, old_rows) == hash_slots_unique(code, new_name, new_rows) else 'DIFF'}")

    slots = classify_slots(old_rows, new_rows)
    print("\n  slot-level (route, headsign, time, seq):")
    print(f"    unique slots {slots['unique_old']} -> {slots['unique_new']}  "
          f"same {slots['unique_same']}  gone {len(slots['unique_gone'])}  new {len(slots['unique_new_slots'])}")
    print(f"    extra/missing copies of shared slots {slots['multiplicity_churn']}")
    n = examples
    if slots["unique_gone"]:
        print("    examples gone:")
        for k in slots["unique_gone"][:n]:
            print(f"      - {fmt_slot(k)}")
    if slots["unique_new_slots"]:
        print("    examples new:")
        for k in slots["unique_new_slots"][:n]:
            print(f"      + {fmt_slot(k)}")

    ids = classify_ids(old_rows, new_rows)
    print("\n  id-level (includes service_id in 'shape'):")
    print(f"    identical trip_id+fields     {ids['identical_trip_id']}")
    print(f"    same trip_id, other fields   {len(ids['same_trip_id_other_fields'])}  {dict(ids['field_counts'])}")
    print(f"    same shape, new trip_id      {ids['trip_id_only']}")
    print(f"    unmatched old/new rows       {len(ids['removed'])}/{len(ids['added'])}")


def hashes_of(stop: StopTimetable) -> dict[str, str]:
    rows = to_rows(stop)
    c, n = stop.stop_code, stop.stop_name
    return {
        "A": hash_current(c, n, rows),
        "B": hash_no_service(c, n, rows),
        "C": hash_slots_multi(c, n, rows),
        "D": hash_slots_unique(c, n, rows),
        "n": len(rows),
        "code": c,
        "name": n,
    }


def run_all(old: GtfsStatic, new: GtfsStatic) -> None:
    print("scanning old feed ...")
    old_h: dict[str, dict] = {}
    for stop in old.all_bus_stop_timetables():
        old_h[stop.stop_id] = hashes_of(stop)
    print(f"  {len(old_h)} stops")
    print("scanning new feed ...")
    new_h: dict[str, dict] = {}
    samples: list[tuple[int, str, str, str]] = []
    for stop in new.all_bus_stop_timetables():
        h = hashes_of(stop)
        new_h[stop.stop_id] = h
        samples.append((h["n"], stop.stop_id, stop.stop_code, stop.stop_name))
    print(f"  {len(new_h)} stops")

    keys = ("A", "B", "C", "D")
    labels = {
        "A": "current (trip+service+clock)",
        "B": "trip_id+clock, drop service_id",
        "C": "slots with copies, no ids",
        "D": "unique slots only (ceiling)",
    }
    both = set(old_h) & set(new_h)
    only_old = len(set(old_h) - set(new_h))
    only_new = len(set(new_h) - set(old_h))
    print(f"\nstops in both feeds {len(both)}  removed {only_old}  added {only_new}")
    print("would-write if ingest hashed as:")
    for k in keys:
        writes = sum(1 for sid in both if old_h[sid][k] != new_h[sid][k]) + only_new
        skips = len(both) - (writes - only_new)
        minutes = writes * 5.5 / WCU_PER_SEC / 60.0  # ~5.5 KB/item from last noisy run
        print(f"  {k} {labels[k]:36}  write {writes:5}  skip {skips:5}  ~{minutes:.0f} min @ 18 WCU/s")

    samples.sort()
    print("\nsize samples (new feed row counts) — use these with a one-stop compare:")
    if samples:
        quiet, mid, busy = samples[0], samples[len(samples) // 2], samples[-1]
        for tag, (n, sid, code, name) in (("quiet", quiet), ("median", mid), ("busy", busy)):
            print(f"  {tag:6} stop {code:6} {name}  {sid}  {n} rows")


def resolve_new_from_ddb(stop_id: str) -> tuple[str, str, list[list], str]:
    from src.common.store import Store
    store = Store(os.environ.get("FOURNEXTBUS_TABLE", "FourNextBus"),
                  os.environ.get("AWS_REGION", "eu-west-1"))
    item = store._get(f"STOP#{stop_id}", "SCHED", consistent=True)
    if not item:
        sys.exit(f"no SCHED item for {stop_id}")
    stored = store.get_stop(stop_id)
    updated = item.get("updated_at", {}).get("N")
    when = datetime.fromtimestamp(int(updated), tz=timezone.utc).isoformat() if updated else "?"
    ver = item.get("feed_version", {}).get("S") or "?"
    print(f"DynamoDB feed {ver} updated {when}")
    return stored.stop_code, stored.stop_name, to_rows(stored), ver


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stop_code", nargs="?", default="184")
    ap.add_argument("--old", help="extracted GTFS directory for the older feed")
    ap.add_argument("--new", help="extracted GTFS directory for the newer feed (else DynamoDB)")
    ap.add_argument("--all", action="store_true", help="hash skip-rate across every bus stop")
    ap.add_argument("--examples", type=int, default=8)
    args = ap.parse_args()

    if args.all:
        if not args.old or not args.new:
            sys.exit("--all needs --old and --new extract directories")
        run_all(GtfsStatic(Path(args.old)), GtfsStatic(Path(args.new)))
        return 0

    old_dir = Path(args.old) if args.old else ROOT / ".cache" / "gtfs"
    if not (old_dir / "stop_times.txt").exists():
        sys.exit(f"no extract at {old_dir}")

    old_gtfs = GtfsStatic(old_dir)
    old_ver = old_gtfs.feed_version()

    if args.new:
        new_gtfs = GtfsStatic(Path(args.new))
        new_ver = new_gtfs.feed_version()
        codes = None
        # Resolve stop_code via new feed stop_code_map
        cmap = new_gtfs.stop_code_map()
        entry = cmap.get(str(args.stop_code).lstrip("0") or "0") or cmap.get(str(args.stop_code))
        if not entry:
            sys.exit(f"stop {args.stop_code} not in new feed")
        stop_id = entry["stop_id"]
        o, n = old_gtfs.stop_timetable(stop_id), new_gtfs.stop_timetable(stop_id)
        if o is None or n is None:
            sys.exit(f"{stop_id} missing from one of the feeds")
        print(f"feeds {old_ver} -> {new_ver}")
        print_stop_report(n.stop_name, stop_id, n.stop_code, o.stop_name, n.stop_name,
                          to_rows(o), to_rows(n), args.examples)
        return 0

    cmap = old_gtfs.stop_code_map()
    entry = cmap.get(str(args.stop_code).lstrip("0") or "0") or cmap.get(str(args.stop_code))
    if not entry:
        sys.exit(f"stop {args.stop_code} not in old feed / STOPCODES")
    stop_id = entry["stop_id"]
    old_stop = old_gtfs.stop_timetable(stop_id)
    if old_stop is None:
        sys.exit(f"{stop_id} missing from {old_dir}")
    print(f"local zip feed {old_ver}")
    code, name, new_rows, _ver = resolve_new_from_ddb(stop_id)
    print_stop_report(name, stop_id, code, old_stop.stop_name, name,
                      to_rows(old_stop), new_rows, args.examples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
