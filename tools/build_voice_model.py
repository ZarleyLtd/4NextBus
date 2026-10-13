"""Merge bus intents with LUAS / Dart / local-train types and samples.

Reads sibling interaction models for station/direction values when present,
or builds catalogs from a local GTFS extract. Writes
skill-package/interactionModels/custom/en-GB.json without dropping bus samples.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "skill-package" / "interactionModels" / "custom" / "en-GB.json"
SIBLINGS = {
    "luas": Path(r"C:\CursorSites\4NextTram\skill-package\interactionModels\custom\en-GB.json"),
    "dart": Path(r"C:\CursorSites\4NextDart\skill-package\interactionModels\custom\en-GB.json"),
    "train": Path(r"C:\CursorSites\4NextLocalTrain\skill-package\interactionModels\custom\en-GB.json"),
}

LUAS_WORDS = ["LUAS", "Lewis", "Louis", "Lucas", "loos"]
DART_WORDS = ["Dart"]
TRAIN_WORDS = ["local train"]

# Do not add '{station} {direction}' here. That sample lets Next* steal a
# set-favourite follow-up such as 'Pearse southbound' / 'Maynooth westbound'.
NEXT_TAILS = [
    "",
    "from {station} {direction}",
    "from {station} towards {direction}",
    "from {station} toward {direction}",
    "from {station} to {direction}",
    "from {station}",
    "from my favourite stop",
    "from my stop",
    "for my stop",
]

QUERY_TAILS = [
    "from {query}",
    "for {query}",
]

SET_TAILS = [
    "to set my favourite stop to {station} {direction}",
    "to set my favourite stop to {station}",
    "to set my favourite stop",
    "set my favourite stop to {station} {direction}",
    "set my favourite stop to {station}",
    "set my favourite stop",
    "to set my favorite stop to {station} {direction}",
    "to set my favorite stop to {station}",
    "to set my favorite stop",
    "set my favorite stop to {station} {direction}",
    "set my favorite stop to {station}",
    "set my favorite stop",
    "change my favourite stop to {station} {direction}",
    "change my favourite stop to {station}",
    "change my favorite stop to {station} {direction}",
    "change my favorite stop to {station}",
]

SET_NOUN = [
    "to set my favourite {noun} stop to {station} {direction}",
    "to set my favourite {noun} stop to {station}",
    "to set my favourite {noun} stop",
    "set my favourite {noun} stop to {station} {direction}",
    "set my favourite {noun} stop to {station}",
    "set my favourite {noun} stop",
    "to set my favorite {noun} stop to {station} {direction}",
    "to set my favorite {noun} stop to {station}",
    "to set my favorite {noun} stop",
    "set my favorite {noun} stop to {station} {direction}",
    "set my favorite {noun} stop to {station}",
    "set my favorite {noun} stop",
    "change my favourite {noun} stop to {station} {direction}",
    "change my favorite {noun} stop to {station} {direction}",
]

NEXT_FOLLOW = [
    "{direction}",
    "going {direction}",
    "heading {direction}",
    "towards {direction}",
    "toward {direction}",
    "{direction} towards {station}",
    "{direction} toward {station}",
]

# Bare follow-ups after an open ask (no 'or Dart' prefix). Required so
# 'Pearse southbound' / 'Maynooth' / 'southbound' match SetFavourite*.
SET_FOLLOW = [
    "{station} {direction}",
    "{station}",
    "{direction}",
    "going {direction}",
    "heading {direction}",
    "towards {direction}",
    "toward {direction}",
]

GET_OR = [
    "for my favourite stop",
    "what is my favourite stop",
    "what's my favourite stop",
    "for my favorite stop",
    "what is my favorite stop",
]

GET_NOUN = [
    "for my favourite {noun} stop",
    "what is my favourite {noun} stop",
    "what's my favourite {noun} stop",
    "what is my favourite {noun} stop number",
    "which {noun} stop is my favourite",
    "for my favorite {noun} stop",
    "what is my favorite {noun} stop",
]

CLEAR_OR = [
    "forget my favourite stop",
    "unset my favourite stop",
    "clear my favourite stop",
    "forget my favorite stop",
    "unset my favorite stop",
    "clear my favorite stop",
    "delete my favourite stop",
    "remove my favourite stop",
    "forget my stop",
    "unset my stop",
]

CLEAR_NOUN = [
    "forget my favourite {noun} stop",
    "unset my favourite {noun} stop",
    "clear my favourite {noun} stop",
    "forget my favorite {noun} stop",
    "unset my favorite {noun} stop",
    "clear my favorite {noun} stop",
    "delete my favourite {noun} stop",
    "remove my favourite {noun} stop",
]

CLEAR_BUS_SAMPLES = [
    "forget my favourite stop",
    "unset my favourite stop",
    "clear my favourite stop",
    "forget my favorite stop",
    "unset my favorite stop",
    "clear my favorite stop",
    "delete my favourite stop",
    "remove my favourite stop",
    "forget my stop",
    "unset my stop",
    "forget my favourite bus stop",
    "unset my favourite bus stop",
    "clear my favourite bus stop",
]

CLEAR_ALL_SAMPLES = [
    "forget all my favourite stops",
    "unset all my favourite stops",
    "clear all my favourite stops",
    "forget all my favorites",
    "forget all my favourites",
    "unset all my favourites",
    "clear all my favourites",
    "forget every favourite stop",
    "unset every favourite stop",
    "forget all favourites",
]


def or_samples(words: list[str], tails: list[str]) -> list[str]:
    out = []
    for word in words:
        for tail in tails:
            out.append(f"or {word} {tail}".strip())
    return out


def noun_samples(words: list[str], templates: list[str]) -> list[str]:
    return [t.replace("{noun}", word) for word in words for t in templates]


def bind_slots(samples: list[str], station_slot: str, direction_slot: str, query_slot: str = "query") -> list[str]:
    return [
        s.replace("{station}", "{" + station_slot + "}")
         .replace("{direction}", "{" + direction_slot + "}")
         .replace("{query}", "{" + query_slot + "}")
        for s in samples
    ]


def unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_types(path: Path, station_type: str, direction_type: str) -> tuple[list, list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    types = {t["name"]: t["values"] for t in data["interactionModel"]["languageModel"]["types"]}
    return types[station_type], types[direction_type]


def fallback_types(mode: str) -> tuple[list, list]:
    cache = ROOT / ".cache" / "gtfs"
    if not ((cache / "stops.txt").exists() and (cache / "stop_times.txt").exists()):
        return [], []
    from ingest.gtfs_static import GtfsStatic
    gtfs = GtfsStatic(cache)
    if mode == "luas":
        from src.modes.luas.stations import Station, alexa_direction_values, alexa_station_values
        rows = [Station.from_dict(r) for r in gtfs.luas_station_catalog()]
        return alexa_station_values(rows), alexa_direction_values()
    if mode == "dart":
        from src.modes.dart.stations import Station, alexa_direction_values, alexa_station_values
        rows = [Station.from_dict(r) for r in gtfs.dart_station_catalog()]
        return alexa_station_values(rows), alexa_direction_values()
    from src.modes.train.stations import Station, alexa_direction_values, alexa_station_values
    rows = [Station.from_dict(r) for r in gtfs.train_station_catalog()]
    return alexa_station_values(rows), alexa_direction_values()


CARDINAL_SYNS = {
    "northbound": [
        "north", "north bound", "going north", "heading north", "going northbound",
        "heading northbound", "northward", "northwards", "to the north",
        "nortbound", "norbound",
    ],
    "southbound": [
        "south", "south bound", "going south", "heading south", "going southbound",
        "heading southbound", "southward", "southwards", "to the south",
    ],
    "eastbound": [
        "east", "east bound", "going east", "heading east", "going eastbound",
        "heading eastbound", "eastward", "eastwards", "to the east",
    ],
    "westbound": [
        "west", "west bound", "going west", "heading west", "going westbound",
        "heading westbound", "westward", "westwards", "to the west",
    ],
}


def ensure_cardinal_synonyms(direction_values: list[dict]) -> list[dict]:
    by_name = {v["name"]["value"]: v for v in direction_values}
    extras = []
    for canonical, syns in CARDINAL_SYNS.items():
        if canonical not in by_name:
            extras.append({"name": {"value": canonical, "synonyms": list(syns)}})
            continue
        existing = by_name[canonical]["name"].setdefault("synonyms", [])
        have = {s.casefold() for s in existing}
        have.add(canonical.casefold())
        for s in syns:
            if s.casefold() not in have:
                existing.append(s)
                have.add(s.casefold())
    return extras + direction_values


def types_for(mode: str, station_type: str, direction_type: str) -> tuple[list, list]:
    sibling = SIBLINGS[mode]
    if sibling.exists():
        stations, directions = load_types(sibling, station_type, direction_type)
    else:
        stations, directions = fallback_types(mode)
    return stations, ensure_cardinal_synonyms(directions)


def intent(name: str, slots: list[dict], samples: list[str]) -> dict:
    return {"name": name, "slots": slots, "samples": unique(samples)}


def dialog_intent(name: str, station_slot: str, direction_slot: str,
                  station_type: str, direction_type: str,
                  elicit_station: str, elicit_direction: str) -> dict:
    return {
        "name": name,
        "confirmationRequired": False,
        "prompts": {},
        "slots": [
            {
                "name": station_slot, "type": station_type,
                "confirmationRequired": False, "elicitationRequired": False,
                "prompts": {"elicitation": elicit_station},
            },
            {
                "name": direction_slot, "type": direction_type,
                "confirmationRequired": False, "elicitationRequired": False,
                "prompts": {"elicitation": elicit_direction},
            },
        ],
    }


def dialog_query_intent(name: str, query_slot: str, elicit_id: str) -> dict:
    return {
        "name": name,
        "confirmationRequired": False,
        "prompts": {},
        "slots": [{
            "name": query_slot, "type": "AMAZON.SearchQuery",
            "confirmationRequired": False, "elicitationRequired": False,
            "prompts": {"elicitation": elicit_id},
        }],
    }


def mode_block(key: str, words: list[str], noun_words: list[str],
               next_name: str, query_name: str, set_name: str, set_query_name: str,
               get_name: str, clear_name: str,
               station_type: str, direction_type: str,
               station_slot: str, direction_slot: str, query_slot: str,
               ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    station_values, direction_values = types_for(key, station_type, direction_type)
    slots = [
        {"name": station_slot, "type": station_type},
        {"name": direction_slot, "type": direction_type},
    ]
    intents = [
        intent(next_name, slots, bind_slots(
            or_samples(words, NEXT_TAILS) + NEXT_FOLLOW, station_slot, direction_slot, query_slot)),
        intent(query_name, [{"name": query_slot, "type": "AMAZON.SearchQuery"}],
               bind_slots(or_samples(words, QUERY_TAILS), station_slot, direction_slot, query_slot)),
        intent(set_name, slots, bind_slots(
            or_samples(words, SET_TAILS) + noun_samples(noun_words, SET_NOUN) + SET_FOLLOW,
            station_slot, direction_slot, query_slot)),
        intent(set_query_name, [{"name": query_slot, "type": "AMAZON.SearchQuery"}],
               bind_slots(
                   or_samples(words, [
                       "to set my favourite stop to {query}",
                       "set my favourite stop to {query}",
                       "to set my favorite stop to {query}",
                       "set my favorite stop to {query}",
                   ])
                   + noun_samples(noun_words, [
                       "to set my favourite {noun} stop to {query}",
                       "set my favourite {noun} stop to {query}",
                       "to set my favorite {noun} stop to {query}",
                       "set my favorite {noun} stop to {query}",
                   ]),
                   station_slot, direction_slot, query_slot)),
        intent(get_name, [], or_samples(words, GET_OR) + noun_samples(noun_words, GET_NOUN)),
        intent(clear_name, [], or_samples(words, CLEAR_OR) + noun_samples(noun_words, CLEAR_NOUN)),
    ]
    types = [
        {"name": station_type, "values": station_values},
        {"name": direction_type, "values": direction_values},
    ]
    elicit_s = f"Elicit.Slot.{station_slot}"
    elicit_d = f"Elicit.Slot.{direction_slot}"
    elicit_q = f"Elicit.Slot.{query_slot}"
    dialog = [
        dialog_intent(next_name, station_slot, direction_slot, station_type, direction_type, elicit_s, elicit_d),
        dialog_intent(set_name, station_slot, direction_slot, station_type, direction_type, elicit_s, elicit_d),
        dialog_query_intent(query_name, query_slot, elicit_q),
        dialog_query_intent(set_query_name, query_slot, elicit_q),
    ]
    prompts = [
        {"id": elicit_s, "variations": [
            {"type": "PlainText", "value": "Which stop?"},
            {"type": "PlainText", "value": "What's the name of the stop?"},
        ]},
        {"id": elicit_d, "variations": [
            {"type": "PlainText", "value": "Which direction?"},
            {"type": "PlainText", "value": "Northbound, southbound, towards the city, or towards a terminus?"},
        ]},
        {"id": elicit_q, "variations": [
            {"type": "PlainText", "value": "Say the stop name and direction."},
            {"type": "PlainText", "value": "Which direction?"},
        ]},
    ]
    return intents, types, dialog, prompts


def main() -> None:
    bus = json.loads(OUT.read_text(encoding="utf-8"))
    lm = bus["interactionModel"]["languageModel"]
    dialog = bus["interactionModel"]["dialog"]
    prompts = bus["interactionModel"]["prompts"]

    extras = [
        mode_block("luas", LUAS_WORDS, LUAS_WORDS,
                   "NextLuasIntent", "NextLuasQueryIntent",
                   "SetFavouriteLuasIntent", "SetFavouriteLuasQueryIntent",
                   "GetFavouriteLuasIntent", "ClearFavouriteLuasIntent",
                   "LUAS_STATION", "LUAS_DIRECTION",
                   "luasStation", "luasDirection", "luasQuery"),
        mode_block("dart", DART_WORDS, DART_WORDS,
                   "NextDartIntent", "NextDartQueryIntent",
                   "SetFavouriteDartIntent", "SetFavouriteDartQueryIntent",
                   "GetFavouriteDartIntent", "ClearFavouriteDartIntent",
                   "DART_STATION", "DART_DIRECTION",
                   "dartStation", "dartDirection", "dartQuery"),
        mode_block("train", TRAIN_WORDS, ["local train"],
                   "NextLocalTrainIntent", "NextLocalTrainQueryIntent",
                   "SetFavouriteLocalTrainIntent", "SetFavouriteLocalTrainQueryIntent",
                   "GetFavouriteLocalTrainIntent", "ClearFavouriteLocalTrainIntent",
                   "LOCAL_TRAIN_STATION", "LOCAL_TRAIN_DIRECTION",
                   "trainStation", "trainDirection", "trainQuery"),
    ]

    # Keep built-ins at the end.
    builtins = [i for i in lm["intents"] if i["name"].startswith("AMAZON.")]
    custom = [i for i in lm["intents"] if not i["name"].startswith("AMAZON.")]
    for extra in (
        intent("ClearFavouriteStopIntent", [], CLEAR_BUS_SAMPLES),
        intent("ClearAllFavouritesIntent", [], CLEAR_ALL_SAMPLES),
    ):
        custom = [c for c in custom if c["name"] != extra["name"]]
        custom.append(extra)
    custom_names = {i["name"] for i in custom}
    for intents, types, dlog, pr in extras:
        for it in intents:
            if it["name"] in custom_names:
                custom = [c for c in custom if c["name"] != it["name"]]
            custom.append(it)
        existing_types = {t["name"] for t in lm["types"]}
        for t in types:
            if t["name"] in existing_types:
                lm["types"] = [x for x in lm["types"] if x["name"] != t["name"]]
            lm["types"].append(t)
        existing_dialog = {d["name"] for d in dialog["intents"]}
        for d in dlog:
            if d["name"] in existing_dialog:
                dialog["intents"] = [x for x in dialog["intents"] if x["name"] != d["name"]]
            dialog["intents"].append(d)
        existing_prompts = {p["id"] for p in prompts}
        for p in pr:
            if p["id"] in existing_prompts:
                prompts[:] = [x for x in prompts if x["id"] != p["id"]]
            prompts.append(p)

    lm["intents"] = custom + builtins
    OUT.write_text(json.dumps(bus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n_types = {t["name"]: len(t.get("values") or []) for t in lm["types"]}
    print(f"wrote {OUT} types={n_types} intents={len(lm['intents'])}")


if __name__ == "__main__":
    main()
