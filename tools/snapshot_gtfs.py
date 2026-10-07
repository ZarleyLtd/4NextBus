"""Save a TFI GTFS zip under its feed_version so a later publish does not overwrite it.

Does not write DynamoDB. Does not replace .cache/GTFS_Realtime.zip (that may be an older feed).

  .\\.venv\\Scripts\\python tools\\snapshot_gtfs.py
  .\\.venv\\Scripts\\python tools\\snapshot_gtfs.py --archive-cache
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

from ingest.gtfs_static import GTFS_URL, NEEDED

FEEDS = ROOT / ".cache" / "feeds"


def version_from_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        with z.open("feed_info.txt") as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            row = next(csv.DictReader(text))
            return (row.get("feed_version") or "unknown").strip()


def extract_zip(zip_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for n in NEEDED:
            if n in names:
                z.extract(n, out_dir)


def download_zip(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    t0 = time.perf_counter()
    with requests.get(GTFS_URL, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    os.replace(tmp, dest)
    print(f"downloaded {dest.stat().st_size / 1e6:.0f} MB in {time.perf_counter() - t0:.1f}s -> {dest}")


def snapshot_path(version: str, kind: str) -> Path:
    safe = version.replace("/", "_")
    if kind == "zip":
        return FEEDS / f"{safe}.zip"
    return FEEDS / safe


def archive_cache_zip() -> None:
    src = ROOT / ".cache" / "GTFS_Realtime.zip"
    if not src.exists():
        print("no .cache/GTFS_Realtime.zip to archive")
        return
    ver = version_from_zip(src)
    dest = snapshot_path(ver, "zip")
    if dest.exists():
        print(f"already have {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    extract = snapshot_path(ver, "dir")
    cache_extract = ROOT / ".cache" / "gtfs"
    if (cache_extract / "stop_times.txt").exists():
        print(f"archived zip {dest}; reuse extract {cache_extract} as --old")
    else:
        extract_zip(dest, extract)
        print(f"archived zip {dest} and extracted to {extract}")


def snapshot_current() -> Path:
    FEEDS.mkdir(parents=True, exist_ok=True)
    tmp = FEEDS / "_download.zip"
    download_zip(tmp)
    ver = version_from_zip(tmp)
    dest = snapshot_path(ver, "zip")
    if dest.exists() and dest.stat().st_size == tmp.stat().st_size:
        tmp.unlink()
        print(f"already have current feed {ver} at {dest}")
    else:
        if dest.exists():
            dest.unlink()
        os.replace(tmp, dest)
        print(f"saved {ver} -> {dest}")
    out_dir = snapshot_path(ver, "dir")
    if not (out_dir / "stop_times.txt").exists():
        print(f"extracting to {out_dir} ...")
        extract_zip(dest, out_dir)
    print(f"extract {out_dir}")
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-cache", action="store_true",
                    help="copy .cache/GTFS_Realtime.zip into .cache/feeds/<version>.zip")
    ap.add_argument("--download", action="store_true", default=True)
    ap.add_argument("--no-download", action="store_false", dest="download")
    args = ap.parse_args()
    if args.archive_cache:
        archive_cache_zip()
    if args.download:
        snapshot_current()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
