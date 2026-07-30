import csv

from settle import (parse_betslips, read_outcomes_csv, grade_slip, settle_run, MatchOutcome,
                    append_backtest, append_backtest_legs, tracker_lines)

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
    assert slips[0]["code"] == "AAA11" and slips[0]["pred_win_pct_floor"] == 25.0
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
    assert slips[0]["pred_win_pct_floor"] == 0.0
    assert len(slips[0]["legs"]) == 1     # leg kept, not silently dropped
    assert slips[0]["legs"][0]["odd"] == 0.0


def test_read_outcomes_csv_notes_skipped_rows(capsys):
    out = read_outcomes_csv("match,home,away\nA vs. B,2,1\nBad Row,x,y\n")
    assert "A vs. B" in out and "Bad Row" not in out
    assert "malformed" in capsys.readouterr().err


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


def test_pred_win_pct_floor_is_named_for_what_it_is():
    """The per-slip predicted win% is P(ALL legs win). Settlement DROPS a void leg and re-prices, so
    the realised rate for push-capable slips runs ABOVE it -- the number is a FLOOR, not an estimate.
    The bare name `pred_win_pct` invited a future analysis to compare it against observed slip
    win-rate and read the difference as edge. The name now carries the semantics."""
    slips = parse_betslips(BETSLIPS)
    assert slips[0]["pred_win_pct_floor"] == 25.0
    assert "pred_win_pct" not in slips[0]


def test_append_backtest_header_names_the_floor_column(tmp_path):
    slips = parse_betslips(BETSLIPS)
    res = settle_run(slips, read_outcomes_csv(OUTCOMES))
    p = tmp_path / "backtest.csv"
    append_backtest(p, "run_x", slips, res)
    header = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))[0]
    assert "pred_win_pct_floor" in header
    assert "pred_win_pct" not in header


def test_tracker_lines_skip_sets_with_no_slips():
    """SET A no longer exists, so a run of SET-B-only slips must not emit a permanently-0/0 SET A
    line. A legacy file that DOES contain SET A slips must still report it."""
    b_only = settle_run([{"set": "B", "label": "B1", "code": "X", "pred_win_pct_floor": 1.0,
                          "legs": [{"league": "L", "match": "m", "market": "1x2",
                                    "selection": "1", "odd": 1.4}]}],
                        {"m": MatchOutcome("m", 2, 1)})
    lines = tracker_lines(b_only)
    assert not any("SET A" in ln for ln in lines)
    assert any("SET B" in ln for ln in lines)
    # ...and the caption must not hardcode the old 20-leg slip shape
    assert not any("20-leg" in ln for ln in lines)

    legacy = settle_run([{"set": "A", "label": "A1", "code": "X", "pred_win_pct_floor": 1.0,
                          "legs": [{"league": "L", "match": "m", "market": "1x2",
                                    "selection": "1", "odd": 1.4}]}],
                        {"m": MatchOutcome("m", 2, 1)})
    assert any("SET A" in ln for ln in tracker_lines(legacy))


def test_settle_run_returns_leg_records_aligned_with_verdicts():
    # per-leg records must be built from the SAME leg verdicts as the family tallies, so a
    # downstream per-leg backtest log can never disagree with the in-run per-family report.
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct_floor": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4},
        {"league": "L", "match": "m", "market": "Total corners", "selection": "Over 8.5", "odd": 1.5}]}]
    res = settle_run(slips, {"m": MatchOutcome("m", 2, 1)})
    recs = res["leg_records"]
    assert len(recs) == 2
    assert recs[0] == {"match": "m", "family": "main", "market": "1x2",
                       "selection": "1", "odd": 1.4, "verdict": "won"}
    assert recs[1]["family"] == "corners" and recs[1]["verdict"] == "unsettleable"


def test_append_backtest_legs_writes_header_and_one_row_per_leg(tmp_path):
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct_floor": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4},
        {"league": "L", "match": "m", "market": "Total corners", "selection": "Over 8.5", "odd": 1.5}]}]
    res = settle_run(slips, {"m": MatchOutcome("m", 2, 1)})
    p = tmp_path / "backtest_legs.csv"
    append_backtest_legs(p, "run_20260101_1200", res)
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == ["settled_at", "run_dir", "match", "family",
                       "market", "selection", "odd", "verdict"]
    assert len(rows) == 3                       # header + 2 legs
    assert rows[1][1:] == ["run_20260101_1200", "m", "main", "1x2", "1", "1.4", "won"]
    assert rows[2][3] == "corners" and rows[2][7] == "unsettleable"


def test_append_backtest_legs_appends_without_duplicating_header(tmp_path):
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct_floor": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4}]}]
    res = settle_run(slips, {"m": MatchOutcome("m", 2, 1)})
    p = tmp_path / "backtest_legs.csv"
    append_backtest_legs(p, "run_A", res)
    append_backtest_legs(p, "run_B", res)
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0][0] == "settled_at"           # single header
    assert [r[1] for r in rows[1:]] == ["run_A", "run_B"]


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
