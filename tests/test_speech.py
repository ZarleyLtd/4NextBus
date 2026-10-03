from datetime import datetime, timedelta

from src.common.gtfs_time import DUBLIN
from src.common.models import Prediction
from src.common.speech import humanise, next_buses_speech, say_route

NOW = datetime(2026, 10, 3, 20, 0, tzinfo=DUBLIN)


def pred(route, head, mins, realtime=True):
    when = NOW + timedelta(minutes=mins)
    return Prediction(route, head, when, when, realtime, 0, f"t-{route}-{mins}")


def test_humanise_expands_abbreviations():
    assert humanise("Fairfield Rd") == "Fairfield Road"
    assert humanise("Parnell Square West, stop 2") == "Parnell Square West"


def test_say_route_splits_letter_suffix():
    assert say_route("46A") == "46 A"
    assert say_route("E2") == "E2"
    assert say_route("145") == "145"


def test_speech_basic():
    text = next_buses_speech("184", "Fairfield Rd", [pred("23", "Merrion Sq", 4), pred("E1", "Ballywaltrim", 7)], NOW)
    assert text == ("At stop 184, Fairfield Road: the 23 towards Merrion Square in 4 minutes, "
                    "and the E1 towards Ballywaltrim in 7 minutes.")


def test_speech_due_now_and_scheduled():
    text = next_buses_speech("1", "X", [pred("9", "Town", 0), pred("9", "Town", 12, realtime=False)], NOW)
    assert "the 9 towards Town due now" in text
    assert "the 9 scheduled in 12 minutes" in text      # headsign not repeated for same route


def test_speech_repeats_headsign_when_route_has_two_destinations():
    text = next_buses_speech("1", "X", [pred("9", "Town", 3), pred("9", "Airport", 8)], NOW)
    assert "the 9 towards Town in 3 minutes" in text
    assert "the 9 towards Airport in 8 minutes" in text


def test_speech_empty_and_no_realtime():
    assert next_buses_speech("184", "Fairfield Rd", [], NOW).startswith("I can't find any buses due at stop 184")
    text = next_buses_speech("1", "X", [pred("9", "Town", 3, realtime=False)], NOW, realtime_available=False)
    assert text.endswith("Live times are unavailable right now, so these are timetable times.")
