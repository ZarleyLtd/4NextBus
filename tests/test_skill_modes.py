"""Handler tests for LUAS, Dart, and local-train intents inside 4NextBus."""
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("NTA_API_KEY", "test-key")

from src.common import rt_cache
from src.common.gtfs_time import DUBLIN, parse_gtfs_time
from src.common.models import Departure, RealtimeFeed, StopTimeUpdate, StopTimetable, TripUpdate
from src.common.rt_cache import RealtimeCache
from src.modes.dart.service import DartService
from src.modes.dart.stations import build_station as dart_build, split_raw_platforms as dart_split
from src.modes.luas.service import LuasService
from src.modes.luas.stations import build_station as luas_build
from src.modes.train.service import LocalTrainService
from src.modes.train.stations import build_station as train_build, split_raw_platforms as train_split
from src.skill import app
from src.skill import service as bus_service_mod
from src.modes.luas import service as luas_svc_mod
from src.modes.dart import service as dart_svc_mod
from src.modes.train import service as train_svc_mod
from tests.alexa_dialog import assert_open_without_dialog, speech

NOW = datetime(2026, 10, 6, 20, 6, tzinfo=DUBLIN)
USER = "amzn1.ask.account.TEST"
NORTH_ID = "8250GA00286"
SOUTH_ID = "8250GA00287"
DOM_NORTH = "8250GA00011"
DOM_SOUTH = "8250GA00012"
BROAD_NORTH = "8250GA00021"
BROAD_SOUTH = "8250GA00022"
PEARSE_ID = "8220IR0134"
CLONTARF_ID = "8220IR0090"
MAYN_ID = "8220IR0056"
BROOM_ID = "8220IR0035"
DRUM_ID = "8220IR0040"


def dundrum_station():
    return luas_build("Dundrum", [
        {"stop_id": NORTH_ID, "stop_code": "998032", "headsigns": ["Broombridge", "Parnell"]},
        {"stop_id": SOUTH_ID, "stop_code": "998132", "headsigns": ["Brides Glen", "Sandyford"]},
    ]).as_dict()


def dominick_station():
    return luas_build("Dominick", [
        {"stop_id": DOM_NORTH, "stop_code": "998011", "headsigns": ["Broombridge", "Parnell"]},
        {"stop_id": DOM_SOUTH, "stop_code": "998012", "headsigns": ["Brides Glen", "Sandyford"]},
    ]).as_dict()


def broadstone_station():
    return luas_build("Broadstone", [
        {"stop_id": BROAD_NORTH, "stop_code": "998021", "headsigns": ["Broombridge", "Parnell"]},
        {"stop_id": BROAD_SOUTH, "stop_code": "998022", "headsigns": ["Brides Glen", "Sandyford"]},
    ]).as_dict()


def pease_dart():
    return dart_build("Dublin Pearse", dart_split(
        PEARSE_ID, "1", "Dublin Pearse",
        ["Howth", "Malahide", "Dublin Connolly", "Bray (Daly)", "Greystones", "Grand Canal Dock"],
    )).as_dict()


def clontarf_dart():
    return dart_build("Clontarf Road", dart_split(
        CLONTARF_ID, "90", "Clontarf Road",
        ["Howth", "Malahide", "Dublin Connolly", "Bray (Daly)", "Greystones"],
    )).as_dict()


def maynooth_train():
    return train_build("Maynooth", train_split(
        MAYN_ID, "2", "Maynooth",
        ["Dublin Connolly", "Dublin Pearse", "Maynooth", "Longford"],
    )).as_dict()


def broombridge_train():
    return train_build("Broombridge", train_split(
        BROOM_ID, "35", "Broombridge",
        ["Dublin Connolly", "Dublin Pearse", "Maynooth", "Longford", "M3 Parkway",
         "Bray (Daly)", "Dun Laoghaire (Mallin)"],
    )).as_dict()


def drumcondra_train():
    return train_build("Drumcondra", train_split(
        DRUM_ID, "11", "Drumcondra",
        ["Dublin Connolly", "Dublin Pearse", "Maynooth", "Longford"],
    )).as_dict()


class FakeStore:
    def __init__(self):
        self.stops = {
            ("luas", NORTH_ID): StopTimetable(NORTH_ID, "998032", "Dundrum", [
                Departure("lt1", "Green", "Broombridge", parse_gtfs_time("20:13:00"), "S1", 10),
            ]),
            ("luas", SOUTH_ID): StopTimetable(SOUTH_ID, "998132", "Dundrum", [
                Departure("lt4", "Green", "Brides Glen", parse_gtfs_time("20:12:00"), "S1", 8),
            ]),
            ("luas", DOM_NORTH): StopTimetable(DOM_NORTH, "998011", "Dominick", [
                Departure("ld1", "Green", "Broombridge", parse_gtfs_time("20:11:00"), "S1", 9),
            ]),
            ("luas", DOM_SOUTH): StopTimetable(DOM_SOUTH, "998012", "Dominick", [
                Departure("ld2", "Green", "Brides Glen", parse_gtfs_time("20:10:00"), "S1", 7),
            ]),
            ("luas", BROAD_NORTH): StopTimetable(BROAD_NORTH, "998021", "Broadstone", [
                Departure("lb1", "Green", "Broombridge", parse_gtfs_time("20:11:00"), "S1", 9),
            ]),
            ("luas", BROAD_SOUTH): StopTimetable(BROAD_SOUTH, "998022", "Broadstone", [
                Departure("lb2", "Green", "Brides Glen", parse_gtfs_time("20:10:00"), "S1", 7),
            ]),
            ("dart", PEARSE_ID): StopTimetable(PEARSE_ID, "1", "Dublin Pearse", [
                Departure("dt1", "DART", "Bray (Daly)", parse_gtfs_time("20:14:00"), "S1", 5),
                Departure("dt2", "DART", "Howth", parse_gtfs_time("20:16:00"), "S1", 6),
            ]),
            ("dart", CLONTARF_ID): StopTimetable(CLONTARF_ID, "90", "Clontarf Road", [
                Departure("dc1", "DART", "Howth", parse_gtfs_time("20:12:00"), "S1", 7),
                Departure("dc2", "DART", "Bray (Daly)", parse_gtfs_time("20:15:00"), "S1", 8),
            ]),
            ("train", MAYN_ID): StopTimetable(MAYN_ID, "2", "Maynooth", [
                Departure("ct1", "Commuter", "Dublin Connolly", parse_gtfs_time("20:15:00"), "S1", 3),
            ]),
            ("train", BROOM_ID): StopTimetable(BROOM_ID, "35", "Broombridge", [
                Departure("bt1", "Commuter", "Maynooth", parse_gtfs_time("20:12:00"), "S1", 4),
                Departure("bt2", "Commuter", "Dublin Connolly", parse_gtfs_time("20:14:00"), "S1", 5),
                Departure("bt3", "Commuter", "M3 Parkway", parse_gtfs_time("20:16:00"), "S1", 6),
            ]),
            ("train", DRUM_ID): StopTimetable(DRUM_ID, "11", "Drumcondra", [
                Departure("dtc1", "Commuter", "Dublin Connolly", parse_gtfs_time("20:13:00"), "S1", 4),
                Departure("dtc2", "Commuter", "Maynooth", parse_gtfs_time("20:16:00"), "S1", 5),
            ]),
        }
        self.stations = {
            "luas": [dundrum_station(), dominick_station(), broadstone_station()],
            "dart": [pease_dart(), clontarf_dart()],
            "train": [maynooth_train(), broombridge_train(), drumcondra_train()],
        }
        self.calendar = {"20261005": {"S1"}, "20261006": {"S1"}}
        self.favourites = {}
        self.last_fetch = None

    def get_stations(self, mode):
        return self.stations.get(mode, [])

    def get_calendar(self):
        return self.calendar

    def get_stop(self, stop_id, mode=None):
        return self.stops.get((mode, stop_id))

    def get_favourite(self, uid, mode=None):
        return self.favourites.get((uid, mode or "bus"))

    def set_favourite(self, uid, stop_id, code, name, mode=None, heads=None, label=""):
        self.favourites[(uid, mode or "bus")] = {
            "stop_id": stop_id, "stop_code": code, "stop_name": name,
            "heads": heads or [], "label": label,
        }

    def clear_favourite(self, uid, mode=None):
        self.favourites.pop((uid, mode or "bus"), None)

    def try_acquire_rt_lock(self, now_epoch, min_interval=60):
        if self.last_fetch is None or self.last_fetch <= now_epoch - min_interval:
            self.last_fetch = now_epoch
            return True
        return False


def fake_feed(api_key, **kw):
    return RealtimeFeed(datetime.now(timezone.utc), None, {
        "lt1": TripUpdate("lt1", "r", "SCHEDULED",
                          [StopTimeUpdate(10, NORTH_ID, None, None, 0, None, "SCHEDULED")]),
    })


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    store = FakeStore()
    rt = RealtimeCache(store, "k")
    monkeypatch.setattr(rt_cache, "fetch_trip_updates", fake_feed)
    for mod in (bus_service_mod, luas_svc_mod, dart_svc_mod, train_svc_mod):
        monkeypatch.setattr(mod, "now_dublin", lambda: NOW)
    monkeypatch.setattr(app, "_luas", LuasService(store, rt))
    monkeypatch.setattr(app, "_dart", DartService(store, rt))
    monkeypatch.setattr(app, "_train", LocalTrainService(store, rt))
    monkeypatch.setattr(app, "_store", store)
    monkeypatch.setattr(app, "_realtime", rt)
    return store


def envelope(request: dict) -> dict:
    return {
        "version": "1.0",
        "session": {"new": True, "sessionId": "s1", "application": {"applicationId": "amzn1.ask.skill.test"},
                    "user": {"userId": USER}},
        "context": {"System": {"application": {"applicationId": "amzn1.ask.skill.test"}, "user": {"userId": USER},
                               "device": {"deviceId": "d1", "supportedInterfaces": {}}}},
        "request": {"requestId": "r1", "timestamp": "2026-10-06T19:06:00Z", "locale": "en-GB", **request},
    }


def intent(name, **slots):
    return envelope({"type": "IntentRequest", "intent": {
        "name": name, "confirmationStatus": "NONE",
        "slots": {k: {"name": k, "value": v, "confirmationStatus": "NONE"} for k, v in slots.items()},
    }})


def continuing(name, attrs, **slots):
    env = intent(name, **slots)
    env["session"]["new"] = False
    env["session"]["attributes"] = dict(attrs or {})
    return env


def test_next_luas_dundrum_southbound():
    resp = app.handler(intent("NextLuasIntent", luasStation="Dundrum", luasDirection="southbound"), None)
    text = speech(resp)
    assert "At Dundrum:" in text
    assert "to Brides Glen" in text


def test_next_luas_unknown_station():
    resp = app.handler(intent("NextLuasIntent", luasStation="Connolly"), None)
    # Connolly is not in the test LUAS catalog.
    text = speech(resp)
    assert "don't know a" in text
    assert "Luas" in text
    assert "Connolly" in text


def test_set_and_get_luas_favourite():
    resp = app.handler(intent("SetFavouriteLuasIntent", luasStation="Dundrum", luasDirection="southbound"), None)
    assert "favourite" in speech(resp) and "Luas" in speech(resp)
    resp = app.handler(intent("GetFavouriteLuasIntent"), None)
    assert "Luas" in speech(resp)
    assert "Dundrum" in speech(resp)
    resp = app.handler(intent("NextLuasIntent"), None)
    assert "to Brides Glen" in speech(resp)


def test_next_dart_pearse_southbound():
    resp = app.handler(intent("NextDartIntent", dartStation="Pearse", dartDirection="southbound"), None)
    text = speech(resp)
    assert "At Pearse:" in text
    assert "to Bray" in text
    assert "Howth" not in text


def test_set_dart_favourite():
    resp = app.handler(intent("SetFavouriteDartIntent", dartStation="Pearse", dartDirection="southbound"), None)
    assert "favourite Dart stop is now" in speech(resp)
    resp = app.handler(intent("GetFavouriteDartIntent"), None)
    assert "Pearse" in speech(resp)


def test_next_local_train_maynooth_eastbound():
    resp = app.handler(intent("NextLocalTrainIntent", trainStation="Maynooth", trainDirection="eastbound"), None)
    text = speech(resp)
    assert "At Maynooth:" in text
    assert "to Connolly" in text or "to Dublin Connolly" in text


def test_set_local_train_favourite():
    resp = app.handler(intent("SetFavouriteLocalTrainIntent", trainStation="Maynooth", trainDirection="eastbound"), None)
    assert "favourite local train stop is now" in speech(resp)
    resp = app.handler(intent("GetFavouriteLocalTrainIntent"), None)
    assert "Maynooth" in speech(resp)


def test_luas_no_favourite_elicits():
    resp = app.handler(intent("NextLuasIntent"), None)
    text = speech(resp)
    assert "haven't set a favourite" in text
    assert "Luas" in text
    assert_open_without_dialog(resp, pending_action="set_favourite")


def test_dart_no_favourite_elicits():
    resp = app.handler(intent("NextDartIntent"), None)
    assert "haven't set a favourite Dart stop" in speech(resp)
    attrs = assert_open_without_dialog(resp, pending_action="set_favourite")
    assert attrs.get("pending_mode") == "dart"


def test_train_no_favourite_elicits():
    resp = app.handler(intent("NextLocalTrainIntent"), None)
    assert "haven't set a favourite local train stop" in speech(resp)
    assert_open_without_dialog(resp, pending_action="set_favourite")


def test_set_favourite_misrouted_as_station():
    for name, slot in (
        ("NextDartIntent", "dartStation"),
        ("NextLuasIntent", "luasStation"),
        ("NextLocalTrainIntent", "trainStation"),
        ("NextDartQueryIntent", "dartQuery"),
    ):
        resp = app.handler(intent(name, **{slot: "to set my favorite stop"}), None)
        assert resp["response"]["shouldEndSession"] is False, name
        assert "should I save as your favourite" in speech(resp), name


def test_pending_dart_favourite_is_not_stolen_by_bus():
    first = app.handler(intent("NextDartIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    stolen = app.handler(continuing("NextBusIntent", attrs), None)
    assert "Fairfield" not in speech(stolen)
    assert_open_without_dialog(stolen, pending_action="set_favourite")
    follow = app.handler(continuing(
        "SetFavouriteDartIntent", stolen.get("sessionAttributes") or attrs,
        dartStation="Pearse", dartDirection="southbound",
    ), None)
    assert "favourite Dart stop is now" in speech(follow)
    assert "Pearse" in speech(follow)


def test_dart_favourite_dialog_station_then_direction():
    first = app.handler(intent("NextDartIntent"), None)
    mid = app.handler(continuing(
        "SetFavouriteDartIntent", first.get("sessionAttributes") or {}, dartStation="Pearse",
    ), None)
    assert "Which direction" in speech(mid)
    assert_open_without_dialog(mid, pending_station="Pearse", pending_action="set_favourite")
    done = app.handler(continuing(
        "SetFavouriteDartIntent", mid.get("sessionAttributes") or {},
        dartStation="Pearse", dartDirection="southbound",
    ), None)
    assert "favourite Dart stop is now" in speech(done)


def test_train_going_east_is_eastbound():
    for kwargs in (
        {"trainStation": "Broombridge", "trainDirection": "going east"},
        {"trainStation": "Broombridge", "trainDirection": "east"},
        {"trainStation": "Broombridge going east"},
    ):
        resp = app.handler(intent("NextLocalTrainIntent", **kwargs), None)
        text = speech(resp)
        assert "Which direction" not in text, kwargs
        assert "At Broombridge" in text, kwargs
        assert "Connolly" in text or "Pearse" in text, kwargs


def test_train_direction_follow_up_after_broombridge():
    first = app.handler(intent("NextLocalTrainIntent", trainStation="Broombridge"), None)
    assert "Which direction at Broombridge" in speech(first)
    attrs = assert_open_without_dialog(first, pending_station="Broombridge")
    follow = app.handler(continuing("NextLocalTrainIntent", attrs, trainDirection="westbound"), None)
    assert follow["response"].get("shouldEndSession") is True
    assert "At Broombridge" in speech(follow)
    assert "Maynooth" in speech(follow)


def test_train_direction_follow_up_not_stolen_by_bus_or_set():
    first = app.handler(intent("NextLocalTrainIntent", trainStation="Broombridge"), None)
    attrs = assert_open_without_dialog(first, pending_station="Broombridge")
    stolen = app.handler(continuing("NextBusIntent", attrs), None)
    assert "Fairfield" not in speech(stolen)
    assert_open_without_dialog(stolen, pending_station="Broombridge")
    times = app.handler(continuing(
        "SetFavouriteLocalTrainIntent", stolen.get("sessionAttributes") or attrs,
        trainDirection="westbound",
    ), None)
    assert "At Broombridge" in speech(times)
    assert "favourite" not in speech(times).lower()


def test_luas_and_dart_direction_follow_up():
    luas = app.handler(intent("NextLuasIntent", luasStation="Dundrum"), None)
    luas_attrs = assert_open_without_dialog(luas, pending_station="Dundrum")
    luas_done = app.handler(continuing(
        "NextLuasIntent", luas_attrs, luasDirection="southbound",
    ), None)
    assert "At Dundrum" in speech(luas_done)
    dart = app.handler(intent("NextDartIntent", dartStation="Pearse"), None)
    dart_attrs = assert_open_without_dialog(dart, pending_station="Pearse")
    dart_done = app.handler(continuing(
        "NextDartIntent", dart_attrs, dartDirection="southbound",
    ), None)
    assert "At Pearse" in speech(dart_done)


@pytest.mark.parametrize("name,slots,spoken", [
    ("NextLuasIntent", {"luasStation": "Broadstone"}, "Broadstone DIT"),
    ("NextLuasIntent", {"luasStation": "Dundrum"}, "Dundrum"),
    ("NextLuasIntent", {"luasStation": "Dominick"}, "Dominick"),
    ("NextDartIntent", {"dartStation": "Pearse"}, "Pearse"),
    ("NextLocalTrainIntent", {"trainStation": "Broombridge"}, "Broombridge"),
])
def test_direction_prompt_does_not_use_dialog_elicit(name, slots, spoken):
    first = app.handler(intent(name, **slots), None)
    assert f"Which direction at {spoken}" in speech(first)
    assert_open_without_dialog(first, pending_station=spoken)


def test_broadstone_one_word_follow_ups_never_silent():
    """Simulate the utterances Alexa actually delivers after an open ask.

    The old test only sent NextLuasIntent with luasDirection=northbound, which
    is what ElicitSlot would have produced if Alexa had forwarded the word.
    On a device that request never arrived.
    """
    first = app.handler(intent("NextLuasIntent", luasStation="Broadstone"), None)
    attrs = assert_open_without_dialog(first, pending_station="Broadstone DIT")
    for follow in (
        continuing("NextLuasIntent", attrs, luasDirection="northbound"),
        continuing("NextLuasIntent", attrs, luasStation="northbound"),
        continuing("NextLuasQueryIntent", attrs, luasQuery="northbound"),
    ):
        resp = app.handler(follow, None)
        assert speech(resp), follow["request"]["intent"]["name"]
        assert "At Broadstone DIT" in speech(resp)
        assert "Broombridge" in speech(resp)
        assert resp["response"].get("shouldEndSession") is True
    for follow in (
        continuing("NextLuasIntent", attrs),
        continuing("AMAZON.FallbackIntent", attrs),
        continuing("NextBusIntent", attrs),
    ):
        resp = app.handler(follow, None)
        assert speech(resp), "empty speech looks silent on the device"
        assert_open_without_dialog(resp, pending_station="Broadstone DIT")
        assert "Fairfield" not in speech(resp)
        assert "Which direction" in speech(resp)


@pytest.mark.parametrize(
    "next_name,set_name,set_query_name,query_name,get_name,station_slot,dir_slot,query_slot,"
    "station,direction,spoken",
    [
        ("NextLuasIntent", "SetFavouriteLuasIntent", "SetFavouriteLuasQueryIntent",
         "NextLuasQueryIntent", "GetFavouriteLuasIntent",
         "luasStation", "luasDirection", "luasQuery", "Dundrum", "southbound", "Dundrum"),
        ("NextDartIntent", "SetFavouriteDartIntent", "SetFavouriteDartQueryIntent",
         "NextDartQueryIntent", "GetFavouriteDartIntent",
         "dartStation", "dartDirection", "dartQuery", "Pearse", "southbound", "Pearse"),
        ("NextLocalTrainIntent", "SetFavouriteLocalTrainIntent", "SetFavouriteLocalTrainQueryIntent",
         "NextLocalTrainQueryIntent", "GetFavouriteLocalTrainIntent",
         "trainStation", "trainDirection", "trainQuery", "Maynooth", "westbound", "Maynooth"),
    ],
)
def test_no_favourite_glued_and_station_then_direction(
    next_name, set_name, set_query_name, query_name, get_name, station_slot, dir_slot, query_slot,
    station, direction, spoken, wired,
):
    """After 'or LUAS/Dart/local train', set-favourite vs a leftover next/from query.

    Follow-ups are an open session (no Dialog.ElicitSlot). A Next* / from
    {station} utterance during leftover set-favourite must give times, not save.
    """
    first = app.handler(intent(next_name), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")

    for follow in (
        continuing(next_name, attrs, **{station_slot: station, dir_slot: direction}),
        continuing(query_name, attrs, **{query_slot: f"from {station} {direction}"}),
        continuing(set_query_name, attrs, **{query_slot: f"from {station} {direction}"}),
    ):
        resp = app.handler(follow, None)
        text = speech(resp)
        assert text, follow["request"]["intent"]["name"]
        assert "don't know" not in text, text
        assert spoken in text
        assert "favourite" not in text.lower(), text
        assert resp["response"].get("shouldEndSession") is True
        got = app.handler(intent(get_name), None)
        assert "haven't set a favourite" in speech(got)

    wired.favourites.clear()
    for follow in (
        continuing(set_name, attrs, **{station_slot: station, dir_slot: direction}),
        continuing(set_query_name, attrs, **{query_slot: f"{station} {direction}"}),
        continuing(next_name, attrs, **{station_slot: f"{station} {direction}"}),
        continuing(query_name, attrs, **{query_slot: f"{station} {direction}"}),
    ):
        resp = app.handler(follow, None)
        text = speech(resp)
        assert text, follow["request"]["intent"]["name"]
        assert "don't know" not in text, text
        assert spoken in text
        assert "favourite" in text.lower()
        assert resp["response"].get("shouldEndSession") is True

    wired.favourites.clear()
    first = app.handler(intent(next_name), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    mid_times = app.handler(continuing(next_name, attrs, **{station_slot: station}), None)
    assert f"Which direction at {spoken}" in speech(mid_times)
    assert_open_without_dialog(
        mid_times, pending_station=spoken, pending_action="set_favourite",
    )

    wired.favourites.clear()
    first = app.handler(intent(next_name), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    mid = app.handler(continuing(set_name, attrs, **{station_slot: station}), None)
    assert f"Which direction at {spoken}" in speech(mid)
    mid_attrs = assert_open_without_dialog(
        mid, pending_station=spoken, pending_action="set_favourite",
    )
    for follow in (
        continuing(next_name, mid_attrs, **{dir_slot: direction}),
        continuing(next_name, mid_attrs, **{station_slot: direction}),
        continuing(set_name, mid_attrs, **{dir_slot: direction}),
        continuing(set_query_name, mid_attrs, **{query_slot: direction}),
    ):
        resp = app.handler(follow, None)
        text = speech(resp)
        assert text, follow["request"]["intent"]["name"]
        assert "Which direction" not in text, text
        assert spoken in text
        assert "favourite" in text.lower()
        assert resp["response"].get("shouldEndSession") is True

    empty = app.handler(continuing(next_name, attrs), None)
    assert_open_without_dialog(empty, pending_action="set_favourite")
    assert "Fairfield" not in speech(empty)


def test_first_use_pearse_southbound_saves_favourite():
    """Device: 'or dart' then 'pearse southbound' must save, not go silent."""
    first = app.handler(intent("NextDartIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    for follow in (
        continuing("SetFavouriteDartIntent", attrs,
                   dartStation="Pearse", dartDirection="southbound"),
        continuing("SetFavouriteDartQueryIntent", attrs, dartQuery="pearse southbound"),
    ):
        resp = app.handler(follow, None)
        assert "favourite Dart stop is now" in speech(resp)
        assert "Pearse" in speech(resp)
        assert resp["response"].get("shouldEndSession") is True


def test_first_use_maynooth_asks_direction_not_wikipedia():
    """Device: 'or local train' then 'maynooth' must stay in-skill and ask direction."""
    first = app.handler(intent("NextLocalTrainIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    for follow in (
        continuing("SetFavouriteLocalTrainIntent", attrs, trainStation="Maynooth"),
        continuing("SetFavouriteLocalTrainQueryIntent", attrs, trainQuery="maynooth"),
        continuing("NextLocalTrainIntent", attrs, trainDirection="Maynooth"),
    ):
        resp = app.handler(follow, None)
        assert "Which direction at Maynooth" in speech(resp)
        assert_open_without_dialog(resp, pending_station="Maynooth", pending_action="set_favourite")


def test_dart_nortbound_typo_is_northbound():
    resp = app.handler(intent("NextDartIntent", dartStation="clontarf road nortbound"), None)
    text = speech(resp)
    assert "don't know" not in text
    assert "Clontarf" in text
    assert "Howth" in text
    assert "Bray" not in text


def test_luas_dominick_northbound_follow_ups():
    first = app.handler(intent("NextLuasIntent", luasStation="Dominick"), None)
    assert "Which direction at Dominick" in speech(first)
    attrs = assert_open_without_dialog(first, pending_station="Dominick")
    for follow in (
        continuing("NextLuasIntent", attrs, luasDirection="northbound"),
        continuing("NextLuasIntent", attrs, luasDirection="going north"),
        continuing("NextLuasIntent", attrs, luasStation="northbound"),
        continuing("AMAZON.FallbackIntent", attrs),
        continuing("NextBusIntent", attrs),
    ):
        resp = app.handler(follow, None)
        assert speech(resp)
        if follow["request"]["intent"]["name"] in ("AMAZON.FallbackIntent", "NextBusIntent"):
            assert_open_without_dialog(resp, pending_station="Dominick")
            assert "Fairfield" not in speech(resp)
            continue
        assert "Which direction" not in speech(resp)
        assert "At Dominick" in speech(resp)
        assert "Broombridge" in speech(resp)


@pytest.mark.parametrize("set_name,get_name,clear_name,slots,spoken", [
    ("SetFavouriteLuasIntent", "GetFavouriteLuasIntent", "ClearFavouriteLuasIntent",
     {"luasStation": "Dundrum", "luasDirection": "southbound"}, "Dundrum"),
    ("SetFavouriteDartIntent", "GetFavouriteDartIntent", "ClearFavouriteDartIntent",
     {"dartStation": "Pearse", "dartDirection": "southbound"}, "Pearse"),
    ("SetFavouriteLocalTrainIntent", "GetFavouriteLocalTrainIntent",
     "ClearFavouriteLocalTrainIntent",
     {"trainStation": "Maynooth", "trainDirection": "eastbound"}, "Maynooth"),
])
def test_forget_favourite_per_mode(set_name, get_name, clear_name, slots, spoken):
    saved = app.handler(intent(set_name, **slots), None)
    assert "favourite" in speech(saved).lower()
    assert spoken in speech(saved)
    assert spoken in speech(app.handler(intent(get_name), None))
    forgotten = app.handler(intent(clear_name), None)
    assert "I've forgotten" in speech(forgotten)
    none = speech(app.handler(intent(clear_name), None))
    assert "didn't have a favourite" in none
    got = speech(app.handler(intent(get_name), None))
    assert "haven't set a favourite" in got


def test_forget_all_favourites():
    app.handler(intent("SetFavouriteLuasIntent", luasStation="Dundrum",
                       luasDirection="southbound"), None)
    app.handler(intent("SetFavouriteDartIntent", dartStation="Pearse",
                       dartDirection="southbound"), None)
    app.handler(intent("SetFavouriteLocalTrainIntent", trainStation="Maynooth",
                       trainDirection="eastbound"), None)
    resp = app.handler(intent("ClearAllFavouritesIntent"), None)
    assert "I've forgotten all your favourite stops" in speech(resp)
    assert "haven't set a favourite" in speech(app.handler(intent("GetFavouriteLuasIntent"), None))
    assert "haven't set a favourite" in speech(app.handler(intent("GetFavouriteDartIntent"), None))
    assert "haven't set a favourite" in speech(
        app.handler(intent("GetFavouriteLocalTrainIntent"), None))


def test_forget_does_not_need_timetable(wired, monkeypatch):
    app.handler(intent("SetFavouriteLuasIntent", luasStation="Dundrum",
                       luasDirection="southbound"), None)

    def boom(*_a, **_k):
        raise RuntimeError("forget must not load the station catalog")

    monkeypatch.setattr(wired, "get_stations", boom)
    resp = app.handler(intent("ClearFavouriteLuasIntent"), None)
    assert "I've forgotten" in speech(resp)


def test_forget_clears_pending_set_favourite():
    first = app.handler(intent("NextDartIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    done = app.handler(continuing("ClearFavouriteDartIntent", attrs), None)
    assert "didn't have a favourite" in speech(done)
    assert done["response"].get("shouldEndSession") is True
    assert not (done.get("sessionAttributes") or {}).get("pending_action")
