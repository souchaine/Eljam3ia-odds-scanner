from settle import MatchOutcome, grade_leg, _grade_score

O = MatchOutcome("A vs. B", 2, 1)          # FT 2-1
D = MatchOutcome("C vs. D", 1, 1)          # draw 1-1


def g(market, sel, o=O):
    return grade_leg(market, sel, o)


def test_1x2():
    assert g("1x2", "1") == "won"
    assert g("1x2", "2") == "lost"
    assert g("1x2", "Draw") == "lost"
    assert g("1x2", "Draw", D) == "won"


def test_total_goals():
    assert g("Total", "Over 2.5") == "won"     # 3 > 2.5
    assert g("Total", "Under 2.5") == "lost"
    assert g("Total", "Over 3") == "void"       # exactly 3 -> push
    assert g("Total", "Under 3.5") == "won"


def test_btts():
    assert g("Both Teams To Score", "Yes") == "won"
    assert g("Both Teams To Score", "No") == "lost"
    assert g("Both Teams To Score", "Yes", MatchOutcome("x", 2, 0)) == "lost"


def test_double_chance():
    assert g("Double chance", "1 or draw") == "won"
    assert g("Double chance", "Draw or 2") == "lost"
    assert g("Double chance", "1 or 2") == "won"


def test_correct_score():
    assert g("Correct score", "2:1") == "won"
    assert g("Correct score", "1:1") == "lost"


def test_multigoals():
    assert g("Multigoals", "1-3") == "won"      # 3 goals
    assert g("Multigoals", "4-6") == "lost"
    assert g("Multigoals", "0-1") == "lost"


def test_draw_no_bet():
    assert g("Draw no bet", "1") == "won"
    assert g("Draw no bet", "2") == "lost"
    assert g("Draw no bet", "1", D) == "void"


def test_handicap_goal():
    assert g("Handicap", "2 (+1.5)") == "won"     # away 1+1.5=2.5 vs 2 -> away covers
    assert g("Handicap", "1 (-1.5)") == "lost"    # home 2-1.5=0.5 vs 1 -> home fails
    assert g("Handicap", "2 (+1)") == "void"      # away 1+1=2 == home 2 -> push


def test_unsettleable_markets():
    for m in ["Total corners", "Total bookings", "1st half - total", "Total shots",
              "DC Halftime/ DC Fulltime", "Total & GG/NG", "Odd/even corners", "Total Offside"]:
        assert grade_leg(m, "Over 0.5", O) == "unsettleable"


def test_unknown_market_is_unsettleable():
    assert grade_leg("Some Novel Market", "Yes", O) == "unsettleable"


def test_never_raises_on_non_string_market_or_selection():
    assert grade_leg(123, "1", O) == "unsettleable"
    assert grade_leg("1x2", 456, O) in ("won", "lost", "unsettleable")
    assert grade_leg(None, None, O) == "unsettleable"


def test_total_unrecognized_selection_is_unsettleable():
    # must NOT be silently graded as an Under
    assert grade_leg("Total", "asdf 2.5", O) == "unsettleable"


def test_btts_unrecognized_selection_is_unsettleable():
    # must NOT be silently graded as a No
    assert grade_leg("Both Teams To Score", "asdf", O) == "unsettleable"


def test_handicap_trailing_garbage_is_unsettleable():
    assert grade_leg("Handicap", "1 (-1.5) extra", O) == "unsettleable"


def test_total_trailing_garbage_is_unsettleable():
    assert grade_leg("Total", "Over 2.5 asdf", O) == "unsettleable"


def test_btts_trailing_garbage_is_unsettleable():
    assert grade_leg("Both Teams To Score", "Yes please", O) == "unsettleable"


def test_grade_score_matches_grade_leg_for_ft_markets():
    # score core on (2,1) must equal the FT grade_leg behaviour
    assert _grade_score("1x2", "1", 2, 1) == "won"
    assert _grade_score("total", "Over 2.5", 2, 1) == "won"
    assert _grade_score("total", "Over 3", 2, 1) == "void"
    assert _grade_score("correct score", "2:1", 2, 1) == "won"
    assert _grade_score("multigoals", "1-3", 2, 1) == "won"
    assert _grade_score("handicap", "2 (+1.5)", 2, 1) == "won"


def test_double_chance_all_notations():
    for sel in ("1 or draw", "1X", "1/X"):
        assert _grade_score("double chance", sel, 2, 1) == "won"   # home win covers 1X
    for sel in ("1 or 2", "12", "1/2"):
        assert _grade_score("double chance", sel, 2, 1) == "won"
    for sel in ("draw or 2", "X2", "x/2"):
        assert _grade_score("double chance", sel, 2, 1) == "lost"


def test_team_total_and_clean_sheet_and_oddeven():
    assert _grade_score("1 total", "Over 1.5", 2, 1) == "won"      # home scored 2 > 1.5
    assert _grade_score("2 total", "Under 0.5", 2, 1) == "lost"    # away scored 1
    assert _grade_score("2 clean sheet", "No", 2, 1) == "won"      # away conceded 2 -> not clean
    assert _grade_score("1 clean sheet", "Yes", 2, 0) == "won"     # away scored 0 -> home clean
    assert _grade_score("odd/even", "Odd", 2, 1) == "won"          # 3 total -> odd
    assert _grade_score("2 odd/even", "Even", 2, 2) == "won"       # away 2 -> even


def test_grade_score_unknown_is_unsettleable():
    assert _grade_score("total corners", "Over 8.5", 2, 1) == "unsettleable"
    # NOTE: "1x2" does plain string equality (sel == res), not regex validation like
    # total/btts/handicap, so a garbage selection is "lost" not "unsettleable" -- this
    # is pre-existing behaviour, unchanged by this refactor (see task-1-report.md).
    assert _grade_score("1x2", "banana", 2, 1) == "lost"


HT = MatchOutcome("A vs. B", 2, 1, ht_home=1, ht_away=0)   # HT 1-0, FT 2-1
NOHT = MatchOutcome("A vs. B", 2, 1)                        # no half-time score


def test_half_multigoals():
    assert grade_leg("1st half - multigoals", "1-3", HT) == "won"   # 1 HT goal
    assert grade_leg("2nd half - multigoals", "1-3", HT) == "won"   # 2nd half = (2-1)+(1-0)=2
    assert grade_leg("2nd half - multigoals", "3-5", HT) == "lost"


def test_half_missing_ht_is_unsettleable():
    assert grade_leg("1st half - multigoals", "1-3", NOHT) == "unsettleable"


def test_half_clean_sheet_and_total():
    assert grade_leg("2nd half - 2 Clean sheet", "No", HT) == "won"   # home scored in 2nd half
    assert grade_leg("1st half - total", "Over 0.5", HT) == "won"     # 1 HT goal > 0.5


def test_half_stat_market_still_unsettleable():
    assert grade_leg("1st half - total bookings", "Over 0.5", HT) == "unsettleable"
    assert grade_leg("1st half - first corner", "1", HT) == "unsettleable"


def test_combo_dc_and_total():
    assert grade_leg("Double chance & total 5.5", "1/2 & under 5.5", HT) == "won"
    assert grade_leg("Double chance & total 1.5", "1/2 & under 1.5", HT) == "lost"   # 3 goals


def test_combo_dc_match_and_half_btts():
    # DC "12" (home won) AND 1st-half both-teams-score "no" (away 0 at HT -> not both) -> won/won
    assert grade_leg("Double chance (match) & 1st half both teams score", "12 & no", HT) == "won"


def test_combo_with_stat_component_is_unsettleable():
    assert grade_leg("1x2 & total corners", "1 & over 8.5", HT) == "unsettleable"


def test_combo_precedence_lost_beats_void():
    # total push (void) & DC lost -> lost
    assert grade_leg("Double chance & total 3", "x/2 & over 3", HT) == "lost"


def test_first_second_half_both_teams_to_score():
    # HT 1-0 (1st-half BTTS no), 2nd half 1-1 (BTTS yes) -> "No/no": 1st no=won, 2nd no=lost -> lost
    assert grade_leg("1st/2nd half both teams to score", "No/no", HT) == "lost"


def test_first_goal_scorer_combo_unsettleable():
    assert grade_leg("First goal & 1x2", "1 & 1", HT) == "unsettleable"


def test_ft_subtypes_through_grade_leg():
    # Task-1 FT sub-types, asserted through the public grade_leg entry point
    # (previously only exercised via _grade_score directly).
    assert grade_leg("1 Total", "Over 1.5", MatchOutcome("x", 2, 1)) == "won"
    assert grade_leg("2 Clean sheet", "No", MatchOutcome("x", 2, 1)) == "won"
    # 3 goals -> odd; only reachable now that the regex no longer blanket-catches odd/even
    assert grade_leg("Odd/Even", "Odd", MatchOutcome("x", 2, 1)) == "won"


def test_half_prefix_distributes_over_combo():
    o = MatchOutcome("x", 1, 1, ht_home=0, ht_away=1)   # 2nd half = 1-0
    assert grade_leg("2nd half - double chance & both teams to score", "12 & no", o) == "won"


def test_word_form_half_market():
    o = MatchOutcome("x", 2, 1, ht_home=1, ht_away=0)   # 1st half = 1-0
    assert grade_leg("First half - multigoals", "1-3", o) == "won"      # 1 HT goal
    assert grade_leg("Second half - total", "Over 0.5", o) == "won"     # 2nd half = 1-1 -> 2 goals


def test_three_part_combo():
    o = MatchOutcome("x", 2, 1)     # FT 2-1
    assert grade_leg("1x2 & total & both teams to score", "1 & over 2.5 & yes", o) == "won"
    assert grade_leg("1x2 & total & both teams to score", "1 & under 2.5 & yes", o) == "lost"


HTFT = MatchOutcome("A vs. B", 2, 1, ht_home=1, ht_away=0)   # FT 2-1, HT 1-0, 2nd half 1-1


def test_team_multigoals_all_three_selection_forms():
    o = MatchOutcome("x", 3, 0)
    assert grade_leg("1 multigoals", "1-3", o) == "won"      # home 3 in [1,3]
    assert grade_leg("1 multigoals", "1-2", o) == "lost"
    assert grade_leg("2 multigoals", "No goal", o) == "won"  # away scored 0
    assert grade_leg("1 multigoals", "No goal", o) == "lost"
    assert grade_leg("1 multigoals", "3+", o) == "won"       # home 3 >= 3
    assert grade_leg("1 multigoals", "4+", o) == "lost"
    assert grade_leg("1 multigoals", "banana", o) == "unsettleable"


def test_plain_multigoals_gains_open_ended_and_no_goal():
    o = MatchOutcome("x", 3, 1)                              # 4 total
    assert grade_leg("Multigoals", "4+", o) == "won"
    assert grade_leg("Multigoals", "5+", o) == "lost"
    assert grade_leg("Multigoals", "No goal", MatchOutcome("x", 0, 0)) == "won"
    assert grade_leg("Multigoals", "1-3", o) == "lost"       # existing form still works


def test_team_exact_goals_and_to_score_on_half():
    assert grade_leg("1st half - 1 exact goals", "1", HTFT) == "won"   # home 1 at HT
    assert grade_leg("1st half - 2 exact goals", "0", HTFT) == "won"   # away 0 at HT
    assert grade_leg("1st half - 2 exact goals", "1", HTFT) == "lost"
    assert grade_leg("1st half - 2 to score", "No", HTFT) == "won"     # away didn't score in H1
    assert grade_leg("1st half - 1 to score", "Yes", HTFT) == "won"


def test_handicap_1x2_direction_and_no_void():
    o = MatchOutcome("x", 2, 1)
    # (a:b) = home-start : away-start; leading token = bet side
    assert grade_leg("Handicap 1x2", "1 (1:0)", o) == "won"    # adj 3-1 -> 1
    assert grade_leg("Handicap 1x2", "2 (0:1)", o) == "lost"   # adj 2-2 -> Draw, so "2" loses
    assert grade_leg("Handicap 1x2", "2 (0:2)", o) == "won"    # adj 2-3 -> 2
    # equality is a Draw WIN, never a void (Gate 2)
    assert grade_leg("Handicap 1x2", "Draw (0:1)", o) == "won"  # adj 2-2 -> Draw
    assert grade_leg("Handicap 1x2", "1 (0:1)", o) == "lost"


def test_handicap_1x2_never_voids_unlike_asian_handicap():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Handicap 1x2", "1 (0:1)", o) != "void"
    assert grade_leg("Handicap", "2 (+1)", o) == "void"        # existing Asian market unchanged


def test_handicap_1x2_on_half():
    # 2nd half = 1-1; "1 (1:0)" -> adj 2-1 -> 1 -> won
    assert grade_leg("2nd half - handicap 1X2", "1 (1:0)", HTFT) == "won"
    assert grade_leg("2nd half - handicap 1X2", "2 (0:1)", HTFT) == "won"   # adj 1-2 -> 2


def test_htft_uses_cumulative_ft():
    # Gate 3: FT is cumulative. HT result 1, FT result 1 -> "1/1" won.
    # If FT were treated as 2nd-half-only (1,1) the FT result would be Draw -> lost.
    assert grade_leg("Halftime/fulltime", "1/1", HTFT) == "won"
    assert grade_leg("Halftime/fulltime", "1/X", HTFT) == "lost"
    assert grade_leg("Halftime/fulltime", "X/1", HTFT) == "lost"


def test_htft_dc_variant_and_missing_ht():
    o = MatchOutcome("x", 1, 2, ht_home=0, ht_away=1)   # HT 0-1 (away), FT 1-2 (away)
    assert grade_leg("DC Halftime/ DC Fulltime", "X2/X2", o) == "won"
    assert grade_leg("DC Halftime/ DC Fulltime", "1X/1X", o) == "lost"
    assert grade_leg("Halftime/fulltime", "1/1", MatchOutcome("x", 2, 1)) == "unsettleable"


def test_htft_total_combo_recurses():
    # combo wrapper already splits on " & "; each side graded independently
    assert grade_leg("Halftime/fulltime & total 2.5", "1/1 & over 2.5", HTFT) == "won"
    assert grade_leg("Halftime/fulltime & total 6.5", "1/1 & over 6.5", HTFT) == "lost"


def test_out_of_scope_markets_stay_unsettleable():
    for m, s in [("Shots - Neymar", "Over 0.5"), ("Saves goalkeeper (Jandrei)", "Over 2.5"),
                 ("To score or assist Neymar", "Over 0.5"), ("Total corners", "Over 8.5"),
                 ("Race to 5 corners", "1"), ("First scoring type", "Goal"),
                 ("A penalty in the match", "Yes"), ("Corner 1x2", "1 (1:0)"),
                 ("15 minutes - 1x2 from 0:00 to 14:59", "1"), ("Both halves over 1.5", "No")]:
        assert grade_leg(m, s, HTFT) == "unsettleable", m


def test_simple_or_market_carries_both_legs():
    o = MatchOutcome("x", 2, 1)                       # home win, 3 goals, no clean sheet
    assert grade_leg("Draw or under 1.5", "Yes", o) == "lost"   # neither
    assert grade_leg("1 or under 1.5", "Yes", o) == "won"       # home win satisfies
    assert grade_leg("Draw or over 2.5", "Yes", o) == "won"     # 3 > 2.5 satisfies
    assert grade_leg("2 or over 2.5", "Yes", o) == "won"


def test_simple_or_handles_no_as_negation():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("1 or under 1.5", "No", o) == "lost"       # OR is true -> "No" loses
    assert grade_leg("Draw or under 1.5", "No", o) == "won"     # OR is false -> "No" wins


def test_or_any_clean_sheet():
    assert grade_leg("2 or any clean sheet", "Yes", MatchOutcome("x", 2, 0)) == "won"   # home clean
    assert grade_leg("1 or any clean sheet", "Yes", MatchOutcome("x", 0, 2)) == "won"   # away clean
    assert grade_leg("Draw or any clean sheet", "Yes", MatchOutcome("x", 2, 1)) == "lost"


def test_or_both_teams_to_score():
    assert grade_leg("1 or both teams to score", "Yes", MatchOutcome("x", 2, 1)) == "won"
    assert grade_leg("2 or both teams to score", "Yes", MatchOutcome("x", 2, 0)) == "lost"


def test_compound_or_binds_selection_tokens_by_type_not_position():
    # market: "Both team to score or Total 2.5"; selection: "Under 2.5 or no"
    # NOTE the selection order is REVERSED vs the market name. Positional pairing would try to
    # grade BTTS with "Under 2.5" and Total with "no" -> must bind by TYPE.
    o = MatchOutcome("x", 1, 0)                        # 1 goal, BTTS no
    assert grade_leg("Both team to score or Total 2.5", "Under 2.5 or no", o) == "won"
    o2 = MatchOutcome("x", 2, 1)                       # 3 goals (over 2.5), BTTS yes
    assert grade_leg("Both team to score or Total 2.5", "Under 2.5 or no", o2) == "lost"
    assert grade_leg("Both team to score or Total 2.5", "Over 2.5 or yes", o2) == "won"


def test_or_combo_malformed_is_unsettleable():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Draw or under 1.5", "banana", o) == "unsettleable"
    assert grade_leg("1 or total corners", "Yes", o) == "unsettleable"   # stat component


# ---- Review fixes: OR-combos must never guess -----------------------------------------------

def test_or_unconsumed_selection_tokens_are_unsettleable():
    # Fix 1: both components are self-contained (bare result / embedded line), so neither calls
    # _take -- the selection tokens are never bound to anything and must not be silently dropped.
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Draw or under 1.5", "banana or split", o) == "unsettleable"
    assert grade_leg("1 or under 1.5", "over 9.5 or yes", o) == "unsettleable"


def test_or_void_component_is_unsettleable():
    # Fix 2: total == line is a push (void); folding void into "not won" silently defines push
    # behaviour as a loss. Must not guess -- push settlement inside an OR isn't defined.
    o = MatchOutcome("x", 1, 1)   # total 2 -- exact push on an integer line
    assert grade_leg("1 or over 2", "Yes", o) == "unsettleable"
    assert grade_leg("1 or under 2", "Yes", o) == "unsettleable"


def test_or_half_prefixed_market_stays_unsettleable():
    # Fix 3: a half-scoped OR market ("1st half - ...") must not fall into the OR branch and get
    # graded on the full-time score -- it's out of scope, like every other half-prefixed market.
    o = MatchOutcome("x", 2, 1, ht_home=0, ht_away=0)   # HT 0-0: BTTS no, Draw at HT
    assert grade_leg("1st half - both teams to score or 1", "Yes", o) == "unsettleable"


def test_or_half_scope_on_either_component_is_unsettleable():
    # Fix 6: the half-prefix check in _grade_or only anchored at position 0 of the whole market
    # string, so a half-scope sitting on the SECOND OR component (not the first) slipped through
    # and got graded on the full-time score. Must bail out per-component, not just whole-market.
    o = MatchOutcome("x", 2, 1, ht_home=0, ht_away=0)   # 1st half 0-0, FT 2-1
    assert grade_leg("1st half - both teams to score or 1", "Yes", o) == "unsettleable"
    assert grade_leg("1 or 1st half both teams to score", "Yes", o) == "unsettleable"
    assert grade_leg("2nd half - total 1.5 or draw", "Yes", o) == "unsettleable"
    assert grade_leg("draw or second half both teams to score", "Yes", o) == "unsettleable"


def test_or_same_type_components_are_ambiguous():
    # Fix 4: both components need a yes/no token -- there's no type signal to bind by, and the
    # provider grammar reverses selection order, so positional fallback would silently guess.
    o = MatchOutcome("x", 2, 0)
    assert grade_leg("Both team to score or any clean sheet", "no or yes", o) == "unsettleable"
    assert grade_leg("Both team to score or any clean sheet", "yes or no", o) == "unsettleable"


def test_compound_or_total_3_5_aligned_and_mixed_polarity():
    # Fix 5: lock the highest-volume real compound shape ("... or Total 3.5"), including the
    # mixed-polarity, reversed-order selections seen in real data ("Over 3.5 or no" / "Under 3.5
    # or yes"). Derivation: verdict = won iff EITHER component's bet, bound by type, wins.
    market = "Both team to score or Total 3.5"
    o_yes3 = MatchOutcome("x", 2, 1)   # BTTS yes, total 3
    o_no2 = MatchOutcome("x", 2, 0)    # BTTS no, total 2
    o_no4 = MatchOutcome("x", 4, 0)    # BTTS no, total 4
    # aligned order: BTTS token first, Total token second (matches market order)
    assert grade_leg(market, "Yes or Over 3.5", o_yes3) == "won"    # BTTS-yes bet hits
    assert grade_leg(market, "Yes or Over 3.5", o_no2) == "lost"    # BTTS-yes wrong; total 2 not >3.5
    assert grade_leg(market, "No or Under 3.5", o_no2) == "won"     # BTTS-no bet hits
    # mixed polarity, reversed order: Total token first, BTTS token second (real 12+1 leg shapes)
    assert grade_leg(market, "Over 3.5 or no", o_no2) == "won"      # BTTS-no bet hits
    assert grade_leg(market, "Over 3.5 or no", o_yes3) == "lost"    # BTTS-no wrong; total 3 not >3.5
    assert grade_leg(market, "Under 3.5 or yes", o_yes3) == "won"   # BTTS-yes bet hits
    assert grade_leg(market, "Under 3.5 or yes", o_no4) == "lost"   # BTTS-yes wrong; total 4 not <3.5


def test_any_clean_sheet_no_and_scoreless_draw():
    assert _grade_score("any clean sheet", "No", 2, 1) == "won"    # neither team kept a clean sheet
    assert _grade_score("any clean sheet", "Yes", 0, 0) == "won"   # 0-0: both kept a clean sheet
    assert _grade_score("any clean sheet", "No", 0, 0) == "lost"


def test_compound_or_token_type_mismatch_is_unsettleable():
    # a compound selection token that doesn't match its component's expected type/pattern.
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Both team to score or Total 2.5", "banana or no", o) == "unsettleable"


# ---- Final-review fixes ------------------------------------------------------------------------

def test_htft_validates_both_picks_before_deciding():
    # Fix 1: an unparseable HT/FT pick must be unsettleable regardless of scoreline. The old code
    # returned "lost" as soon as the FIRST pick mismatched, WITHOUT validating the second
    # (unparseable) pick -- so the exact same selection graded "lost" or "unsettleable" purely
    # depending on whether the first pick happened to already miss. Both scorelines below must
    # land on "unsettleable" for all three shapes.
    o_ht10 = MatchOutcome("x", 2, 1, ht_home=1, ht_away=0)   # HT 1-0
    o_ht01 = MatchOutcome("x", 2, 1, ht_home=0, ht_away=1)   # HT 0-1
    assert grade_leg("Halftime/fulltime", "2/QQQ", o_ht10) == "unsettleable"
    assert grade_leg("Halftime/fulltime", "2/QQQ", o_ht01) == "unsettleable"
    assert grade_leg("DC Halftime/ DC Fulltime", "X2/GARBAGE", o_ht10) == "unsettleable"
    assert grade_leg("DC Halftime/ DC Fulltime", "X2/GARBAGE", o_ht01) == "unsettleable"
    assert grade_leg("DC Halftime/ DC Fulltime", "1X/GARBAGE", o_ht10) == "unsettleable"
    assert grade_leg("DC Halftime/ DC Fulltime", "1X/GARBAGE", o_ht01) == "unsettleable"


def test_market_family_half_time_full_time_spelling():
    # Fix 5: grade_leg dispatches "half time/full time" (with spaces) to _grade_htft, so the
    # family classifier must recognize it too, instead of dumping it in "other".
    from settle import _market_family
    assert _market_family("Half time/Full time") == "htft"


def test_or_component_whitelist_rejects_loose_substring_matches():
    # Fix 3: _or_component_verdict used substring/prefix checks ("any clean sheet" in p, "both
    # team" in p, p.startswith("total")) which GRADE any unanticipated variant that merely
    # contains the keyword. Must whitelist (fullmatch) known component forms instead, so anything
    # unanticipated falls through to unsettleable.
    o = MatchOutcome("x", 2, 1)   # FT 2-1: BTTS yes, total 3
    assert grade_leg("Both teams to score in both halves or 1", "Yes", o) == "unsettleable"
    assert grade_leg("1 or 1st-half both teams to score", "Yes", o) == "unsettleable"
    assert grade_leg("2 or any clean sheet in the 1st half", "Yes", o) == "unsettleable"


def test_or_component_whitelist_still_grades_known_forms():
    # sanity: the whitelist must still accept the exact known forms it's meant to grade.
    o = MatchOutcome("x", 2, 1)   # FT 2-1: BTTS yes, total 3
    assert grade_leg("2 or any clean sheet", "Yes", MatchOutcome("x", 2, 0)) == "won"
    assert grade_leg("Both team to score or Total 2.5", "Under 2.5 or no", o) == "lost"
    assert grade_leg("1 or both teams to score", "Yes", o) == "won"


def test_market_family_goalscorer_or_substitute_is_player():
    # Fix 5: "Goalscorer OR the substitute to score - <player>" is a player market, but the bare
    # "or" in its name currently routes it into "or-combo" ahead of ever reaching the player check.
    from settle import _market_family
    assert _market_family("Goalscorer OR the substitute to score - Someone") == "player"
