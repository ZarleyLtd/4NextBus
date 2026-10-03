"""End-to-end handler tests: synthetic Alexa envelopes -> Lambda handler -> speech, with a fake store."""
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("NTA_API_KEY", "test-key")

from src.common import rt_cache
from src.common.gtfs_time import DUBLIN, parse_gtfs_time
from src.common.models import Departure, RealtimeFeed, StopTimeUpdate, StopTimetable, TripUpdate
from src.common.rt_cache import RealtimeCache
from src.skill import app, service as service_mod
from src.skill.service import BusService

NOW = datetime(2026, 10, 3, 20, 6, tzinfo=DUBLIN)
USER = "amzn1.ask.account.TEST"


class FakeStore:
    def __init__(self):
        self.stops = {
            "8220DB000184": StopTimetable("8220DB000184", "184", "Fairfield Rd", [
                Departure("t1", "23", "Merrion Sq", parse_gtfs_time("20:13:00"), "S1", 10),
                Departure("t2", "E2", "Dun Laoghaire", parse_gtfs_time("20:15:00"), "S1", 12),
                Departure("t3", "E1", "Ballywaltrim", parse_gtfs_time("20:19:00"), "S1", 7),
                Departure("t4", "23", "Merrion Sq", parse_gtfs_time("20:40:00"), "S1", 10),
            ]),
        }
        self.codes = {"184": {"stop_id": "8220DB000184", "stop_name": "Fairfield Rd"}}
        self.calendar = {"20261002": {"S1"}, "20261003": {"S1"}}
        self.favourites = {}
        self.last_fetch = None

    def get_stop_codes(self): return self.codes
    def get_calendar(self): return self.calendar
    def get_stop(self, stop_id): return self.stops.get(stop_id)
    def get_favourite(self, uid): return self.favourites.get(uid)
    def set_favourite(self, uid, stop_id, code, name):
        self.favourites[uid] = {"stop_id": stop_id, "stop_code": code, "stop_name": name}
    def try_acquire_rt_lock(self, now_epoch, min_interval=60):
        if self.last_fetch is None or self.last_fetch <= now_epoch - min_interval:
            self.last_fetch = now_epoch
            return True
        return False


def fake_feed(api_key, **kw):
    return RealtimeFeed(datetime.now(timezone.utc), None, {
        "t1": TripUpdate("t1", "r", "SCHEDULED", [StopTimeUpdate(10, "8220DB000184", None, None, 345, None, "SCHEDULED")]),
        "t3": TripUpdate("t3", "r", "CANCELED", []),
    })


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(rt_cache, "fetch_trip_updates", fake_feed)
    monkeypatch.setattr(service_mod, "now_dublin", lambda: NOW)
    monkeypatch.setattr(app, "_service", BusService(store, RealtimeCache(store, "k")))
    return store


def envelope(request: dict) -> dict:
    return {
        "version": "1.0",
        "session": {"new": True, "sessionId": "s1", "application": {"applicationId": "amzn1.ask.skill.test"},
                    "user": {"userId": USER}},
        "context": {"System": {"application": {"applicationId": "amzn1.ask.skill.test"}, "user": {"userId": USER},
                               "device": {"deviceId": "d1", "supportedInterfaces": {}}}},
        "request": {"requestId": "r1", "timestamp": "2026-10-03T19:06:00Z", "locale": "en-GB", **request},
    }


def intent(name, **slots):
    return envelope({"type": "IntentRequest", "intent": {
        "name": name, "confirmationStatus": "NONE",
        "slots": {k: {"name": k, "value": v, "confirmationStatus": "NONE"} for k, v in slots.items()},
    }})


def speech(resp: dict) -> str:
    return resp["response"]["outputSpeech"]["ssml"]


def test_next_bus_with_stop_number():
    resp = app.handler(intent("NextBusIntent", stopNumber="184"), None)
    text = speech(resp)
    # t1 delayed 345s -> 20:18:45 (12 min); t2 scheduled 20:15 (9 min); t3 cancelled; t4 20:40 (34 min)
    assert "At stop 184, Fairfield Road:" in text
    assert "the E2 towards Dun Laoghaire scheduled in 9 minutes" in text
    assert "the 23 towards Merrion Square in 12 minutes" in text
    assert "Ballywaltrim" not in text
    assert resp["response"]["shouldEndSession"] is True
    assert resp["response"]["card"]["title"] == "Stop 184 - Fairfield Road"


def test_unknown_stop():
    resp = app.handler(intent("NextBusIntent", stopNumber="99999"), None)
    assert "couldn't find stop number 99999" in speech(resp)


def test_next_bus_without_favourite_elicits_slot():
    resp = app.handler(intent("NextBusIntent"), None)
    assert resp["response"]["shouldEndSession"] is False
    assert resp["response"]["directives"][0]["type"] == "Dialog.ElicitSlot"
    assert "haven't set a favourite stop" in speech(resp)


def test_set_get_and_use_favourite():
    resp = app.handler(intent("SetFavouriteStopIntent", stopNumber="184"), None)
    assert "Your favourite stop is now 184, Fairfield Road" in speech(resp)
    resp = app.handler(intent("GetFavouriteStopIntent"), None)
    assert speech(resp) == "<speak>Your favourite stop is 184, Fairfield Road.</speak>"
    resp = app.handler(intent("NextBusIntent"), None)
    assert "At stop 184, Fairfield Road:" in speech(resp)
    resp = app.handler(envelope({"type": "LaunchRequest"}), None)
    assert "At stop 184, Fairfield Road:" in speech(resp)


def test_launch_without_favourite_welcomes():
    resp = app.handler(envelope({"type": "LaunchRequest"}), None)
    assert "Welcome to four next bus" in speech(resp)
    assert resp["response"]["shouldEndSession"] is False


def test_help_stop_fallback():
    assert "set my favourite stop to" in speech(app.handler(intent("AMAZON.HelpIntent"), None))
    assert "Goodbye" in speech(app.handler(intent("AMAZON.StopIntent"), None))
    assert "didn't catch that" in speech(app.handler(intent("AMAZON.FallbackIntent"), None))


def test_timetable_not_loaded_is_graceful(wired):
    wired.codes = {}
    resp = app.handler(intent("NextBusIntent", stopNumber="184"), None)
    assert "timetable isn't loaded yet" in speech(resp)
