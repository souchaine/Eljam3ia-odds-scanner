from calibrate import calibrate, print_report, read_legs_csv


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


def test_small_sample_note_pluralises_correctly(capsys):
    one = [_row("main", "m", "1x2", "1", "1.4", "won")]
    print_report(calibrate(one))
    assert "only 1 graded leg total" in capsys.readouterr().out      # singular
    many = one + [_row("main", "m2", "1x2", "1", "1.4", "lost")]
    print_report(calibrate(many))
    assert "only 2 graded legs total" in capsys.readouterr().out     # plural


# ---- n-floor suppression: never print a rate the sample cannot support -------------------------

def _legs(family, n_won, n_lost, odd="1.4"):
    return ([_row(family, f"m{i}", "1x2", "1", odd, "won") for i in range(n_won)] +
            [_row(family, f"x{i}", "1x2", "2", odd, "lost") for i in range(n_lost)])


def test_hit_and_gap_suppressed_below_n_floor(capsys):
    # At implied ~0.72 the SE at n=10 is ~14pp, so a 95% band is +-28pp: any gap smaller than that
    # is indistinguishable from noise. Printing it invites reading noise as signal.
    print_report(calibrate(_legs("main", 6, 4)), min_n=20)       # graded = 10
    out = capsys.readouterr().out
    row = [l for l in out.splitlines() if l.strip().startswith("main")][0]
    assert " 10 " in row                      # graded count is a fact -> still shown
    assert "60" not in row                    # 6/10 = 60% hit -> suppressed
    assert row.rstrip().endswith("-")         # gap suppressed
    assert "71" in row or "71." in row        # implied% is exact, not a sample estimate -> shown


def test_hit_and_gap_shown_at_or_above_n_floor(capsys):
    print_report(calibrate(_legs("main", 15, 10)), min_n=20)     # graded = 25
    row = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("main")][0]
    assert "60" in row                        # 15/25 = 60% hit -> shown
    assert not row.rstrip().endswith("-")     # gap shown


def test_n_floor_threshold_is_configurable(capsys):
    print_report(calibrate(_legs("main", 6, 4)), min_n=5)        # graded = 10, floor lowered
    row = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("main")][0]
    assert "60" in row, "a lowered floor must un-suppress the rate"


def test_n_floor_default_is_twenty(capsys):
    print_report(calibrate(_legs("main", 6, 4)))                 # no min_n passed
    row = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("main")][0]
    assert "60" not in row, "default floor of 20 must suppress a 10-leg family"


def test_n_floor_does_not_change_empty_family_or_add_aggregate(capsys):
    rows = _legs("main", 15, 10) + [_row("corners", "m", "Total corners", "Over 8.5", "1.4",
                                         "unsettleable")]
    print_report(calibrate(rows), min_n=20)
    out = capsys.readouterr().out
    corners = [l for l in out.splitlines() if l.strip().startswith("corners")][0]
    assert corners.count("-") >= 3            # zero-graded family still all "-", never 0%
    assert "No blended aggregate" in out      # existing rule intact
    assert not any(l.strip().startswith(("total", "TOTAL", "overall")) for l in out.splitlines())


def test_suppression_is_explained_when_it_fires(capsys):
    print_report(calibrate(_legs("main", 6, 4)), min_n=20)
    assert "n < 20" in capsys.readouterr().out
