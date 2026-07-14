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


def test_novig_single_outcome_market_uses_raw_not_one():
    # a market with only one active outcome cannot be de-vigged -> raw 1/price, not 1.0
    assert abs(novig_prob(1.35, [1.35]) - (1.0 / 1.35)) < 1e-9


def test_slip_win_pct_is_product_times_100():
    slip = [{"novig_prob": 0.5}, {"novig_prob": 0.5}]
    assert abs(slip_win_pct(slip) - 25.0) < 1e-9


def test_slip_win_pct_empty_slip_is_zero():
    assert slip_win_pct([]) == 0.0


def test_collect_selections_attaches_novig_from_active_outcomes():
    from make_betslips import collect_selections
    details = {
        "odds": [
            {"id": 1, "price": 2.0, "oddStatus": 0, "name": "A"},
            {"id": 2, "price": 2.0, "oddStatus": 0, "name": "B"},
            {"id": 3, "price": 5.0, "oddStatus": 1, "name": "C-suspended"},
        ],
        "markets": [{"name": "1x2", "typeId": 1, "sportMarketId": 1, "id": 10,
                     "desktopOddIds": [[1], [2], [3]]}],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 2.5)
    by_id = {s["odd"]["id"]: s["novig_prob"] for s in out}
    assert abs(by_id[1] - 0.5) < 1e-9  # only active outcomes 1&2 (2.0 each) -> 0.5


def test_collect_selections_survives_malformed_market_price():
    from make_betslips import collect_selections
    details = {
        "odds": [
            {"id": 1, "price": 1.40, "oddStatus": 0, "name": "A"},
            {"id": 2, "price": "n/a", "oddStatus": 0, "name": "B"},
        ],
        "markets": [{"name": "Total", "typeId": 18, "sportMarketId": 2, "id": 20,
                     "desktopOddIds": [[1], [2]]}],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 1.5)  # only odd 1 (1.40) qualifies; must not crash
    assert len(out) == 1 and out[0]["odd"]["id"] == 1
    assert out[0]["novig_prob"] > 0
