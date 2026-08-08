"""A booking code dies at its FIRST kickoff, and nothing used to say when that is.

Diagnosed live 2026-08-08: code D48TV resolved perfectly against FindReservedBet — 12 selections,
no null ids, Error null — but loaded nothing, because all 12 legs had already kicked off. The
reservation was intact; the football was over. Minting was never broken.

So the file has to carry the expiry, and the longest-lived slip has to come first. A code whose
expiry is not shown is a code you find out about by pasting it and getting an empty betslip.
"""
from make_betslips import slip_expiry, slip_header_line, sort_slips_by_expiry


def _leg(price=1.4, market="1x2", label="1", start="2026-08-09T18:00:00Z", match="A vs B"):
    return {"price": price, "market_name": market, "label": label, "match": match,
            "league": "L", "event": {"startDate": start}}


def test_expiry_is_the_earliest_kickoff():
    slip = [_leg(start="2026-08-09T20:00:00Z"), _leg(start="2026-08-09T18:00:00Z", match="C vs D"),
            _leg(start="2026-08-09T19:00:00Z", match="E vs F")]
    assert slip_expiry(slip) == "2026-08-09T18:00:00Z"


def test_expiry_is_none_when_no_leg_has_a_start():
    assert slip_expiry([{"price": 1.4, "market_name": "1x2", "label": "1", "event": {}}]) is None


def test_expiry_ignores_legs_with_a_missing_start():
    slip = [_leg(start="2026-08-09T20:00:00Z"),
            {"price": 1.4, "market_name": "1x2", "label": "1", "event": {}}]
    assert slip_expiry(slip) == "2026-08-09T20:00:00Z"


def test_header_shows_the_expiry():
    line = slip_header_line("B1", [_leg(start="2026-08-09T18:00:00Z")])
    assert "expires" in line and "2026-08-09 18:00Z" in line


def test_header_survives_a_slip_with_no_kickoff_data():
    line = slip_header_line("B1", [{"price": 1.4, "market_name": "1x2", "label": "1",
                                    "event": {}}])
    assert "BETSLIP B1" in line          # no crash, no invented expiry
    assert "expires" not in line


def test_longest_lived_slip_sorts_first():
    early = [_leg(start="2026-08-09T12:00:00Z")]
    late = [_leg(start="2026-08-09T22:00:00Z", match="C vs D")]
    mid = [_leg(start="2026-08-09T18:00:00Z", match="E vs F")]
    assert sort_slips_by_expiry([early, late, mid]) == [late, mid, early]


def test_slips_without_expiry_sort_last():
    dated = [_leg(start="2026-08-09T12:00:00Z")]
    undated = [{"price": 1.4, "market_name": "1x2", "label": "1", "event": {}}]
    assert sort_slips_by_expiry([undated, dated]) == [dated, undated]


def test_sorting_is_stable_for_equal_expiries():
    a = [_leg(start="2026-08-09T12:00:00Z", match="A vs B")]
    b = [_leg(start="2026-08-09T12:00:00Z", match="C vs D")]
    assert sort_slips_by_expiry([a, b]) == [a, b]
