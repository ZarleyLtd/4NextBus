"""Alexa handlers for LUAS, DART, and local-train phrases inside 4NextBus."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import is_intent_name
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard

from src.common.speech import LUAS as SAY_LUAS
from src.modes.luas.stations import split_station_and_direction as luas_split

log = logging.getLogger(__name__)

PENDING_SET_FAV = "set_favourite"
PENDING_NEED_DIR = "need_direction"
PENDING_ACTIONS = frozenset({PENDING_SET_FAV, PENDING_NEED_DIR})
_CARDINALS = frozenset({"northbound", "southbound", "eastbound", "westbound", "city"})
_DIR_UTTER = re.compile(
    r"^(?:going|heading|towards?|north|south|east|west)",
    re.I,
)
_SET_FAV = re.compile(
    r"(?:^|.*\b)(?:to\s+)?(?:set|change|save|remember)\s+my\s+favou?rite"
    r"(?:\s+\w+(?:\s+\w+)?)?\s+stop(?:\s+to\s+(?P<rest>.+))?$",
    re.I,
)
_FROM_QUERY = re.compile(r"^\s*from\s+\S", re.I)


def looks_like_set_favourite(text: str | None) -> bool:
    return bool(text and _SET_FAV.search(text.strip()))


def station_after_set_favourite(text: str | None) -> str | None:
    if not text:
        return None
    m = _SET_FAV.search(text.strip())
    rest = (m.group("rest") or "").strip() if m else ""
    return rest or None


def spoken_mode(spec: "ModeSpec") -> str:
    return SAY_LUAS if spec.key == "luas" else spec.label


@dataclass(frozen=True)
class ModeSpec:
    key: str
    label: str  # "LUAS", "DART", "local train"
    next_intent: str
    next_query_intent: str
    set_intent: str
    set_query_intent: str
    get_intent: str
    clear_intent: str
    ask_station: str
    ask_direction: str
    ask_favourite: str
    no_favourite: str
    miss_station: str
    after_save: str
    station_slot: str
    direction_slot: str
    query_slot: str
    split: Callable[[str | None, str | None], tuple[str | None, str | None]]


LUAS = ModeSpec(
    key="luas",
    label="LUAS",
    next_intent="NextLuasIntent",
    next_query_intent="NextLuasQueryIntent",
    set_intent="SetFavouriteLuasIntent",
    set_query_intent="SetFavouriteLuasQueryIntent",
    get_intent="GetFavouriteLuasIntent",
    clear_intent="ClearFavouriteLuasIntent",
    ask_station=f"Which {SAY_LUAS} stop?",
    ask_direction="Which direction?",
    ask_favourite="Say the stop name and direction, for example Dundrum southbound.",
    no_favourite=(f"You haven't set a favourite {SAY_LUAS} stop yet. Tell me the stop name and direction, "
                  "for example, Dundrum southbound."),
    miss_station=(f"I didn't catch which {SAY_LUAS} stop. Say the stop name and direction, "
                  "for example, Dundrum southbound."),
    after_save=f"From now on, just ask me for the next {SAY_LUAS}.",
    station_slot="luasStation",
    direction_slot="luasDirection",
    query_slot="luasQuery",
    split=luas_split,
)


def dart_split(station, direction):
    from src.modes.dart.stations import split_station_and_direction
    return split_station_and_direction(station, direction)


def train_split(station, direction):
    from src.modes.train.stations import split_station_and_direction
    return split_station_and_direction(station, direction)


DART = ModeSpec(
    key="dart",
    label="Dart",
    next_intent="NextDartIntent",
    next_query_intent="NextDartQueryIntent",
    set_intent="SetFavouriteDartIntent",
    set_query_intent="SetFavouriteDartQueryIntent",
    get_intent="GetFavouriteDartIntent",
    clear_intent="ClearFavouriteDartIntent",
    ask_station="Which DART station?",
    ask_direction="Which direction?",
    ask_favourite="Say the station name and direction, for example Pearse southbound.",
    no_favourite=("You haven't set a favourite Dart stop yet. Tell me the station name and direction, "
                  "for example, Pearse southbound."),
    miss_station="I didn't catch which station. Say the station name and direction, for example, Pearse southbound.",
    after_save="From now on, just ask me for the next Dart.",
    station_slot="dartStation",
    direction_slot="dartDirection",
    query_slot="dartQuery",
    split=dart_split,
)

TRAIN = ModeSpec(
    key="train",
    label="local train",
    next_intent="NextLocalTrainIntent",
    next_query_intent="NextLocalTrainQueryIntent",
    set_intent="SetFavouriteLocalTrainIntent",
    set_query_intent="SetFavouriteLocalTrainQueryIntent",
    get_intent="GetFavouriteLocalTrainIntent",
    clear_intent="ClearFavouriteLocalTrainIntent",
    ask_station="Which station?",
    ask_direction="Which direction?",
    ask_favourite="Say the station name and direction, for example Maynooth westbound.",
    no_favourite=("You haven't set a favourite local train stop yet. Tell me the station name and direction, "
                  "for example, Maynooth westbound."),
    miss_station="I didn't catch which station. Say the station name and direction, for example, Maynooth westbound.",
    after_save="From now on, just ask me for the next local train.",
    station_slot="trainStation",
    direction_slot="trainDirection",
    query_slot="trainQuery",
    split=train_split,
)

SERVICES: dict[str, Callable] = {}


def service_for(spec: ModeSpec):
    return SERVICES[spec.key]()

MODES = (LUAS, DART, TRAIN)


def session_attrs(handler_input: HandlerInput) -> dict:
    return handler_input.attributes_manager.session_attributes


def user_id(handler_input: HandlerInput) -> str:
    return handler_input.request_envelope.context.system.user.user_id


def pending_mode(handler_input: HandlerInput) -> str | None:
    return session_attrs(handler_input).get("pending_mode")


def ask_without_elicit(handler_input: HandlerInput, prompt: str, ask: str | None = None) -> Response:
    text = ask or prompt
    return (handler_input.response_builder
            .speak(prompt).ask(text)
            .set_should_end_session(False)
            .response)


def elicit(handler_input: HandlerInput, prompt: str, slot_name: str, spec: ModeSpec) -> Response:
    return ask_without_elicit(handler_input, prompt, prompt)


def pending_prompt(handler_input: HandlerInput, spec: ModeSpec, prompt: str, *,
                   action: str, station: str | None = None) -> Response:
    """Keep a normal open session. Do not use Dialog.ElicitSlot.

    ElicitSlot on a custom station/direction type drops 'northbound' and
    'Maynooth westbound'. ElicitSlot on AMAZON.SearchQuery also drops
    follow-ups — Alexa leaves the skill (silence, or a Wikipedia answer
    for a place name). Repeating the full spoken prompt in .ask() means a
    device replay is still the question, and SET_FOLLOW samples can match
    'Pearse southbound' / 'Maynooth' as a normal intent.
    """
    attrs = session_attrs(handler_input)
    attrs["pending_action"] = action
    attrs["pending_mode"] = spec.key
    if station:
        attrs["pending_station"] = station
    return ask_without_elicit(handler_input, prompt, prompt)


def intent_name(handler_input: HandlerInput) -> str | None:
    intent = getattr(handler_input.request_envelope.request, "intent", None)
    return getattr(intent, "name", None) if intent else None


def clear_pending(handler_input: HandlerInput) -> None:
    attrs = session_attrs(handler_input)
    attrs.pop("pending_action", None)
    attrs.pop("pending_station", None)
    attrs.pop("pending_mode", None)


def peel_from_query(text: str | None) -> str | None:
    if not text:
        return text
    m = re.match(r"^\s*from\s+(.+)$", text.strip(), re.I)
    return (m.group(1).strip() if m else text) or None


def looks_like_from_query(text: str | None) -> bool:
    return bool(text and _FROM_QUERY.search(text))


def is_direction_only_follow_up(spec: ModeSpec, station: str | None,
                                direction: str | None) -> bool:
    """True when the utterance is just a compass, not a new station query."""
    if not follow_up_direction(spec, station, direction):
        return False
    return not (station and not follow_up_direction(spec, station, None))


def place_and_direction(spec: ModeSpec, station: str | None, direction: str | None,
                        pending_station: str | None = None) -> tuple[str | None, str | None]:
    """Recover a station Alexa stuffed into the direction slot.

    Commuter destinations such as Drumcondra are LOCAL_TRAIN_DIRECTION values,
    so a follow-up of 'drumcondra' often arrives as trainDirection only.
    If we already asked for a direction at a station, keep that station and
    treat the place name as 'towards Drumcondra'.
    """
    if station:
        return station, direction
    if not direction:
        return None, None
    if follow_up_direction(spec, direction, None):
        return None, direction
    if pending_station:
        if pending_station.casefold() == direction.strip().casefold():
            return pending_station, None
        return pending_station, direction
    return direction, None


def is_times_query_during_set_fav(handler_input: HandlerInput, spec: ModeSpec,
                                  station: str | None, direction: str | None) -> bool:
    """A from {station} {direction} next-query, not a set-favourite answer."""
    if looks_like_from_query(station):
        return True
    if is_direction_only_follow_up(spec, station, direction):
        return False
    name = intent_name(handler_input)
    if name not in (spec.next_intent, spec.next_query_intent):
        return False
    place = station and not follow_up_direction(spec, station, None)
    compass = bool(follow_up_direction(spec, None, direction) or (
        direction and follow_up_direction(spec, direction, None)))
    return bool(place and compass)


def elicit_set_favourite(handler_input: HandlerInput, spec: ModeSpec, prompt: str,
                         station: str | None = None) -> Response:
    return pending_prompt(handler_input, spec, prompt, action=PENDING_SET_FAV, station=station)


def respond_with_times(handler_input: HandlerInput, spec: ModeSpec, ref) -> Response:
    result = service_for(spec).next_departures(ref)
    return (handler_input.response_builder
            .speak(result.speech)
            .set_card(SimpleCard(result.card_title, result.card_text))
            .set_should_end_session(True)
            .response)


def ask_for_favourite_stop(handler_input: HandlerInput, spec: ModeSpec, prompt: str) -> Response:
    return elicit_set_favourite(handler_input, spec, prompt)


def save_favourite(handler_input: HandlerInput, spec: ModeSpec,
                   station: str | None, direction: str | None) -> Response:
    log.info("%s set favourite station=%r direction=%r", spec.key, station, direction)
    if looks_like_set_favourite(station):
        station, direction = station_after_set_favourite(station), direction
    if station:
        peeled, extra = spec.split(station, direction)
        station, direction = peeled or station, extra or direction
    if not station:
        return ask_for_favourite_stop(
            handler_input, spec,
            f"Which {spoken_mode(spec)} stop should I save as your favourite?")
    svc = service_for(spec)
    result = svc.resolve(station, direction)
    if result.status == "ok" and result.ref:
        svc.set_favourite(user_id(handler_input), result.ref)
        clear_pending(handler_input)
        speech = (f"Done. Your favourite {spoken_mode(spec)} stop is now {result.ref.spoken_name}. "
                  f"{spec.after_save}")
        return (handler_input.response_builder.speak(speech)
                .set_card(SimpleCard(f"Favourite {spec.label} stop saved", result.ref.spoken_name))
                .set_should_end_session(True).response)
    if result.status in ("need_direction", "bad_direction") and result.elicit:
        peeled, _ = spec.split(station, direction)
        label = result.spoken or peeled
        attrs = session_attrs(handler_input)
        if label:
            attrs["pending_station"] = label
        attrs["pending_action"] = PENDING_SET_FAV
        attrs["pending_mode"] = spec.key
        return elicit_set_favourite(handler_input, spec, result.prompt, station=label)
    session_attrs(handler_input).pop("pending_action", None)
    session_attrs(handler_input).pop("pending_mode", None)
    return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


def handle_resolve(handler_input: HandlerInput, spec: ModeSpec,
                   station: str | None, direction: str | None,
                   no_station_prompt: str, elicit_slots: bool = True) -> Response:
    svc = service_for(spec)
    result = svc.resolve(station, direction)
    if result.status == "ok" and result.ref:
        session_attrs(handler_input).pop("pending_station", None)
        return respond_with_times(handler_input, spec, result.ref)
    if result.status == "need_station":
        if elicit_slots:
            return elicit(handler_input, no_station_prompt, "station", spec)
        return ask_without_elicit(handler_input, no_station_prompt, no_station_prompt)
    if result.status in ("need_direction", "bad_direction") and result.elicit:
        peeled, _ = spec.split(station, direction)
        label = result.spoken or peeled
        attrs = session_attrs(handler_input)
        if label:
            attrs["pending_station"] = label
        attrs["pending_action"] = PENDING_NEED_DIR
        attrs["pending_mode"] = spec.key
        return pending_prompt(handler_input, spec, result.prompt, action=PENDING_NEED_DIR, station=label)
    return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


def handle_next(handler_input: HandlerInput, spec: ModeSpec, station: str | None,
                direction: str | None, elicit_slots: bool = True) -> Response:
    action = session_attrs(handler_input).get("pending_action")
    pending = pending_mode(handler_input)
    if action == PENDING_SET_FAV and (pending == spec.key or pending is None):
        pending_station = session_attrs(handler_input).get("pending_station")
        station, direction = place_and_direction(spec, station, direction, pending_station)
        if is_times_query_during_set_fav(handler_input, spec, station, direction):
            station = peel_from_query(station)
            clear_pending(handler_input)
            return handle_resolve(handler_input, spec, station, direction, spec.ask_station,
                                  elicit_slots)
        return save_favourite(handler_input, spec, station, direction)
    if action == PENDING_NEED_DIR and (pending == spec.key or pending is None):
        direction = follow_up_direction(spec, station, direction)
        station = session_attrs(handler_input).get("pending_station") or station
        if direction:
            session_attrs(handler_input).pop("pending_action", None)
            return handle_resolve(handler_input, spec, station, direction, spec.ask_station, elicit_slots)
        return pending_prompt(
            handler_input, spec, "Sorry, I didn't catch that. " + spec.ask_direction,
            action=PENDING_NEED_DIR, station=station)
    if looks_like_set_favourite(station):
        rest = station_after_set_favourite(station)
        if rest:
            peeled, extra = spec.split(rest, direction)
            return save_favourite(handler_input, spec, peeled, extra or direction)
        return save_favourite(handler_input, spec, None, direction)
    if not station:
        fav = service_for(spec).get_favourite(user_id(handler_input))
        if fav:
            return respond_with_times(handler_input, spec, fav)
        return ask_for_favourite_stop(handler_input, spec, spec.no_favourite)
    return handle_resolve(handler_input, spec, station, direction, spec.ask_station, elicit_slots)


def make_handlers(spec: ModeSpec, slot_value: Callable) -> list[AbstractRequestHandler]:
    class NextHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.next_intent)(handler_input)

        def handle(self, handler_input):
            continued = continue_pending(handler_input, slot_value)
            if continued:
                return continued
            station = (slot_value(handler_input, spec.station_slot)
                       or slot_value(handler_input, "station")
                       or session_attrs(handler_input).get("pending_station"))
            direction = slot_value(handler_input, spec.direction_slot) or slot_value(handler_input, "direction")
            log.info("%s station=%r direction=%r", spec.next_intent, station, direction)
            return handle_next(handler_input, spec, station, direction)

    class NextQueryHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.next_query_intent)(handler_input)

        def handle(self, handler_input):
            continued = continue_pending(handler_input, slot_value)
            if continued:
                return continued
            query = slot_value(handler_input, spec.query_slot) or slot_value(handler_input, "query")
            log.info("%s query=%r", spec.next_query_intent, query)
            return handle_next(handler_input, spec, query, None, elicit_slots=False)

    class SetHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.set_intent)(handler_input)

        def handle(self, handler_input):
            continued = continue_pending(handler_input, slot_value)
            if continued:
                return continued
            station = (slot_value(handler_input, spec.station_slot)
                       or slot_value(handler_input, "station")
                       or session_attrs(handler_input).get("pending_station"))
            direction = slot_value(handler_input, spec.direction_slot) or slot_value(handler_input, "direction")
            return save_favourite(handler_input, spec, station, direction)

    class SetQueryHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.set_query_intent)(handler_input)

        def handle(self, handler_input):
            continued = continue_pending(handler_input, slot_value)
            if continued:
                return continued
            query = slot_value(handler_input, spec.query_slot) or slot_value(handler_input, "query")
            log.info("%s query=%r", spec.set_query_intent, query)
            return save_favourite(handler_input, spec, query, None)

    class GetHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.get_intent)(handler_input)

        def handle(self, handler_input):
            continued = continue_pending(handler_input, slot_value)
            if continued:
                return continued
            fav = service_for(spec).get_favourite(user_id(handler_input))
            if not fav:
                return ask_for_favourite_stop(handler_input, spec, spec.no_favourite)
            speech = f"Your favourite {spoken_mode(spec)} stop is {fav.spoken_name}."
            return handler_input.response_builder.speak(speech).set_should_end_session(True).response

    class ClearHandler(AbstractRequestHandler):
        def can_handle(self, handler_input):
            return is_intent_name(spec.clear_intent)(handler_input)

        def handle(self, handler_input):
            svc = service_for(spec)
            uid = user_id(handler_input)
            # Read the profile row only — do not load the station catalog.
            had = svc.store.get_favourite(uid, spec.key)
            svc.clear_favourite(uid)
            clear_pending(handler_input)
            if had:
                speech = f"I've forgotten your favourite {spoken_mode(spec)} stop."
            else:
                speech = f"You didn't have a favourite {spoken_mode(spec)} stop saved."
            return (handler_input.response_builder.speak(speech)
                    .set_should_end_session(True).response)

    NextHandler.__name__ = f"Next{spec.key.title()}Handler"
    NextQueryHandler.__name__ = f"Next{spec.key.title()}QueryHandler"
    SetHandler.__name__ = f"SetFavourite{spec.key.title()}Handler"
    SetQueryHandler.__name__ = f"SetFavourite{spec.key.title()}QueryHandler"
    GetHandler.__name__ = f"GetFavourite{spec.key.title()}Handler"
    ClearHandler.__name__ = f"ClearFavourite{spec.key.title()}Handler"
    return [ClearHandler(), NextHandler(), NextQueryHandler(), SetHandler(),
            SetQueryHandler(), GetHandler()]


def pending_spec(handler_input: HandlerInput) -> ModeSpec | None:
    if session_attrs(handler_input).get("pending_action") not in PENDING_ACTIONS:
        return None
    key = pending_mode(handler_input)
    return next((m for m in MODES if m.key == key), None)


def collect_named_slots(handler_input: HandlerInput, slot_value: Callable) -> tuple[str | None, str | None]:
    station = None
    direction = None
    for spec in MODES:
        station = station or slot_value(handler_input, spec.station_slot) or slot_value(handler_input, spec.query_slot)
        direction = direction or slot_value(handler_input, spec.direction_slot)
    station = station or slot_value(handler_input, "station") or slot_value(handler_input, "query")
    direction = direction or slot_value(handler_input, "direction")
    return station, direction


def follow_up_direction(spec: ModeSpec, station: str | None, direction: str | None) -> str | None:
    """Treat a compass follow-up stuffed into any slot as the missing direction."""
    for text in (direction, station):
        if not text:
            continue
        _, parsed = spec.split(None, text)
        if parsed in _CARDINALS:
            return parsed
        if parsed and _DIR_UTTER.match(text.strip()):
            return parsed
    return None


def continue_pending(handler_input: HandlerInput, slot_value: Callable) -> Response | None:
    """Keep a station/direction dialog from falling through to the bus favourite."""
    spec = pending_spec(handler_input)
    if not spec:
        return None
    action = session_attrs(handler_input).get("pending_action")
    station, direction = collect_named_slots(handler_input, slot_value)
    log.info("pending %s mode=%s station=%r direction=%r", action, spec.key, station, direction)
    if looks_like_set_favourite(station):
        station = station_after_set_favourite(station)
    pending_station = session_attrs(handler_input).get("pending_station")
    if action == PENDING_SET_FAV:
        station, direction = place_and_direction(spec, station, direction, pending_station)
    if action == PENDING_SET_FAV and is_times_query_during_set_fav(
            handler_input, spec, station, direction):
        station = peel_from_query(station)
        clear_pending(handler_input)
        return handle_resolve(handler_input, spec, station, direction, spec.ask_station,
                              elicit_slots=False)
    if action == PENDING_NEED_DIR:
        direction = follow_up_direction(spec, station, direction)
        station = pending_station or station
        if direction:
            session_attrs(handler_input).pop("pending_action", None)
            return handle_resolve(handler_input, spec, station, direction, spec.ask_station, elicit_slots=False)
        return pending_prompt(
            handler_input, spec, "Sorry, I didn't catch that. " + spec.ask_direction,
            action=PENDING_NEED_DIR, station=station)
    coerced = follow_up_direction(spec, station, direction)
    if coerced:
        if station and follow_up_direction(spec, station, None):
            station = pending_station
        direction = coerced
    if not station and direction:
        station = pending_station
    if station or direction:
        return save_favourite(handler_input, spec, station, direction)
    if pending_station:
        return elicit_set_favourite(
            handler_input, spec, "Sorry, I didn't catch that. " + spec.ask_direction, station=pending_station)
    return ask_for_favourite_stop(handler_input, spec, "Sorry, I didn't catch that. " + spec.ask_favourite)


def redirect_if_pending(handler_input: HandlerInput, slot_value: Callable) -> Response | None:
    return continue_pending(handler_input, slot_value)


def handle_fallback_pending(handler_input: HandlerInput, slot_value: Callable) -> Response | None:
    return continue_pending(handler_input, slot_value)
