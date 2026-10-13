"""Shared Alexa response checks for named-mode follow-up contracts.

Device failures we have already hit, and that these helpers exist to catch:

- Dialog.ElicitSlot on a custom station/direction type drops 'northbound' and
  'Maynooth westbound'; Lambda never runs and the device goes silent.
- Dialog.ElicitSlot on AMAZON.SearchQuery also drops follow-ups. Alexa leaves
  the skill: silence, or a Wikipedia answer for a place name such as Maynooth.
- A short .ask() ('Which direction?') is what Alexa replays when it drops the
  utterance, so the reprompt must repeat the full spoken prompt.
- Tests that inject a filled direction slot only prove the happy path Alexa
  would have sent if ElicitSlot had worked. Always also exercise the intents
  Alexa actually delivers: station slot stuffed with the word, SearchQuery,
  Fallback, and NextBusIntent stealing the turn.
"""


def speech(resp: dict) -> str:
    out = (resp.get("response") or {}).get("outputSpeech") or {}
    return out.get("ssml") or out.get("text") or ""


def ssml_text(ssml: str) -> str:
    return (ssml or "").replace("<speak>", "").replace("</speak>", "").strip()


def elicit_slot(resp: dict) -> str | None:
    for directive in (resp.get("response") or {}).get("directives") or []:
        if directive.get("type") == "Dialog.ElicitSlot":
            return directive.get("slotToElicit")
    return None


def dialog_directive_types(resp: dict) -> list[str]:
    return [
        d.get("type")
        for d in (resp.get("response") or {}).get("directives") or []
        if str(d.get("type") or "").startswith("Dialog.")
    ]


def assert_open_without_dialog(resp, *, pending_station=None, pending_action="need_direction"):
    """Named-mode follow-ups must keep a normal open session.

    Do not 'fix' a failure here by sending Dialog.ElicitSlot. That is the
    bug. Keep shouldEndSession false, no Dialog.* directives, and a
    reprompt that is the same text as the spoken prompt.
    """
    body = resp.get("response") or {}
    spoken = speech(resp)
    assert spoken, "open prompt returned no speech (device would go silent)"
    assert body.get("shouldEndSession") is False
    ask = ((body.get("reprompt") or {}).get("outputSpeech") or {})
    ask_ssml = ask.get("ssml") or ask.get("text") or ""
    assert ask_ssml, "missing reprompt; Alexa may stop listening"
    assert ssml_text(ask_ssml) == ssml_text(spoken), (ask_ssml, spoken)
    assert dialog_directive_types(resp) == [], (
        "Dialog.ElicitSlot drops follow-ups on device; "
        f"got {dialog_directive_types(resp)}"
    )
    attrs = resp.get("sessionAttributes") or {}
    assert attrs.get("pending_action") == pending_action
    if pending_station is not None:
        assert attrs.get("pending_station") == pending_station
    return attrs


def assert_not_silent(resp) -> str:
    """Any in-skill follow-up must speak; empty SSML looks like device silence."""
    text = speech(resp)
    assert text, "empty speech looks silent on the device"
    return text
