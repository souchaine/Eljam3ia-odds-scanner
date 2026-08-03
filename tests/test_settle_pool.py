"""Full-gated-pool settlement: every settleable selection on a slate, not just the slipped ones.

Calibration needs (market, selection, odd, verdict). Slip structure exists for BETTING and is
irrelevant to measurement, so a slate's ~1,900 gate-eligible selections settle against the same
scores CSV as its ~100 slipped legs -- a ~19x sample increase at zero elapsed time.

CONTAMINATION: a slipped leg is a BET; a pool leg is an OBSERVATION. They must never be silently
aggregated, so pool rows go to their OWN file with a `source` column that the slip schema lacks.
"""
import csv

from settle import (MatchOutcome, append_backtest_pool_legs, exclude_inplay, grade_leg,
                    read_odds_matrix, settle_pool, settle_run)

MATRIX = (
    "League,Match,Kickoff (UTC),Event ID,1x2,Total,Total corners,1st half - total\n"
    "LigA,A vs. B,2026-07-31T18:00:00Z,1,1 @ 1.40,Over 2.5 @ 1.45,Over 8.5 @ 1.30,Over 0.5 @ 1.35\n"
    "LigA,C vs. D,2026-07-31T18:00:00Z,2,2 @ 1.50,Under 3.5 @ 1.25,,\n"
)
OUTCOMES = {"A vs. B": MatchOutcome("A vs. B", 2, 1, ht_home=1, ht_away=0),
            "C vs. D": MatchOutcome("C vs. D", 0, 3, ht_home=0, ht_away=1)}


def test_read_odds_matrix_extracts_every_selection_cell():
    rows = read_odds_matrix(MATRIX)
    assert len(rows) == 6                                   # 4 + 2 populated cells
    a = [r for r in rows if r["match"] == "A vs. B" and r["market"] == "1x2"][0]
    assert a == {"league": "LigA", "match": "A vs. B", "market": "1x2",
                 "selection": "1", "odd": 1.40, "kickoff": "2026-07-31T18:00:00Z"}
    assert all(r["odd"] > 0 for r in rows)


def test_settle_pool_keeps_only_gate_eligible_selections():
    recs = settle_pool(read_odds_matrix(MATRIX), OUTCOMES)
    markets = {r["market"] for r in recs}
    assert "Total corners" not in markets, "stat market is not gate-eligible"
    assert {"1x2", "Total", "1st half - total"} <= markets


def test_settle_pool_verdicts_cannot_disagree_with_slip_verdicts():
    """The binding guarantee: pool and slip verdicts come from the SAME code path, so the same
    (match, market, selection) can never grade differently depending on which file it lands in."""
    slips = [{"set": "B", "label": "B1", "code": None, "pred_win_pct_floor": 1.0, "legs": [
        {"league": "LigA", "match": "A vs. B", "market": "1x2", "selection": "1", "odd": 1.40},
        {"league": "LigA", "match": "A vs. B", "market": "Total", "selection": "Over 2.5", "odd": 1.45},
        {"league": "LigA", "match": "C vs. D", "market": "1x2", "selection": "2", "odd": 1.50},
        {"league": "LigA", "match": "C vs. D", "market": "Total", "selection": "Under 3.5", "odd": 1.25},
    ]}]
    slip_recs = settle_run(slips, OUTCOMES)["leg_records"]
    pool_recs = settle_pool(read_odds_matrix(MATRIX), OUTCOMES)
    slip_by = {(r["match"], r["market"], r["selection"]): r["verdict"] for r in slip_recs}
    pool_by = {(r["match"], r["market"], r["selection"]): r["verdict"] for r in pool_recs}
    shared = set(slip_by) & set(pool_by)
    assert len(shared) == 4, "the four slipped legs must also appear in the pool"
    for k in shared:
        assert slip_by[k] == pool_by[k], f"{k}: slip={slip_by[k]} pool={pool_by[k]}"
    # and each equals a direct grade_leg call -- no third opinion exists
    for (m, mk, sel), v in pool_by.items():
        assert v == grade_leg(mk, sel, OUTCOMES[m])


def test_settle_pool_marks_missing_outcome_unsettleable():
    recs = settle_pool(read_odds_matrix(MATRIX), {})       # no scores at all
    assert recs and all(r["verdict"] == "unsettleable" for r in recs)


def test_pool_file_schema_is_incompatible_with_slip_file(tmp_path):
    """Contamination guard: the pool file carries a `source` column the slip file does not, so a
    naive concatenation of the two produces mismatched headers and fails loudly."""
    recs = settle_pool(read_odds_matrix(MATRIX), OUTCOMES)
    p = tmp_path / "backtest_pool_legs.csv"
    append_backtest_pool_legs(p, "run_x", recs)
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == ["settled_at", "run_dir", "source", "match", "family",
                       "market", "selection", "odd", "verdict", "kickoff_date"]
    assert "source" in rows[0] and "kickoff_date" in rows[0], (
        "the guard is that these columns do NOT exist in the slip schema, so concatenating the "
        "two files yields mismatched headers and fails loudly")
    assert all(r[2] == "pool" for r in rows[1:]), "every pool row self-identifies as an observation"
    assert len(rows) == len(recs) + 1


def test_append_backtest_pool_legs_appends_without_duplicating_header(tmp_path):
    recs = settle_pool(read_odds_matrix(MATRIX), OUTCOMES)
    p = tmp_path / "backtest_pool_legs.csv"
    append_backtest_pool_legs(p, "run_a", recs)
    append_backtest_pool_legs(p, "run_b", recs)
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert sum(1 for r in rows if r[0] == "settled_at") == 1
    assert {r[1] for r in rows[1:]} == {"run_a", "run_b"}


# ---- in-play contamination: odds scraped after kickoff are not pre-match predictions -----------

MATRIX_KO = (
    "League,Match,Kickoff (UTC),Event ID,1x2\n"
    "LigA,Early vs. Started,2026-07-24T18:00:00Z,1,1 @ 1.40\n"     # kicked off DURING the scan
    "LigA,Later vs. Clean,2026-07-25T20:00:00Z,2,1 @ 1.45\n"       # after the scan finished
    "LigA,No vs. Kickoff,,3,1 @ 1.50\n"                             # unknown -> cannot prove clean
)
SCAN_END = "2026-07-25T19:08:33Z"


def test_read_odds_matrix_carries_kickoff():
    rows = read_odds_matrix(MATRIX_KO)
    assert {r["match"]: r["kickoff"] for r in rows}["Early vs. Started"] == "2026-07-24T18:00:00Z"


def test_exclude_inplay_drops_fixtures_that_kicked_off_during_the_scan():
    """Odds scraped after kickoff are IN-PLAY prices: they encode information about a match already
    in progress, so their implied probability is not a pre-match prediction and would silently
    corrupt calibration. Found for real in run_20260724_1812, a 26-hour scan whose window spans its
    entire fixture list."""
    kept = exclude_inplay(read_odds_matrix(MATRIX_KO), SCAN_END)
    names = {r["match"] for r in kept}
    assert "Later vs. Clean" in names
    assert "Early vs. Started" not in names, "kickoff inside the scan window -> possibly in-play"


def test_exclude_inplay_is_conservative_about_unknown_kickoff():
    kept = exclude_inplay(read_odds_matrix(MATRIX_KO), SCAN_END)
    assert "No vs. Kickoff" not in {r["match"] for r in kept}, "cannot prove pre-match -> exclude"


def test_exclude_inplay_without_a_scrape_time_keeps_nothing():
    # no provenance -> nothing can be shown to be pre-match
    assert exclude_inplay(read_odds_matrix(MATRIX_KO), None) == []
