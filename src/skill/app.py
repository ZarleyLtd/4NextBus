"""Alexa skill Lambda handler for 4NextBus (invocation name: "four next bus")."""
from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.dialog import ElicitSlotDirective
from ask_sdk_model.ui import SimpleCard

from src.common import config
from src.common.rt_cache import RealtimeCache
from src.common.speech import LUAS as SAY_LUAS, LUASES
from src.common.store import Store
from src.modes.dart.service import DartService
from src.modes.luas.service import LuasService
from src.modes.train.service import LocalTrainService
from src.skill import named
from src.skill.service import BusService, StopRef, TimetableNotLoaded

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)

# One service per container (warm invocations reuse the caches).
_service: BusService | None = None
_luas: LuasService | None = None
_dart: DartService | None = None
_train: LocalTrainService | None = None
_store: Store | None = None
_realtime: RealtimeCache | None = None


def _backend() -> tuple[Store, RealtimeCache]:
    global _store, _realtime
    if _store is None:
        _store = Store(config.TABLE_NAME, config.REGION)
        _realtime = RealtimeCache(_store, config.nta_api_key())
    return _store, _realtime


def service() -> BusService:
    global _service
    if _service is None:
        store, rt = _backend()
        _service = BusService(store, rt)
    return _service


def luas_service() -> LuasService:
    global _luas
    if _luas is None:
        store, rt = _backend()
        _luas = LuasService(store, rt)
    return _luas


def dart_service() -> DartService:
    global _dart
    if _dart is None:
        store, rt = _backend()
        _dart = DartService(store, rt)
    return _dart


def train_service() -> LocalTrainService:
    global _train
    if _train is None:
        store, rt = _backend()
        _train = LocalTrainService(store, rt)
    return _train


named.SERVICES["luas"] = luas_service
named.SERVICES["dart"] = dart_service
named.SERVICES["train"] = train_service


# ---- speech fragments --------------------------------------------------------------------

HELP = (f"I can tell you the next Dublin buses, {LUASES}, DART trains, or local commuter trains. "
        "For a bus, say from stop followed by the number on the pole, for example, from stop 184. "
        f"For {SAY_LUAS}, say or LUAS from Dundrum southbound. "
        "For Dart, say or Dart from Pearse southbound. "
        "For a local train, say or local train from Maynooth westbound. "
        "To save a favourite, say set my favourite stop to and a bus number, "
        f"or or LUAS to set my favourite {SAY_LUAS} stop to Dundrum southbound. "
        "To forget a favourite, say forget my favourite stop, or or Dart forget my favourite Dart stop. "
        "To forget all of them, say forget all my favourite stops. What would you like?")
NO_FAVOURITE = ("You haven't set a favourite stop yet. Say, set my favourite stop to, followed by the "
                "number on your bus stop pole.")
ASK_STOP = "Which stop number?"
FORGOTTEN = "I've forgotten your favourite stop."
NO_FAVOURITE_TO_FORGET = "You didn't have a favourite stop saved."
FORGOTTEN_ALL = "I've forgotten all your favourite stops."
ERROR = "Sorry, I had trouble getting the times. Please try again in a moment."
NOT_READY = "Sorry, the timetable isn't loaded yet. Please try again later."


def unknown_stop(code: str) -> str:
    return f"I couldn't find stop number {code}. Check the number on the bus stop pole and try again."


def user_id(handler_input: HandlerInput) -> str:
    return handler_input.request_envelope.context.system.user.user_id


def slot_value(handler_input: HandlerInput, name: str) -> str | None:
    """Spoken slot text, including slotValue payloads Alexa sometimes sends instead of value."""
    intent = getattr(handler_input.request_envelope.request, "intent", None)
    slots = getattr(intent, "slots", None) or {}
    slot = slots.get(name)
    if not slot:
        return None
    candidates: list[str] = []

    def _add(raw: str | None) -> None:
        if raw and raw != "?":
            text = str(raw).strip()
            if text:
                candidates.append(text)

    _add(getattr(slot, "value", None))
    sv = getattr(slot, "slot_value", None)
    _add(getattr(sv, "value", None) if sv is not None else None)
    for item in getattr(sv, "values", None) or []:
        _add(getattr(item, "value", None))
        inner = getattr(item, "value", None)
        _add(getattr(inner, "value", None) if inner is not None and not isinstance(inner, str) else None)

    sources = [getattr(slot, "resolutions", None)]
    if sv is not None:
        sources.append(getattr(sv, "resolutions", None))
    for resolutions in sources:
        authorities = getattr(resolutions, "resolutions_per_authority", None) if resolutions else None
        for auth in authorities or []:
            status = getattr(getattr(auth, "status", None), "code", None)
            values = getattr(auth, "values", None) or []
            if str(status).endswith("ER_SUCCESS_MATCH") and values:
                name_obj = getattr(values[0], "value", None)
                resolved = getattr(name_obj, "name", None) or getattr(name_obj, "id", None)
                if resolved:
                    _add(str(resolved).strip())
                break
    if not candidates:
        return None
    return max(candidates, key=len)


def respond_with_buses(handler_input: HandlerInput, ref: StopRef) -> Response:
    result = service().next_buses(ref)
    return (handler_input.response_builder
            .speak(result.speech)
            .set_card(SimpleCard(result.card_title, result.card_text))
            .set_should_end_session(True)
            .response)


def elicit_stop_number(handler_input: HandlerInput, prompt: str) -> Response:
    return (handler_input.response_builder
            .speak(prompt).ask(ASK_STOP)
            .add_directive(ElicitSlotDirective(slot_to_elicit="stopNumber"))
            .response)


# ---- handlers ----------------------------------------------------------------------------

class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        fav = service().get_favourite(user_id(handler_input))
        if fav:
            return respond_with_buses(handler_input, fav)
        speech = ("Welcome to four next bus. Ask me for buses from a stop number, for example, from stop 184. "
                  "Or say, set my favourite stop to, and your stop number.")
        return handler_input.response_builder.speak(speech).ask(ASK_STOP).response


class NextBusIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("NextBusIntent")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        code = slot_value(handler_input, "stopNumber")
        svc = service()
        if code:
            ref = svc.resolve_stop(code)
            if not ref:
                return handler_input.response_builder.speak(unknown_stop(code)).set_should_end_session(True).response
            return respond_with_buses(handler_input, ref)
        fav = svc.get_favourite(user_id(handler_input))
        if fav:
            return respond_with_buses(handler_input, fav)
        return elicit_stop_number(handler_input, NO_FAVOURITE + " Or tell me a stop number now. " + ASK_STOP)


class SetFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("SetFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        code = slot_value(handler_input, "stopNumber")
        if not code:
            return elicit_stop_number(handler_input, "Which stop number should I save as your favourite?")
        svc = service()
        ref = svc.resolve_stop(code)
        if not ref:
            return handler_input.response_builder.speak(unknown_stop(code)).set_should_end_session(True).response
        svc.set_favourite(user_id(handler_input), ref)
        speech = (f"Done. Your favourite stop is now {ref.stop_code}, {ref.spoken_name}. "
                  "From now on, just ask me for the next bus.")
        return (handler_input.response_builder.speak(speech)
                .set_card(SimpleCard("Favourite stop saved", f"Stop {ref.stop_code} - {ref.spoken_name}"))
                .set_should_end_session(True).response)


class GetFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("GetFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        fav = service().get_favourite(user_id(handler_input))
        speech = f"Your favourite stop is {fav.stop_code}, {fav.spoken_name}." if fav else NO_FAVOURITE
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


class ClearFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ClearFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        uid = user_id(handler_input)
        svc = service()
        had = svc.get_favourite(uid)
        svc.clear_favourite(uid)
        named.clear_pending(handler_input)
        speech = FORGOTTEN if had else NO_FAVOURITE_TO_FORGET
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


def user_store():
    """Favourites live on the shared table; prefer an already-wired service store."""
    if _service is not None:
        return _service.store
    store, _ = _backend()
    return store


class ClearAllFavouritesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ClearAllFavouritesIntent")(handler_input)

    def handle(self, handler_input):
        uid = user_id(handler_input)
        store = user_store()
        for mode in (None, "luas", "dart", "train"):
            store.clear_favourite(uid, mode)
        named.clear_pending(handler_input)
        return (handler_input.response_builder.speak(FORGOTTEN_ALL)
                .set_should_end_session(True).response)


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        return handler_input.response_builder.speak(HELP).ask(ASK_STOP).response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or is_intent_name("AMAZON.StopIntent")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Goodbye.").set_should_end_session(True).response


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        pending = named.redirect_if_pending(handler_input, slot_value)
        if pending:
            return pending
        speech = "Sorry, I didn't catch that. " + HELP
        return handler_input.response_builder.speak(speech).ask(ASK_STOP).response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        if isinstance(exception, TimetableNotLoaded):
            log.error("timetable not loaded: %s", exception)
            speech = NOT_READY
        else:
            log.exception("unhandled error")
            speech = ERROR
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


class SkillIdVerificationError(Exception):
    pass


def _application_id(event: dict) -> str | None:
    system = ((event.get("context") or {}).get("System") or {})
    app = system.get("application") or ((event.get("session") or {}).get("application") or {})
    return app.get("applicationId")


def verify_skill_id(event: dict) -> None:
    """ask-sdk only supports a single skill ID; we allow several (e.g. dev + live copies)."""
    if not config.SKILL_IDS:
        return
    app_id = _application_id(event)
    if app_id not in config.SKILL_IDS:
        log.error("skill ID verification failed for %r", app_id)
        raise SkillIdVerificationError(f"unexpected skill ID {app_id!r}")


sb = SkillBuilder()
handlers = [LaunchRequestHandler(), NextBusIntentHandler(), SetFavouriteStopIntentHandler(),
            GetFavouriteStopIntentHandler(), ClearFavouriteStopIntentHandler(),
            ClearAllFavouritesIntentHandler()]
for spec in named.MODES:
    handlers.extend(named.make_handlers(spec, slot_value))
handlers.extend([HelpIntentHandler(), CancelOrStopIntentHandler(),
                 FallbackIntentHandler(), SessionEndedRequestHandler()])
for h in handlers:
    sb.add_request_handler(h)
sb.add_exception_handler(CatchAllExceptionHandler())

_sdk_handler = sb.lambda_handler()


def handler(event, context):
    verify_skill_id(event)
    return _sdk_handler(event, context)
