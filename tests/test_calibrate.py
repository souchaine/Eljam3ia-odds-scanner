from calibrate import calibrate, read_legs_csv


def _row(family, match, market, selection, odd, verdict):
    return {"family": family, "match": match, "market": market,
            "selection": selection, "odd": odd, "verdict": verdict}


def test_calibrate_per_family_hit_vs_implied():
    # two graded main legs: won @1.25 (implied 80%), lost @2.0 (implied 50%); one ungraded corners
    rows = [
        _row("main", "m1", "1x2", "1", "1.25", "won"),
        _row("main", "m2", "1x2", "1", "2.0", "lost"),
        _row("corners", "m1", "Total corners", "Over 8.5", "1.4", "unsettleable"),
    ]
    c = calibrate(rows)
    assert c["main"]["graded"] == 2
    assert c["main"]["won"] == 1
    assert c["main"]["hit_pct"] == 50.0                 # 1 of 2 won
    assert round(c["main"]["implied_pct"], 1) == 65.0   # mean(0.80, 0.50)
    assert round(c["main"]["gap"], 1) == -15.0          # 50 - 65
    # an all-unsettleable family reports no hit/implied, never a fabricated 0%
    assert c["corners"]["graded"] == 0
    assert c["corners"]["hit_pct"] is None
    assert c["corners"]["implied_pct"] is None
    assert c["corners"]["gap"] is None


def test_calibrate_excludes_void_and_counts_distinct():
    rows = [
        _row("main", "m", "Draw no bet", "1", "1.4", "void"),   # push -> excluded from graded
        _row("main", "m", "1x2", "1", "1.5", "won"),
        _row("main", "m", "1x2", "1", "1.5", "won"),            # duplicate leg
    ]
    c = calibrate(rows)
    assert c["main"]["n"] == 3
    assert c["main"]["distinct"] == 2      # (m, Draw no bet, 1) and (m, 1x2, 1)
    assert c["main"]["graded"] == 2        # the void is not graded
    assert c["main"]["won"] == 2
    assert c["main"]["hit_pct"] == 100.0


def test_calibrate_ignores_invalid_odds_for_implied_only():
    # a graded leg with a missing/zero odd still counts toward the hit rate but cannot contribute
    # an implied probability; implied is averaged only over graded legs with a positive odd.
    rows = [
        _row("main", "m1", "1x2", "1", "2.0", "won"),
        _row("main", "m2", "1x2", "1", "0", "lost"),       # malformed odd
    ]
    c = calibrate(rows)
    assert c["main"]["graded"] == 2
    assert c["main"]["won"] == 1
    assert c["main"]["hit_pct"] == 50.0
    assert round(c["main"]["implied_pct"], 1) == 50.0      # only the 2.0-odd leg (1/2.0)


def test_read_legs_csv_roundtrips_dictrows():
    text = ("settled_at,run_dir,match,family,market,selection,odd,verdict\n"
            "2026-01-01T00:00:00Z,run_A,m,main,1x2,1,1.4,won\n")
    rows = read_legs_csv(text)
    assert rows[0]["family"] == "main" and rows[0]["odd"] == "1.4" and rows[0]["verdict"] == "won"
