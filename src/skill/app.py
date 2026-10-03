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
from src.common.store import Store
from src.skill.service import BusService, StopRef, TimetableNotLoaded

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)

# One service per container (warm invocations reuse the caches).
_service: BusService | None = None


def service() -> BusService:
    global _service
    if _service is None:
        store = Store(config.TABLE_NAME, config.REGION)
        _service = BusService(store, RealtimeCache(store, config.nta_api_key()))
    return _service


# ---- speech fragments --------------------------------------------------------------------

HELP = ("I can tell you the next Dublin buses from any stop. Say, from stop, followed by the number "
        "on the bus stop pole, for example, from stop 184. To save a stop, say, set my favourite stop to, "
        "and the number. After that, just ask me for the next bus. What would you like?")
NO_FAVOURITE = ("You haven't set a favourite stop yet. Say, set my favourite stop to, followed by the "
                "number on your bus stop pole.")
ASK_STOP = "Which stop number?"
ERROR = "Sorry, I had trouble getting the bus times. Please try again in a moment."
NOT_READY = "Sorry, the bus timetable isn't loaded yet. Please try again later."


def unknown_stop(code: str) -> str:
    return f"I couldn't find stop number {code}. Check the number on the bus stop pole and try again."


def user_id(handler_input: HandlerInput) -> str:
    return handler_input.request_envelope.context.system.user.user_id


def slot_value(handler_input: HandlerInput, name: str) -> str | None:
    intent = getattr(handler_input.request_envelope.request, "intent", None)
    slots = getattr(intent, "slots", None) or {}
    slot = slots.get(name)
    value = getattr(slot, "value", None) if slot else None
    return value.strip() if value and value != "?" else None


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
        fav = service().get_favourite(user_id(handler_input))
        speech = f"Your favourite stop is {fav.stop_code}, {fav.spoken_name}." if fav else NO_FAVOURITE
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
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


sb = SkillBuilder()
if config.SKILL_ID:
    sb.skill_id = config.SKILL_ID
for h in (LaunchRequestHandler(), NextBusIntentHandler(), SetFavouriteStopIntentHandler(),
          GetFavouriteStopIntentHandler(), HelpIntentHandler(), CancelOrStopIntentHandler(),
          FallbackIntentHandler(), SessionEndedRequestHandler()):
    sb.add_request_handler(h)
sb.add_exception_handler(CatchAllExceptionHandler())

handler = sb.lambda_handler()
