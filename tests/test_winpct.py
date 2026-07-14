import math

from make_betslips import novig_prob, slip_win_pct


def test_novig_two_way_even_market():
    # 1.90 / 1.90 -> implied 0.5263 each, sum 1.0526, no-vig 0.5 each
    assert abs(novig_prob(1.90, [1.90, 1.90]) - 0.5) < 1e-9


def test_novig_normalizes_over_all_outcomes():
    # market 2.0 / 4.0 / 4.0 -> implied 0.5/0.25/0.25 = 1.0 (no vig) -> 0.5 for the 2.0 pick
    assert abs(novig_prob(2.0, [2.0, 4.0, 4.0]) - 0.5) < 1e-9


def test_novig_empty_market_falls_back_to_raw():
    assert abs(novig_prob(1.25, []) - 0.8) < 1e-9


def test_novig_skips_zero_prices():
    assert abs(novig_prob(2.0, [2.0, 2.0, 0.0]) - 0.5) < 1e-9


def test_slip_win_pct_is_product_times_100():
    slip = [{"novig_prob": 0.5}, {"novig_prob": 0.5}]
    assert abs(slip_win_pct(slip) - 25.0) < 1e-9


def test_slip_win_pct_empty_slip_is_zero():
    assert slip_win_pct([]) == 0.0
