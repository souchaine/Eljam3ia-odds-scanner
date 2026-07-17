from settle import parse_betslips, read_outcomes_csv, grade_slip, settle_run, MatchOutcome

BETSLIPS = """Eljam3ia dual-set betslips - built 2026
window 1.25..1.5, 20 legs/slip

===== SET A: all-odds =====

BETSLIP A1  (2 legs, combined odds x2.00, win% 25)
   1. LigA - A vs. B - 1x2: 1 @ 1.40
   2. LigA - C vs. D - Total: Over 1.5 @ 1.40
  >> BOOKING CODE: AAA11

===== SET B: 7-category diversified =====

BETSLIP B1  (1 legs, combined odds x1.40, win% 71, families: corners x1)
   1. LigA - A vs. B - Total corners: Over 8.5 @ 1.40
  >> BOOKING CODE: BBB22
"""

OUTCOMES = "match,home,away\nA vs. B,2,1\nC vs. D,3,0\n"


def test_parse_betslips():
    slips = parse_betslips(BETSLIPS)
    assert [s["set"] for s in slips] == ["A", "B"]
    assert slips[0]["code"] == "AAA11" and slips[0]["pred_win_pct"] == 25.0
    assert len(slips[0]["legs"]) == 2
    assert slips[0]["legs"][0] == {"league": "LigA", "match": "A vs. B",
                                   "market": "1x2", "selection": "1", "odd": 1.40}


def test_read_outcomes_csv():
    out = read_outcomes_csv(OUTCOMES)
    assert out["A vs. B"] == MatchOutcome("A vs. B", 2, 1)


def test_grade_slip_won():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    assert grade_slip(slips[0], out) == "won"       # 1x2:1 won + Total Over1.5 (3>1.5) won


def test_grade_slip_ungradeable_on_stat_leg():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    assert grade_slip(slips[1], out) == "ungradeable"   # Total corners -> unsettleable


def test_grade_slip_ungradeable_when_outcome_missing():
    slips = parse_betslips(BETSLIPS)
    assert grade_slip(slips[0], {}) == "ungradeable"


def test_settle_run_tallies_trackers():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    r = settle_run(slips, out)
    assert r["A"] == {"won": 1, "gradeable": 1, "total": 1}
    assert r["B"] == {"won": 0, "gradeable": 0, "total": 1}


def test_parse_betslips_survives_malformed_numbers():
    text = ("===== SET A: all-odds =====\n"
            "BETSLIP A9  (1 legs, win% 1.4.0)\n"
            "   1. L - A vs. B - 1x2: 1 @ 1.4.0\n"
            "  >> BOOKING CODE: ZZZ99\n")
    slips = parse_betslips(text)          # must not raise
    assert slips[0]["pred_win_pct"] == 0.0
    assert len(slips[0]["legs"]) == 1     # leg kept, not silently dropped
    assert slips[0]["legs"][0]["odd"] == 0.0


def test_read_outcomes_csv_skips_malformed_rows():
    out = read_outcomes_csv("match,home,away\nA vs. B,2,1\nBad Row,x,y\nShort\n")
    assert "A vs. B" in out and "Bad Row" not in out and "Short" not in out


def test_read_outcomes_csv_reads_halftime_columns():
    out = read_outcomes_csv("match,home,away,ht_home,ht_away\nA vs. B,2,1,1,0\n")
    assert out["A vs. B"].ht_home == 1 and out["A vs. B"].ht_away == 0


def test_settle_run_reports_verdicts():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    r = settle_run(slips, out)
    assert r["verdicts"][0][:2] == ("A1", "won")
    assert r["verdicts"][1][:2] == ("B1", "ungradeable")


def test_all_void_slip_is_ungradeable():
    text = ("===== SET A: all-odds =====\n"
            "BETSLIP A8  (1 legs, win% 50)\n"
            "   1. L - A vs. B - Draw no bet: 1 @ 1.40\n"
            "  >> BOOKING CODE: VVV11\n")
    slips = parse_betslips(text)
    outcomes = read_outcomes_csv("match,home,away\nA vs. B,1,1\n")   # draw -> DNB voids
    assert grade_slip(slips[0], outcomes) == "ungradeable"


def test_won_legs_counts_individually_won_legs_even_when_ungradeable():
    text = ("===== SET A: all-odds =====\n"
            "BETSLIP A7  (2 legs, win% 10)\n"
            "   1. L - A vs. B - 1x2: 1 @ 1.40\n"
            "   2. L - C vs. D - Total corners: Over 8.5 @ 1.40\n"
            "  >> BOOKING CODE: WWW11\n")
    slips = parse_betslips(text)
    out = read_outcomes_csv("match,home,away\nA vs. B,2,1\nC vs. D,3,0\n")
    r = settle_run(slips, out)
    _label, verdict, _legs, won_legs, _gradeable_legs = r["verdicts"][0]
    assert verdict == "ungradeable"   # the corners leg cannot be graded
    assert won_legs == 1              # ...but the 1x2 leg genuinely won


def test_gradeable_legs_counts_only_score_gradeable_legs():
    text = ("===== SET A: all-odds =====\n"
            "BETSLIP A6  (2 legs, win% 10)\n"
            "   1. L - A vs. B - 1x2: 1 @ 1.40\n"
            "   2. L - C vs. D - Total corners: Over 8.5 @ 1.40\n"
            "  >> BOOKING CODE: GGG11\n")
    slips = parse_betslips(text)
    out = read_outcomes_csv("match,home,away\nA vs. B,2,1\nC vs. D,3,0\n")
    r = settle_run(slips, out)
    _label, verdict, legs, won_legs, gradeable_legs = r["verdicts"][0]
    assert legs == 2                 # two legs total
    assert gradeable_legs == 1       # only the 1x2 leg is score-gradeable
    assert won_legs == 1
    assert verdict == "ungradeable"  # the corners leg blocks a slip verdict
