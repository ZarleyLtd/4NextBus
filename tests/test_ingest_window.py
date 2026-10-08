from ingest.build_timetable import calendar_service_ids, keep_window_departures
from src.common.models import Departure, StopTimetable


def test_calendar_service_ids_unions_all_days():
    cal = {"20261008": {"A", "B"}, "20261009": {"B", "C"}}
    assert calendar_service_ids(cal) == frozenset({"A", "B", "C"})


def test_keep_window_departures_preserves_matching_copies():
    stop = StopTimetable("sid", "184", "Fairfield Rd", [
        Departure("t1", "23", "Town", 3600, "A", 10),
        Departure("t2", "23", "Town", 3600, "Z", 10),
        Departure("t3", "E1", "Town", 7200, "B", 5),
    ])
    keep_window_departures(stop, frozenset({"A", "B"}))
    assert [d.trip_id for d in stop.departures] == ["t1", "t3"]
    assert stop.departures[0].service_id == "A"
