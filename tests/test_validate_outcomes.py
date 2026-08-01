"""Pre-settlement validation of a hand-filled scores CSV.

A hand-filled CSV fails silently in ways settlement cannot flag: a mistyped match name simply never
joins, so its legs go `unsettleable` and the sample quietly shrinks. This runs BEFORE anything is
written and names the problems while they are still fixable.
"""
from settle import MatchOutcome, validate_outcomes

SLIPS = [{"set": "B", "label": "B1", "code": None, "pred_win_pct_floor": 1.0, "legs": [
    {"league": "L", "match": "A vs. B", "market": "1x2", "selection": "1", "odd": 1.4},
    {"league": "L", "match": "C vs. D", "market": "1st half - total", "selection": "Over 0.5", "odd": 1.4},
    {"league": "L", "match": "E vs. F", "market": "Total", "selection": "Over 2.5", "odd": 1.4},
]}]


def test_typo_in_a_match_name_is_reported_as_unjoined():
    # "A vs B" (missing the dot) is a realistic hand-entry slip: it joins nothing.
    outcomes = {"A vs B": MatchOutcome("A vs B", 2, 1, 1, 0)}
    r = validate_outcomes(SLIPS, outcomes)
    assert "A vs B" in r["unjoined_rows"], "a row matching no leg must be surfaced, not ignored"
    assert r["legs_affected_by_unjoined"] == 0        # it matched nothing, so it rescues nothing


def test_matches_with_no_score_row_are_reported_with_leg_counts():
    outcomes = {"A vs. B": MatchOutcome("A vs. B", 2, 1, 1, 0)}
    r = validate_outcomes(SLIPS, outcomes)
    assert set(r["missing_outcomes"]) == {"C vs. D", "E vs. F"}
    assert r["legs_ungradeable_from_missing"] == 2


def test_impossible_halftime_score_is_caught():
    # HT cannot exceed FT -- goals do not un-score. A transposition typo produces exactly this.
    outcomes = {"A vs. B": MatchOutcome("A vs. B", 1, 0, 2, 0),      # ht_home 2 > ft_home 1
                "C vs. D": MatchOutcome("C vs. D", 3, 1, 0, 2)}      # ht_away 2 > ft_away 1
    r = validate_outcomes(SLIPS, outcomes)
    assert set(r["impossible"]) == {"A vs. B", "C vs. D"}


def test_full_time_without_half_time_is_reported_with_the_cost():
    outcomes = {"A vs. B": MatchOutcome("A vs. B", 2, 1),            # no HT
                "C vs. D": MatchOutcome("C vs. D", 1, 0, 0, 0)}
    r = validate_outcomes(SLIPS, outcomes)
    assert r["ft_without_ht"] == ["A vs. B"]
    # the 1st-half leg belongs to C vs. D which HAS ht, so nothing is lost here
    assert r["legs_lost_to_missing_ht"] == 0


def test_missing_ht_costs_exactly_the_half_dependent_legs():
    outcomes = {"A vs. B": MatchOutcome("A vs. B", 2, 1, 1, 0),
                "C vs. D": MatchOutcome("C vs. D", 1, 0),            # no HT, and it owns a half leg
                "E vs. F": MatchOutcome("E vs. F", 3, 0, 1, 0)}
    r = validate_outcomes(SLIPS, outcomes)
    assert r["ft_without_ht"] == ["C vs. D"]
    assert r["legs_lost_to_missing_ht"] == 1, "the 1st-half leg on C vs. D cannot grade"


def test_clean_csv_reports_nothing_and_is_ok():
    outcomes = {"A vs. B": MatchOutcome("A vs. B", 2, 1, 1, 0),
                "C vs. D": MatchOutcome("C vs. D", 1, 0, 1, 0),
                "E vs. F": MatchOutcome("E vs. F", 3, 0, 1, 0)}
    r = validate_outcomes(SLIPS, outcomes)
    assert r["unjoined_rows"] == [] and r["missing_outcomes"] == []
    assert r["impossible"] == [] and r["ft_without_ht"] == []
    assert r["ok"] is True


def test_ok_is_false_when_anything_blocks():
    r = validate_outcomes(SLIPS, {"A vs. B": MatchOutcome("A vs. B", 1, 0, 2, 0)})
    assert r["ok"] is False
