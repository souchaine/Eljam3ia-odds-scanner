"""Build-time settleability gate: may a (market, selection) enter a betslip?

The gate is deliberately STRICTER than "grade_leg can grade this on some scoreline". At build time
the outcome is unknown, so eligibility must hold for EVERY outcome the slip could settle against --
otherwise a slip could be built that turns out ungradeable, which is exactly what the settleable
redesign exists to prevent.
"""
from pathlib import Path

from settle import REPRESENTATIVE_OUTCOMES, grade_leg, is_settleable, is_void_capable

VOCAB = Path(__file__).parent / "data" / "market_vocabulary.tsv"


def _vocab():
    rows = []
    for line in VOCAB.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        market, _, selection = line.partition("\t")
        rows.append((market, selection))
    return rows


def test_representative_outcomes_cover_ft_grid_with_every_ht_split():
    # all FT scorelines 0-4 x 0-4, each with every valid half-time split (ht <= ft)
    assert len(REPRESENTATIVE_OUTCOMES) == 225
    for o in REPRESENTATIVE_OUTCOMES:
        assert 0 <= o.home <= 4 and 0 <= o.away <= 4
        # LOAD-BEARING: half/HT-FT/both-halves markets are unsettleable without a half-time score,
        # so every representative outcome must supply one.
        assert o.ht_home is not None and o.ht_away is not None
        assert o.ht_home <= o.home and o.ht_away <= o.away
    assert len({(o.home, o.away, o.ht_home, o.ht_away) for o in REPRESENTATIVE_OUTCOMES}) == 225


def test_both_halves_integer_line_is_excluded():
    # grades won/lost on most scorelines, but an integer line landing exactly on a half's total is
    # a push we deliberately refuse to guess (-> unsettleable). Build time cannot know which, so
    # the market must not be selectable at all.
    assert is_settleable("Both halves over 2", "Yes") is False
    assert is_settleable("Both halves under 2", "Yes") is False
    # ...while a half-line both-halves market never pushes and stays eligible
    assert is_settleable("Both halves over 1.5", "Yes") is True


def test_plain_total_integer_line_is_included_because_void_is_a_real_verdict():
    # "Total"/"Over 2" returns void on total == 2. void is a settlement outcome (stake returned),
    # NOT a failure to grade -- so it stays eligible, unlike the both-halves integer line above.
    assert is_settleable("Total", "Over 2") is True
    assert any(grade_leg("Total", "Over 2", o) == "void" for o in REPRESENTATIVE_OUTCOMES)
    assert all(grade_leg("Total", "Over 2", o) != "unsettleable" for o in REPRESENTATIVE_OUTCOMES)


def test_stat_and_player_markets_are_excluded():
    for market, sel in [("Total corners", "Over 8.5"),
                        ("Total bookings", "Over 3.5"),
                        ("1st half - Both teams 2+ corners each", "No"),
                        ("Both teams 3+ bookings each", "No"),
                        ("Shots - Daouda Weidmann (TWE)", "Over 1.5"),
                        ("Saves Goalkeeper (Pedro Rangel) (incl. overtime)", "Over 2.5"),
                        ("Race to 5 corners", "1"),
                        ("15 minutes - 1x2 from 0:00 to 14:59", "1")]:
        assert is_settleable(market, sel) is False, market


def test_core_score_markets_are_included():
    for market, sel in [("1x2", "1"),
                        ("Double chance", "1 or draw"),
                        ("Both Teams To Score", "Yes"),
                        ("Multigoals", "1-3"),
                        ("1st half - total", "Over 0.5"),
                        ("2nd half - multigoals", "1-3"),
                        ("Halftime/fulltime", "1/1"),
                        ("DC Halftime/ 1X2 Fulltime", "1X/1"),
                        ("1 to score in both halves", "Yes")]:
        assert is_settleable(market, sel) is True, market


def test_unparseable_selection_is_excluded_not_raised():
    assert is_settleable("Total", "banana") is False
    assert is_settleable("Some Novel Market", "Yes") is False
    assert is_settleable(None, None) is False


def test_void_capable_flags_push_risk():
    # used to annotate slips: a push drops the leg and shortens the slip
    assert is_void_capable("Total", "Over 2") is True          # integer line can push
    assert is_void_capable("Total", "Over 2.5") is False       # half line never pushes
    assert is_void_capable("1x2", "1") is False


def test_grade_leg_never_raises_across_corpus_vocabulary():
    """Invariant #1 swept over the FULL real market vocabulary x every representative outcome.

    One test rather than a parametrized case per pair: this is ~6.5k pairs x 225 outcomes, and
    6.5k pytest IDs cost more in reporting overhead than the assertions do in compute.
    """
    vocab = _vocab()
    assert len(vocab) > 5000, "corpus vocabulary fixture looks truncated"
    allowed = {"won", "lost", "void", "unsettleable"}
    for market, selection in vocab:
        for o in REPRESENTATIVE_OUTCOMES:
            v = grade_leg(market, selection, o)          # must never raise
            assert v in allowed, f"{market!r}/{selection!r} -> {v!r}"
