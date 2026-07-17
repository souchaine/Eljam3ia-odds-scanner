from settle import MatchOutcome, grade_leg

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
