"""Static contracts for the interaction model.

These checks exist because handler tests inject already-filled slots. They
cannot see whether Alexa will still be in the skill when the user says
'Maynooth' or 'Pearse southbound'. The samples and the Lambda dialog
directives together decide that.

Run: pytest tests/test_voice_model_contracts.py
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "skill-package" / "interactionModels" / "custom" / "en-GB.json"
NAMED = ROOT / "src" / "skill" / "named.py"

_spec = importlib.util.spec_from_file_location(
    "build_voice_model", ROOT / "tools" / "build_voice_model.py")
vm = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(vm)

MODES = (
    ("NextLuasIntent", "SetFavouriteLuasIntent", "NextLuasQueryIntent",
     "SetFavouriteLuasQueryIntent", "luasStation", "luasDirection", "luasQuery"),
    ("NextDartIntent", "SetFavouriteDartIntent", "NextDartQueryIntent",
     "SetFavouriteDartQueryIntent", "dartStation", "dartDirection", "dartQuery"),
    ("NextLocalTrainIntent", "SetFavouriteLocalTrainIntent", "NextLocalTrainQueryIntent",
     "SetFavouriteLocalTrainQueryIntent", "trainStation", "trainDirection", "trainQuery"),
)

# 'or Dart {dartStation} {dartDirection}' with no 'from' — Alexa then routes a
# set-favourite follow-up of 'Pearse southbound' to NextDartIntent.
# 'or Dart from {dartStation} {dartDirection}' is a genuine times query.
_GLUED = re.compile(
    r"^(?:or\s+(?:LUAS|Lewis|Louis|Lucas|loos|Dart|local train)\s+)?"
    r"\{(luasStation|dartStation|trainStation)\}(?:\s+towards?)?\s+"
    r"\{(luasDirection|dartDirection|trainDirection)\}$",
    re.I,
)


def _model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def _intents(data: dict) -> dict[str, dict]:
    return {i["name"]: i for i in data["interactionModel"]["languageModel"]["intents"]}


def _samples(data: dict, name: str) -> list[str]:
    return list(_intents(data)[name].get("samples") or [])


def test_named_handlers_must_not_elicit_a_slot():
    """src/skill/named.py once sent Dialog.ElicitSlot; that caused device silence."""
    src = NAMED.read_text(encoding="utf-8")
    assert "ElicitSlotDirective" not in src
    assert "elicit_search_query" not in src
    assert "add_directive" not in src


def test_builder_next_tails_do_not_include_glued_station_direction():
    assert "{station} {direction}" not in vm.NEXT_TAILS
    assert "{station} towards {direction}" not in vm.NEXT_TAILS
    for tail in vm.NEXT_TAILS:
        if "{station}" in tail and "{direction}" in tail:
            assert tail.strip().startswith("from "), tail


def test_builder_set_follow_covers_station_only_glued_and_direction_only():
    for needed in ("{station} {direction}", "{station}", "{direction}"):
        assert needed in vm.SET_FOLLOW, needed


def test_builder_next_follow_covers_direction_only():
    assert "{direction}" in vm.NEXT_FOLLOW


def test_builder_search_query_tails_have_carrier_phrases():
    """Alexa rejects SearchQuery samples that are only a slot."""
    assert "{query}" not in vm.QUERY_TAILS
    for tail in vm.QUERY_TAILS:
        assert tail.strip() != "{query}"
        assert "{query}" in tail


@pytest.mark.parametrize("next_name,set_name,next_query,set_query,station,direction,query", MODES)
def test_published_next_intents_do_not_claim_glued_follow_ups(
    next_name, set_name, next_query, set_query, station, direction, query,
):
    data = _model()
    stolen = [s for s in _samples(data, next_name) if _GLUED.match(s)]
    assert stolen == [], f"{next_name} would steal set-favourite follow-ups: {stolen}"
    bare_query = [s for s in _samples(data, next_query) if s.strip() == "{" + query + "}"]
    assert bare_query == [], f"{next_query} bare query would steal follow-ups: {bare_query}"


@pytest.mark.parametrize("next_name,set_name,next_query,set_query,station,direction,query", MODES)
def test_published_set_intents_claim_device_follow_ups(
    next_name, set_name, next_query, set_query, station, direction, query,
):
    data = _model()
    set_samples = _samples(data, set_name)
    assert "{" + station + "} {" + direction + "}" in set_samples
    assert "{" + station + "}" in set_samples
    assert "{" + direction + "}" in set_samples
    query_samples = _samples(data, set_query)
    bare = "{" + query + "}"
    assert bare not in query_samples, (
        f"{set_query} cannot use a slot-only SearchQuery sample; Alexa rejects it"
    )
    assert any(bare in s and s.strip() != bare for s in query_samples)


@pytest.mark.parametrize("next_name,set_name,next_query,set_query,station,direction,query", MODES)
def test_published_next_intents_claim_direction_only_follow_ups(
    next_name, set_name, next_query, set_query, station, direction, query,
):
    data = _model()
    assert "{" + direction + "}" in _samples(data, next_name)


def test_search_query_samples_are_not_slot_only():
    """Alexa: 'Sample utterance with phrase types cannot consist of only slots.'"""
    data = _model()
    bad = []
    for intent in data["interactionModel"]["languageModel"]["intents"]:
        query_slots = [
            s["name"] for s in intent.get("slots") or []
            if s.get("type") == "AMAZON.SearchQuery"
        ]
        for sample in intent.get("samples") or []:
            stripped = sample.strip()
            if any(stripped == "{" + n + "}" for n in query_slots):
                bad.append(f"{intent['name']}: {sample!r}")
    assert bad == [], bad


def test_commuter_stops_also_appear_as_direction_values():
    """Drumcondra is a station and a 'towards Drumcondra' direction.

    Alexa may copy 'drumcondra' into trainDirection. Handlers must treat that
    as the station during set-favourite, not as a times query with no station.
    """
    data = _model()
    types = {t["name"]: t for t in data["interactionModel"]["languageModel"]["types"]}
    stations = {v["name"]["value"] for v in types["LOCAL_TRAIN_STATION"]["values"]}
    directions = {v["name"]["value"] for v in types["LOCAL_TRAIN_DIRECTION"]["values"]}
    overlap = stations & directions
    assert "Drumcondra" in overlap
    assert "Maynooth" in overlap


def test_slot_names_are_unique_per_mode():
    """en-IN rejected reused slot names across intents; keep mode-prefixed slots."""
    data = _model()
    slots = {}
    for intent in data["interactionModel"]["languageModel"]["intents"]:
        for slot in intent.get("slots") or []:
            slots.setdefault(slot["name"], set()).add(intent["name"])
    for name in ("luasStation", "dartStation", "trainStation",
                 "luasDirection", "dartDirection", "trainDirection",
                 "luasQuery", "dartQuery", "trainQuery"):
        assert name in slots, name
    shared = {name: sorted(owners) for name, owners in slots.items()
              if name in ("station", "direction", "query")}
    assert shared == {}, f"generic slot names collide across modes: {shared}"
