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


# ---- Final-review fixes ------------------------------------------------------------------------

def test_market_family_both_halves_not_force_fit_into_2nd_half():
    # Fix 2: the unanchored "2nd\s*half" pattern was matching the substring inside "1st/2nd half
    # both teams to score", force-fitting a both-halves market into the "2nd half" family. It --
    # and the ungradeable "Both halves over/under N" shape -- need their own family.
    assert _market_family("1st/2nd half both teams to score") == "both halves"
    assert _market_family("Both halves over 1.5") == "both halves"
    # existing period-family classification must still hold
    assert _market_family("1st half - multigoals") == "1st half"
    assert _market_family("1st half corners") == "corners"
    assert _market_family("2nd half - handicap 1X2") == "2nd half"


def test_market_family_team_to_score_and_exact_goals_are_main():
    # Found by the build-time gate sweeping the FULL odds matrix: "1 to score" (x9), "2 to score"
    # (x9) and "2 exact goals" (x1) are gate-ELIGIBLE yet classified "other", because the main
    # pattern covered "[12] (total|clean sheet|odd/even)" but not to-score / exact-goals. The old
    # drift guard could not see it -- its fixture came from betslip legs, and the previous builder
    # never picked these markets. Under the settleable builder they ARE picked, so the latent
    # misclassification would start polluting `other` in the per-family calibration.
    assert _market_family("1 to score") == "main"
    assert _market_family("2 to score") == "main"
    assert _market_family("2 exact goals") == "main"
    assert _market_family("1 exact goals") == "main"
    # "both halves" is matched BEFORE main, so the both-halves variants are unaffected
    assert _market_family("1 to score in both halves") == "both halves"
    assert _market_family("2 to win both halves") == "both halves"
    # period families are also matched before main
    assert _market_family("1st half - 1 to score") == "1st half"
    # and a player market that merely contains "to score" still classifies as player
    assert _market_family("To score or assist Neymar") == "player"


def test_settle_run_reports_distinct_legs_smaller_than_n_when_repeated_across_slips():
    # Fix 4: n counts every leg occurrence (pseudo-replicated when the same leg is repeated across
    # slips); "distinct" must count unique (match, market, selection) triples instead.
    leg = {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4}
    other = {"league": "L", "match": "m", "market": "1x2", "selection": "2", "odd": 1.4}
    slips = [
        {"set": "A", "label": "A1", "code": "X", "pred_win_pct": 1.0, "legs": [dict(leg)]},
        {"set": "A", "label": "A2", "code": "Y", "pred_win_pct": 1.0, "legs": [dict(leg), dict(other)]},
    ]
    outcomes = {"m": MatchOutcome("m", 2, 1)}
    res = settle_run(slips, outcomes)
    fam = res["families"]["main"]
    assert fam["n"] == 3          # leg repeated twice + other once
    assert fam["distinct"] == 2   # only two unique (match, market, selection) triples
    assert fam["n"] > fam["distinct"]
    # existing keys must remain intact
    assert fam["gradeable"] == 3
    assert fam["won"] == 2
