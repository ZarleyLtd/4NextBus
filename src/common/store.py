"""Single-table DynamoDB access for 4NextBus.

Table (pk S, sk S), provisioned 25 RCU / 25 WCU (free tier):

  STOP#<stop_id>   SCHED      stop_code, stop_name, hash, feed_version, gz (gzipped JSON departures)
  META             STOPCODES  gz: {stop_code: [stop_id, stop_name]}
  META             CALENDAR   gz: {YYYYMMDD: [service_id, ...]}
  META             MANIFEST   gz: {stop_id: hash}, feed_version, updated_at
  META             RTLOCK     last_fetch (N, epoch seconds)
  USER#<user_id>   PROFILE    stop_id, stop_code, stop_name, updated_at

Uses the low-level boto3 client to keep Lambda cold starts short.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .models import ServiceCalendar, StopTimetable


def pack(obj: Any) -> bytes:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def unpack(blob: bytes) -> Any:
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def content_hash(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=False).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


class Store:
    def __init__(self, table_name: str, region: str | None = None, client=None):
        self.table = table_name
        self.ddb = client or boto3.client("dynamodb", region_name=region)

    # ---- low level -------------------------------------------------------------

    def _get(self, pk: str, sk: str, consistent: bool = False) -> dict | None:
        resp = self.ddb.get_item(TableName=self.table, Key={"pk": {"S": pk}, "sk": {"S": sk}},
                                 ConsistentRead=consistent)
        return resp.get("Item")

    def _put(self, pk: str, sk: str, attrs: dict[str, dict]) -> None:
        item = {"pk": {"S": pk}, "sk": {"S": sk}, **attrs}
        self.ddb.put_item(TableName=self.table, Item=item)

    @staticmethod
    def _s(v: str) -> dict:
        return {"S": v}

    @staticmethod
    def _n(v: int | float) -> dict:
        return {"N": str(v)}

    @staticmethod
    def _b(v: bytes) -> dict:
        return {"B": v}

    # ---- timetable -------------------------------------------------------------

    def put_stop(self, stop: StopTimetable, feed_version: str, hash_: str) -> int:
        """Write a stop's timetable. Returns approximate item size in bytes."""
        gz = pack([d.to_row() for d in stop.departures])
        self._put(f"STOP#{stop.stop_id}", "SCHED", {
            "stop_code": self._s(stop.stop_code),
            "stop_name": self._s(stop.stop_name),
            "hash": self._s(hash_),
            "feed_version": self._s(feed_version),
            "updated_at": self._n(int(time.time())),
            "gz": self._b(gz),
        })
        return len(gz) + 200

    def get_stop(self, stop_id: str) -> StopTimetable | None:
        item = self._get(f"STOP#{stop_id}", "SCHED")
        if not item:
            return None
        return StopTimetable.from_dict({
            "stop_id": stop_id,
            "stop_code": item["stop_code"]["S"],
            "stop_name": item["stop_name"]["S"],
            "departures": unpack(item["gz"]["B"]),
        })

    def put_stop_codes(self, codes: dict[str, dict]) -> None:
        compact = {code: [v["stop_id"], v["stop_name"]] for code, v in codes.items()}
        self._put("META", "STOPCODES", {"gz": self._b(pack(compact)), "updated_at": self._n(int(time.time()))})

    def get_stop_codes(self) -> dict[str, dict]:
        item = self._get("META", "STOPCODES")
        if not item:
            return {}
        return {code: {"stop_id": v[0], "stop_name": v[1]} for code, v in unpack(item["gz"]["B"]).items()}

    def put_calendar(self, cal: ServiceCalendar) -> None:
        self._put("META", "CALENDAR", {"gz": self._b(pack({k: sorted(v) for k, v in cal.items()})),
                                       "updated_at": self._n(int(time.time()))})

    def get_calendar(self) -> ServiceCalendar:
        item = self._get("META", "CALENDAR")
        if not item:
            return {}
        return {k: set(v) for k, v in unpack(item["gz"]["B"]).items()}

    def put_manifest(self, hashes: dict[str, str], feed_version: str) -> None:
        self._put("META", "MANIFEST", {"gz": self._b(pack(hashes)), "feed_version": self._s(feed_version),
                                       "updated_at": self._n(int(time.time()))})

    def get_manifest(self) -> tuple[dict[str, str], str | None]:
        item = self._get("META", "MANIFEST", consistent=True)
        if not item:
            return {}, None
        return unpack(item["gz"]["B"]), item.get("feed_version", {}).get("S")

    def delete_stop(self, stop_id: str) -> None:
        self.ddb.delete_item(TableName=self.table, Key={"pk": {"S": f"STOP#{stop_id}"}, "sk": {"S": "SCHED"}})

    # ---- realtime lock -----------------------------------------------------------

    def try_acquire_rt_lock(self, now_epoch: int, min_interval: int = 60) -> bool:
        """Atomically claim the right to call NTA. True if we may fetch now."""
        try:
            self.ddb.update_item(
                TableName=self.table,
                Key={"pk": {"S": "META"}, "sk": {"S": "RTLOCK"}},
                UpdateExpression="SET last_fetch = :now",
                ConditionExpression="attribute_not_exists(last_fetch) OR last_fetch <= :cutoff",
                ExpressionAttributeValues={":now": self._n(now_epoch), ":cutoff": self._n(now_epoch - min_interval)},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    # ---- users -------------------------------------------------------------------

    def get_favourite(self, user_id: str) -> dict | None:
        item = self._get(f"USER#{user_id}", "PROFILE")
        if not item or "stop_id" not in item:
            return None
        return {"stop_id": item["stop_id"]["S"], "stop_code": item["stop_code"]["S"], "stop_name": item["stop_name"]["S"]}

    def set_favourite(self, user_id: str, stop_id: str, stop_code: str, stop_name: str) -> None:
        self._put(f"USER#{user_id}", "PROFILE", {
            "stop_id": self._s(stop_id), "stop_code": self._s(stop_code), "stop_name": self._s(stop_name),
            "updated_at": self._n(int(time.time())),
        })
