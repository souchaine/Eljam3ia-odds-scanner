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
