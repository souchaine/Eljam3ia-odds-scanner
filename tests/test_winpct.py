from make_betslips import collect_selections, implied_prob, slip_win_pct


def legs(prices, market_name="Total"):
    return [{"price": p, "market_name": market_name} for p in prices]


def combined(prices):
    out = 1.0
    for p in prices:
        out *= p
    return out


def test_implied_prob_is_one_over_price():
    assert abs(implied_prob(1.25) - 0.8) < 1e-9
    assert abs(implied_prob(2.0) - 0.5) < 1e-9


def test_implied_prob_guards_bad_input():
    assert implied_prob("n/a") == 0.0
    assert implied_prob(0) == 0.0
    assert implied_prob(None) == 0.0


def test_slip_win_pct_is_product_times_100():
    assert abs(slip_win_pct(legs([2.0, 2.0])) - 25.0) < 1e-9


def test_slip_win_pct_empty_slip_is_zero():
    assert slip_win_pct([]) == 0.0


def test_slip_win_pct_equals_100_over_combined_odds():
    prices = [1.4, 1.3, 1.5, 1.25]
    assert abs(slip_win_pct(legs(prices)) - 100.0 / combined(prices)) < 1e-9


def test_win_pct_is_monotonic_with_combined_odds():
    """Regression: higher combined odds must ALWAYS mean lower win%.

    The old de-vig normalized over a market's bundled lines, so win% depended on which markets
    the legs came from and could rank a longer-odds slip ABOVE a shorter-odds one.
    """
    longer = legs([1.4] * 20)   # combined ~836
    shorter = legs([1.3] * 20)  # combined ~190
    assert combined([1.4] * 20) > combined([1.3] * 20)
    assert slip_win_pct(longer) < slip_win_pct(shorter)


def test_win_pct_ignores_which_market_a_leg_came_from():
    """Regression: two slips with identical prices must score identically, whatever the market.

    Previously a leg from a heavily-bundled market (Total/Handicap) was crushed ~10-20x versus
    an identical price in a 3-outcome market (1x2), which is what broke the ordering.
    """
    prices = [1.4, 1.35, 1.45]
    assert slip_win_pct(legs(prices, "Total")) == slip_win_pct(legs(prices, "1x2"))


def test_win_pct_magnitude_is_sane_for_20_legs():
    """A 20-leg slip of 1.40s is ~0.12%, not ~1e-20 (the old bundled-devig artifact)."""
    pct = slip_win_pct(legs([1.4] * 20))
    assert 0.01 < pct < 1.0


def test_collect_selections_keeps_price_and_market_name():
    details = {
        "odds": [
            {"id": 1, "price": 1.40, "oddStatus": 0, "name": "Over 2.5"},
            {"id": 2, "price": 5.00, "oddStatus": 0, "name": "Under 2.5"},
            {"id": 3, "price": 1.30, "oddStatus": 1, "name": "suspended"},
        ],
        "markets": [{"name": "Total", "typeId": 18, "sportMarketId": 2, "id": 20,
                     "desktopOddIds": [[1], [2], [3]]}],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 1.5)  # only odd 1 qualifies (1.40); 3 is suspended
    assert len(out) == 1
    assert out[0]["price"] == 1.40 and out[0]["market_name"] == "Total"
    assert abs(slip_win_pct(out) - 100.0 / 1.40) < 1e-9


def test_collect_selections_survives_malformed_price():
    details = {
        "odds": [
            {"id": 1, "price": 1.40, "oddStatus": 0, "name": "A"},
            {"id": 2, "price": "n/a", "oddStatus": 0, "name": "B"},
        ],
        "markets": [{"name": "Total", "typeId": 18, "sportMarketId": 2, "id": 20,
                     "desktopOddIds": [[1], [2]]}],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 1.5)  # must not crash on the "n/a" price
    assert len(out) == 1 and out[0]["odd"]["id"] == 1
