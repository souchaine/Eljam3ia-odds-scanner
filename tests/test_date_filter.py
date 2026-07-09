from datetime import datetime, timezone

from eljam3ia_odds_scanner import filter_events_by_window

NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def ev(start):
    return {"id": 1, "startDate": start}


def test_keeps_event_inside_window():
    assert filter_events_by_window([ev("2026-07-09T20:00:00Z")], 23, now=NOW)


def test_drops_event_beyond_window():
    assert filter_events_by_window([ev("2026-07-10T12:00:00Z")], 23, now=NOW) == []


def test_keeps_event_exactly_at_window_end():
    assert filter_events_by_window([ev("2026-07-10T11:00:00Z")], 23, now=NOW)


def test_drops_already_started_event():
    assert filter_events_by_window([ev("2026-07-09T11:59:00Z")], 23, now=NOW) == []


def test_hours_zero_keeps_everything():
    events = [ev("2027-01-01T00:00:00Z"), ev("2020-01-01T00:00:00Z")]
    assert filter_events_by_window(events, 0, now=NOW) == events


def test_drops_unparseable_startdate():
    assert filter_events_by_window([{"id": 2, "startDate": ""}], 23, now=NOW) == []
