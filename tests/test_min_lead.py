"""Codes must not be born dead.

Measured 2026-08-08: a run finishing at 12:14Z minted 25 codes, of which SEVEN expired at 12:00Z —
before the file was even written. The scan walks every league and takes ~30 minutes, so a fixture
that is comfortably upcoming when it is scanned can have kicked off by the time its code is
reserved. The reservation still succeeds; it is simply useless.

So selections are filtered against a minimum LEAD TIME immediately before building, not against
the state of the world when the scan started.
"""
import pytest

from make_betslips import drop_starting_soon


def _pick(start, match="A vs B"):
    return {"price": 1.4, "market_name": "1x2", "label": "1", "match": match,
            "league": "L", "event": {"startDate": start}}


def _pools(*starts):
    return {str(i): [_pick(s, f"M{i}")] for i, s in enumerate(starts)}


NOW = "2026-08-08T12:00:00Z"


def test_a_fixture_already_started_is_dropped():
    pools = drop_starting_soon(_pools("2026-08-08T11:30:00Z"), NOW, lead_minutes=15)
    assert pools == {}


def test_a_fixture_inside_the_lead_window_is_dropped():
    # starts in 10 minutes; by the time 25 codes are reserved it may already be running
    pools = drop_starting_soon(_pools("2026-08-08T12:10:00Z"), NOW, lead_minutes=15)
    assert pools == {}


def test_a_fixture_beyond_the_lead_window_is_kept():
    pools = drop_starting_soon(_pools("2026-08-08T12:30:00Z"), NOW, lead_minutes=15)
    assert len(pools) == 1


def test_the_boundary_is_inclusive():
    pools = drop_starting_soon(_pools("2026-08-08T12:15:00Z"), NOW, lead_minutes=15)
    assert len(pools) == 1, "exactly at the lead time still counts as usable"


def test_only_the_starting_soon_events_are_dropped():
    pools = drop_starting_soon(
        _pools("2026-08-08T11:00:00Z", "2026-08-08T18:00:00Z", "2026-08-08T12:05:00Z"),
        NOW, lead_minutes=15)
    assert [p[0]["event"]["startDate"] for p in pools.values()] == ["2026-08-08T18:00:00Z"]


def test_an_event_with_no_start_is_dropped_not_assumed_safe():
    # an unknown kickoff cannot be SHOWN to be in the future; the same view exclude_inplay takes
    pools = {"1": [{"price": 1.4, "market_name": "1x2", "label": "1", "event": {}}]}
    assert drop_starting_soon(pools, NOW, lead_minutes=15) == {}


def test_an_unparseable_start_is_dropped():
    assert drop_starting_soon(_pools("not a date"), NOW, lead_minutes=15) == {}


@pytest.mark.parametrize("lead", [0, 60])
def test_lead_is_configurable(lead):
    pools = drop_starting_soon(_pools("2026-08-08T12:30:00Z"), NOW, lead_minutes=lead)
    assert (len(pools) == 1) is (lead == 0)


def test_partially_started_event_group_is_dropped_whole():
    # one event id maps to many selections; if the fixture started they all go
    pools = {"1": [_pick("2026-08-08T11:00:00Z"), _pick("2026-08-08T11:00:00Z")]}
    assert drop_starting_soon(pools, NOW, lead_minutes=15) == {}
