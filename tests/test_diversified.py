from make_betslips import build_diversified_slips


def sel(match, oddid, market_name):
    return {"match": match, "market_name": market_name, "odd": {"id": oddid}}


def pools():
    # 6 matches; two families present: "corners" and "main"
    return {
        "m1": [sel("m1", 1, "Total corners"), sel("m1", 2, "1x2")],
        "m2": [sel("m2", 3, "Corner 1x2"), sel("m2", 4, "Total")],
        "m3": [sel("m3", 5, "Handicap")],
        "m4": [sel("m4", 6, "Total corners")],
        "m5": [sel("m5", 7, "1x2")],
        "m6": [sel("m6", 8, "Corner 1x2")],
    }


def test_distinct_matches_within_each_slip():
    for slip in build_diversified_slips(pools(), size=4, max_slips=10):
        keys = [s["match"] for s in slip]
        assert len(keys) == len(set(keys))


def test_no_odd_id_reused_across_slips():
    slips = build_diversified_slips(pools(), size=4, max_slips=10)
    ids = [s["odd"]["id"] for slip in slips for s in slip]
    assert len(ids) == len(set(ids))


def test_first_slip_spans_both_families_when_possible():
    from make_betslips import market_category
    slip = build_diversified_slips(pools(), size=4, max_slips=10)[0]
    fams = {market_category(s["market_name"]) for s in slip}
    assert "corners" in fams and "main" in fams


def test_respects_max_and_size():
    slips = build_diversified_slips(pools(), size=4, max_slips=1)
    assert len(slips) == 1
    assert len(slips[0]) <= 4
