from settle import _market_family, settle_run, MatchOutcome


def test_market_family_classifies_known_families():
    assert _market_family("1x2") == "main"
    assert _market_family("Double chance") == "main"
    assert _market_family("1st half - multigoals") == "1st half"
    assert _market_family("1st half corners") == "corners"        # stat-before-period rule
    assert _market_family("2nd half - handicap 1X2") == "2nd half"
    assert _market_family("Total corners") == "corners"
    assert _market_family("Total bookings") == "cards"
    assert _market_family("2 multigoals") == "multigoals"
    assert _market_family("Halftime/fulltime") == "htft"
    assert _market_family("Draw or under 1.5") == "or-combo"
    assert _market_family("Double chance & total 5.5") == "combo"


def test_market_family_has_explicit_other_bucket():
    # an unanticipated market must land visibly in "other", not be force-fit
    assert _market_family("Some Novel Market") == "other"
    assert _market_family("Shots - Neymar") == "player"


def test_settle_run_reports_per_family_counts():
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4},
        {"league": "L", "match": "m", "market": "1x2", "selection": "2", "odd": 1.4},
        {"league": "L", "match": "m", "market": "Total corners", "selection": "Over 8.5", "odd": 1.4},
    ]}]
    outcomes = {"m": MatchOutcome("m", 2, 1)}
    res = settle_run(slips, outcomes)
    fam = res["families"]
    assert fam["main"]["n"] == 2
    assert fam["main"]["gradeable"] == 2
    assert fam["main"]["won"] == 1              # "1" won, "2" lost
    assert fam["corners"]["n"] == 1
    assert fam["corners"]["gradeable"] == 0     # needs a provider
    assert fam["corners"]["won"] == 0


def test_settle_run_keeps_existing_per_set_tallies():
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4}]}]
    res = settle_run(slips, {"m": MatchOutcome("m", 2, 1)})
    assert res["A"]["total"] == 1 and res["A"]["won"] == 1
    assert "verdicts" in res
