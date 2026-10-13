"""Device-realistic follow-up regression tests.

Each case below is a failure we saw on a phone or in the Alexa simulator.
Handler tests that only send a filled custom slot (luasDirection=northbound)
miss the actual device path: Alexa never copies that word into the slot.

Run: pytest tests/test_dialog_regression.py tests/test_voice_model_contracts.py

Do not 'fix' failures in this file by adding Dialog.ElicitSlot. That is the
bug. Keep an open session, a full-text reprompt, and samples that match the
bare follow-up as a normal intent.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("NTA_API_KEY", "test-key")

from src.common import rt_cache
from src.common.rt_cache import RealtimeCache
from src.modes.dart.service import DartService
from src.modes.luas.service import LuasService
from src.modes.train.service import LocalTrainService
from src.skill import app
from src.skill import service as bus_service_mod
from src.modes.luas import service as luas_svc_mod
from src.modes.dart import service as dart_svc_mod
from src.modes.train import service as train_svc_mod

from tests.alexa_dialog import assert_not_silent, assert_open_without_dialog, speech
from tests.test_skill_modes import FakeStore, NOW, continuing, fake_feed, intent

PROMPT_PATHS = [
    ("NextLuasIntent", {}, "set_favourite", None),
    ("NextDartIntent", {}, "set_favourite", None),
    ("NextLocalTrainIntent", {}, "set_favourite", None),
    ("NextLuasIntent", {"luasStation": "Broadstone"}, "need_direction", "Broadstone DIT"),
    ("NextLuasIntent", {"luasStation": "Dundrum"}, "need_direction", "Dundrum"),
    ("NextLuasIntent", {"luasStation": "Dominick"}, "need_direction", "Dominick"),
    ("NextDartIntent", {"dartStation": "Pearse"}, "need_direction", "Pearse"),
    ("NextLocalTrainIntent", {"trainStation": "Broombridge"}, "need_direction", "Broombridge"),
    ("NextLocalTrainIntent", {"trainStation": "Maynooth"}, "need_direction", "Maynooth"),
]


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


@pytest.mark.parametrize("name,slots,action,station", PROMPT_PATHS)
def test_named_prompt_is_open_session_with_full_reprompt(name, slots, action, station):
    """Every named-mode prompt: no Dialog.*, full-text reprompt, not silent."""
    resp = app.handler(intent(name, **slots), None)
    assert_open_without_dialog(resp, pending_action=action, pending_station=station)


@pytest.mark.parametrize("next_name,station_slot,dir_slot,query_name,query_slot,station,direction,spoken,expect", [
    ("NextLuasIntent", "luasStation", "luasDirection", "NextLuasQueryIntent", "luasQuery",
     "Broadstone", "northbound", "Broadstone DIT", "Broombridge"),
    ("NextLuasIntent", "luasStation", "luasDirection", "NextLuasQueryIntent", "luasQuery",
     "Dominick", "northbound", "Dominick", "Broombridge"),
    ("NextDartIntent", "dartStation", "dartDirection", "NextDartQueryIntent", "dartQuery",
     "Pearse", "southbound", "Pearse", "Bray"),
    ("NextLocalTrainIntent", "trainStation", "trainDirection", "NextLocalTrainQueryIntent",
     "trainQuery", "Broombridge", "westbound", "Broombridge", "Maynooth"),
])
def test_times_direction_follow_up_never_silent(
    next_name, station_slot, dir_slot, query_name, query_slot, station, direction, spoken, expect,
):
    """After 'from {station}', Alexa may deliver the compass in any slot — or not at all."""
    first = app.handler(intent(next_name, **{station_slot: station}), None)
    attrs = assert_open_without_dialog(first, pending_station=spoken, pending_action="need_direction")
    for follow in (
        continuing(next_name, attrs, **{dir_slot: direction}),
        continuing(next_name, attrs, **{station_slot: direction}),
        continuing(query_name, attrs, **{query_slot: direction}),
        continuing("AMAZON.FallbackIntent", attrs),
        continuing("NextBusIntent", attrs),
    ):
        resp = app.handler(follow, None)
        text = assert_not_silent(resp)
        assert "Fairfield" not in text
        name = follow["request"]["intent"]["name"]
        if name in ("AMAZON.FallbackIntent", "NextBusIntent"):
            assert_open_without_dialog(resp, pending_station=spoken, pending_action="need_direction")
            continue
        assert "Which direction" not in text, text
        assert f"At {spoken}" in text
        assert expect in text
        assert resp["response"].get("shouldEndSession") is True


def test_first_use_glued_phrase_saves_favourite_not_silence(wired):
    """Simulator: 'or dart' then 'pearse southbound' used to finish in silence."""
    first = app.handler(intent("NextDartIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    for follow in (
        continuing("SetFavouriteDartIntent", attrs,
                   dartStation="Pearse", dartDirection="southbound"),
        continuing("SetFavouriteDartQueryIntent", attrs, dartQuery="pearse southbound"),
        continuing("SetFavouriteDartIntent", attrs, dartStation="Pearse southbound"),
    ):
        wired.favourites.clear()
        resp = app.handler(follow, None)
        text = assert_not_silent(resp)
        assert "favourite Dart stop is now" in text
        assert "Pearse" in text
        assert resp["response"].get("shouldEndSession") is True


def test_first_use_station_only_stays_in_skill(wired):
    """Simulator: 'or local train' then 'maynooth' used to hit Wikipedia."""
    first = app.handler(intent("NextLocalTrainIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    for follow in (
        continuing("SetFavouriteLocalTrainIntent", attrs, trainStation="Maynooth"),
        continuing("SetFavouriteLocalTrainQueryIntent", attrs, trainQuery="maynooth"),
        continuing("NextLocalTrainIntent", attrs, trainStation="Maynooth"),
        continuing("NextLocalTrainIntent", attrs, trainDirection="Maynooth"),
        continuing("AMAZON.FallbackIntent", attrs),
        continuing("NextBusIntent", attrs),
    ):
        resp = app.handler(follow, None)
        text = assert_not_silent(resp)
        assert "Fairfield" not in text
        name = follow["request"]["intent"]["name"]
        if name in ("AMAZON.FallbackIntent", "NextBusIntent"):
            assert_open_without_dialog(resp, pending_action="set_favourite")
            continue
        assert "Which station?" not in text, text
        assert "haven't set a favourite" not in text, text
        assert "Which direction at Maynooth" in text
        assert_open_without_dialog(
            resp, pending_station="Maynooth", pending_action="set_favourite",
        )


def test_drumcondra_in_direction_slot_asks_direction_not_which_station(wired):
    """Device: 'or local train' then 'drumcondra' then 'drumcondra' again.

    Drumcondra is both a station and a LOCAL_TRAIN_DIRECTION destination, so
    Alexa often fills trainDirection and not trainStation. That used to ask
    'Which station?', clear set-favourite, and replay the no-favourite prompt.
    """
    first = app.handler(intent("NextLocalTrainIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    mid = app.handler(continuing(
        "NextLocalTrainIntent", attrs, trainDirection="drumcondra",
    ), None)
    text = assert_not_silent(mid)
    assert "Which station?" not in text, text
    assert "haven't set a favourite" not in text, text
    assert "Which direction at Drumcondra" in text
    mid_attrs = assert_open_without_dialog(
        mid, pending_station="Drumcondra", pending_action="set_favourite",
    )
    again = app.handler(continuing(
        "NextLocalTrainIntent", mid_attrs, trainDirection="drumcondra",
    ), None)
    again_text = assert_not_silent(again)
    assert "Which station?" not in again_text, again_text
    assert "haven't set a favourite" not in again_text, again_text
    assert "Which direction at Drumcondra" in again_text
    done = app.handler(continuing(
        "SetFavouriteLocalTrainIntent", mid_attrs,
        trainStation="Drumcondra", trainDirection="Connolly",
    ), None)
    assert "favourite local train stop is now" in speech(done)
    assert "Drumcondra" in speech(done)
    assert "Connolly" in speech(done) or "eastbound" in speech(done)


def test_leftover_set_favourite_from_query_gives_times_not_save(wired):
    """Leftover set-favourite + 'from Maynooth eastbound' used to save the stop."""
    first = app.handler(intent("NextLocalTrainIntent"), None)
    attrs = assert_open_without_dialog(first, pending_action="set_favourite")
    for follow in (
        continuing("NextLocalTrainIntent", attrs,
                   trainStation="Maynooth", trainDirection="eastbound"),
        continuing("NextLocalTrainQueryIntent", attrs, trainQuery="from Maynooth eastbound"),
        continuing("SetFavouriteLocalTrainQueryIntent", attrs,
                   trainQuery="from Maynooth eastbound"),
    ):
        wired.favourites.clear()
        resp = app.handler(follow, None)
        text = assert_not_silent(resp)
        assert "favourite" not in text.lower(), text
        assert "At Maynooth" in text
        got = speech(app.handler(intent("GetFavouriteLocalTrainIntent"), None))
        assert "haven't set a favourite" in got


def test_going_east_resolves_as_eastbound():
    resp = app.handler(intent(
        "NextLocalTrainIntent", trainStation="Broombridge", trainDirection="going east",
    ), None)
    text = assert_not_silent(resp)
    assert "Which direction" not in text
    assert "At Broombridge" in text


def test_nortbound_typo_resolves_as_northbound():
    resp = app.handler(intent("NextDartIntent", dartStation="clontarf road nortbound"), None)
    text = assert_not_silent(resp)
    assert "don't know" not in text
    assert "Clontarf" in text
    assert "Howth" in text
    assert "Bray" not in text
