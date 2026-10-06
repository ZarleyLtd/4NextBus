"""Read-only: compare a stop's stored DynamoDB timetable with a local GTFS extract.

Does not download a zip and does not write DynamoDB. Point --gtfs at an extracted
feed (e.g. .cache/gtfs from a previous ingest) to see what a new publish changed.

  .\\.venv\\Scripts\\python tools\\compare_stop.py 184 --gtfs .cache/gtfs
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
from src.common.store import Store, content_hash

STOP_ID_184 = "8220DB000184"


def shape(row: list) -> tuple:
    return (row[1], row[2], int(row[3]), row[4], int(row[5]))  # route, headsign, secs, service, seq


def fmt_row(row: list) -> str:
    return (f"{row[1]:6} {format_gtfs_time(int(row[3]))} {row[2]!r} svc={row[4]} "
            f"seq={row[5]} trip={row[0]}")


def classify(old_rows: list[list], new_rows: list[list]) -> dict:
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
    used_old = set()
    for r in only_new_ids:
        sh = shape(r)
        bucket = old_shapes.get(sh) or []
        found = None
        for i, old in enumerate(bucket):
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

    order_only = (Counter(tuple(r) for r in old_rows) == Counter(tuple(r) for r in new_rows)
                  and old_rows != new_rows)
    return {
        "identical_trip_id": identical,
        "same_trip_id_other_fields": same_id_field_change,
        "field_counts": field_counts,
        "trip_id_only": trip_id_only,
        "removed": unmatched_old,
        "added": unmatched_new,
        "order_only": order_only,
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stop_code", nargs="?", default="184")
    ap.add_argument("--gtfs", default=str(ROOT / ".cache" / "gtfs"),
                    help="extracted GTFS directory (not the zip); will not download")
    ap.add_argument("--examples", type=int, default=8)
    args = ap.parse_args()

    gtfs_dir = Path(args.gtfs)
    if not (gtfs_dir / "stop_times.txt").exists():
        sys.exit(f"no extract at {gtfs_dir}; copy an old feed there (do not run ensure_gtfs)")

    store = Store(os.environ.get("FOURNEXTBUS_TABLE", "FourNextBus"),
                  os.environ.get("AWS_REGION", "eu-west-1"))
    codes = store.get_stop_codes()
    entry = codes.get(str(args.stop_code).lstrip("0") or "0") or codes.get(str(args.stop_code))
    if not entry:
        sys.exit(f"stop {args.stop_code} not in STOPCODES")
    stop_id = entry["stop_id"]

    item = store._get(f"STOP#{stop_id}", "SCHED", consistent=True)
    if not item:
        sys.exit(f"no SCHED item for {stop_id}")
    stored = store.get_stop(stop_id)
    stored_rows = [d.to_row() for d in stored.departures]
    stored_ver = item.get("feed_version", {}).get("S")
    stored_hash = item.get("hash", {}).get("S")
    updated = item.get("updated_at", {}).get("N")
    when = datetime.fromtimestamp(int(updated), tz=timezone.utc).isoformat() if updated else "?"

    zip_feed = GtfsStatic(gtfs_dir)
    zip_ver = zip_feed.feed_version()
    zip_stop = zip_feed.stop_timetable(stop_id)
    if zip_stop is None:
        sys.exit(f"{stop_id} missing from {gtfs_dir}")
    zip_rows = [d.to_row() for d in zip_stop.departures]

    print(f"stop {stored.stop_code} {stored.stop_name} ({stop_id})")
    print(f"  DynamoDB: feed {stored_ver}  {len(stored_rows)} rows  hash {stored_hash}  updated {when}")
    print(f"  local zip: feed {zip_ver}  {len(zip_rows)} rows  name {zip_stop.stop_name!r}")
    print(f"  hash stored rows {content_hash([stored.stop_code, stored.stop_name, stored_rows])}")
    print(f"  hash zip rows    {content_hash([zip_stop.stop_code, zip_stop.stop_name, zip_rows])}")

    if stored_rows == zip_rows and stored.stop_name == zip_stop.stop_name:
        print("identical timetable")
        return 0

    stats = classify(zip_rows, stored_rows)  # old zip vs new DynamoDB
    print()
    print("classify (local zip = old, DynamoDB = new):")
    print(f"  identical trip_id+fields     {stats['identical_trip_id']}")
    print(f"  same trip_id, other fields   {len(stats['same_trip_id_other_fields'])}"
          f"  {dict(stats['field_counts'])}")
    print(f"  same shape, new trip_id      {stats['trip_id_only']}")
    print(f"  removed (no shape match)     {len(stats['removed'])}")
    print(f"  added (no shape match)       {len(stats['added'])}")
    print(f"  order-only (same multiset)   {stats['order_only']}")
    n = args.examples
    if stats["same_trip_id_other_fields"]:
        print("\n  examples same trip_id, other fields:")
        for old, new in stats["same_trip_id_other_fields"][:n]:
            print(f"    - {fmt_row(old)}")
            print(f"      {fmt_row(new)}")
    if stats["trip_id_only"]:
        print(f"\n  (trip_id-only count {stats['trip_id_only']}; ids not listed)")
    if stats["removed"]:
        print("\n  examples removed:")
        for r in stats["removed"][:n]:
            print(f"    - {fmt_row(r)}")
    if stats["added"]:
        print("\n  examples added:")
        for r in stats["added"][:n]:
            print(f"    - {fmt_row(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
