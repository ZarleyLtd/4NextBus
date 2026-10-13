from datetime import datetime, timedelta

from src.common.gtfs_time import DUBLIN
from src.common.models import Prediction
from src.common.speech import humanise, next_buses_speech, next_trains_speech, next_trams_speech, say_route

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
    assert text == ("At stop 184, Fairfield Road: the 23 to Merrion Square in 4 minutes, "
                    "and the E1 to Ballywaltrim in 7 minutes.")


def test_speech_due_now_and_scheduled():
    text = next_buses_speech("1", "X", [pred("9", "Town", 0), pred("9", "Town", 12, realtime=False)], NOW)
    assert "the 9 to Town due now" in text
    assert "the 9 to Town scheduled in 12 minutes" in text


def test_speech_repeats_headsign_when_route_has_two_destinations():
    text = next_buses_speech("1", "X", [pred("9", "Town", 3), pred("9", "Airport", 8)], NOW)
    assert "the 9 to Town in 3 minutes" in text
    assert "the 9 to Airport in 8 minutes" in text


def test_speech_empty_and_no_realtime():
    assert next_buses_speech("184", "Fairfield Rd", [], NOW).startswith("I can't find any buses due at stop 184")
    text = next_buses_speech("1", "X", [pred("9", "Town", 3, realtime=False)], NOW, realtime_available=False)
    assert text.endswith("Live times are unavailable right now, so these are timetable times.")


def test_trams_and_trains_speech():
    assert next_trams_speech("Dundrum", [pred("Green", "Brides Glen", 4)], NOW) == (
        'At Dundrum: <sub alias="Lewis">Luas</sub> in 4 minutes to Brides Glen.')
    assert next_trams_speech("Dundrum", [], NOW) == (
        'I can\'t find any <sub alias="Lewises">Luases</sub> due at Dundrum in the next two hours.')
    assert next_trains_speech("Pearse", [pred("DART", "Bray", 3)], NOW).startswith("At Pearse: Train in 3 minutes to Bray.")
    empty = next_trains_speech("Maynooth", [], NOW, empty_kind="commuter trains")
    assert empty.startswith("I can't find any commuter trains due at Maynooth")


def test_speech_repeats_destination_for_consecutive_same_destination():
    buses = next_buses_speech("1", "X", [pred("9", "Town", 3), pred("9", "Town", 8)], NOW)
    assert buses.count("to Town") == 2
    trams = next_trams_speech("Dundrum", [pred("Green", "Brides Glen", 4), pred("Green", "Brides Glen", 11)], NOW)
    assert trams.count("to Brides Glen") == 2
    trains = next_trains_speech("Pearse", [pred("DART", "Bray", 3), pred("DART", "Bray", 18)], NOW)
    assert trains.count("to Bray") == 2
