from make_betslips import build_slips, collect_selections


def sel(match, n):
    return {"match": match, "odd": {"id": n}}


def pools():
    return {
        "m1": [sel("m1", 1), sel("m1", 2), sel("m1", 3)],
        "m2": [sel("m2", 4), sel("m2", 5)],
        "m3": [sel("m3", 6)],
    }


def test_slips_have_distinct_matches_within_each():
    slips = build_slips(pools(), size=2, max_slips=10)
    for slip in slips:
        keys = [s["match"] for s in slip]
        assert len(keys) == len(set(keys))


def test_no_odd_id_reused_across_all_slips():
    slips = build_slips(pools(), size=2, max_slips=10)
    ids = [s["odd"]["id"] for slip in slips for s in slip]
    assert len(ids) == len(set(ids))


def test_respects_max_slips():
    assert len(build_slips(pools(), size=2, max_slips=1)) == 1


def test_leg_count_never_exceeds_size():
    for slip in build_slips(pools(), size=2, max_slips=10):
        assert len(slip) <= 2


def test_size_zero_returns_no_slips():
    assert build_slips(pools(), size=0, max_slips=10) == []


def test_collect_selections_dedupes_and_filters():
    details = {
        "odds": [
            {"id": 1, "price": 1.40, "oddStatus": 0, "name": "A"},
            {"id": 2, "price": 1.90, "oddStatus": 0, "name": "B"},
            {"id": 3, "price": 1.30, "oddStatus": 1, "name": "C"},
        ],
        "markets": [
            {"name": "Total", "typeId": 18, "sportMarketId": 70, "id": 100,
             "desktopOddIds": [[1], [2], [3]]},
            {"name": "Total", "typeId": 18, "sportMarketId": 70, "id": 100,
             "desktopOddIds": [[1]]},  # duplicate ref of odd 1
        ],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 1.50)
    assert [s["odd"]["id"] for s in out] == [1]  # only 1.40 active, deduped; 1.90 out of band, 1.30 suspended
