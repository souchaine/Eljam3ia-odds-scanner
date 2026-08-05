"""Daily betslips built OFFLINE from a scanned matrix — visible, and incapable of placing a bet.

The daily job runs `--skip-betslips` so it cannot mint a booking code. Slips are still wanted for
inspection, so they are built here from the matrix the scan already wrote: no second scan, no
network, and structurally no way to reserve anything.

The safety property is the point. `run_all.py` mints codes as part of building slips; this path
has no client, so "no codes" is not a flag that could be dropped but an absence of the capability.
"""
import pytest

from offline_betslips import build_from_matrix, render, selections_from_matrix

# Four markets in FOUR DISTINCT families — 1x2, Total and Both-teams-to-score all classify as
# `main`, so a matrix built from those cannot fill a 3-leg slip (distinct family per leg).
MATRIX = (
    "League,Match,Kickoff (UTC),1x2,1st half - 1x2,2nd half - 1x2,1 or over 2.5\n"
    "Premier League,A vs B,2099-01-01T18:00:00Z,1 @ 1.30,1 @ 1.45,1 @ 1.40,Yes @ 1.35\n"
    "Premier League,C vs D,2099-01-01T19:00:00Z,1 @ 1.28,1 @ 1.42,1 @ 1.38,Yes @ 1.33\n"
    "Premier League,E vs F,2099-01-01T20:00:00Z,1 @ 1.26,1 @ 1.44,1 @ 1.36,Yes @ 1.31\n"
    "Premier League,G vs H,2099-01-01T21:00:00Z,1 @ 1.29,1 @ 1.41,1 @ 1.37,Yes @ 1.34\n"
)


def _sel(**kw):
    return selections_from_matrix(MATRIX, lo=1.25, hi=1.50, now="2026-08-04T00:00:00Z", **kw)


def test_selections_are_within_the_window():
    sels = _sel()
    assert sels and all(1.25 <= s["price"] <= 1.50 for s in sels)


def test_selections_outside_the_window_are_dropped():
    text = MATRIX.replace("1 @ 1.30", "1 @ 2.60")
    sels = selections_from_matrix(text, lo=1.25, hi=1.50, now="2026-08-04T00:00:00Z")
    assert not any(s["price"] == 2.60 for s in sels)


def test_fixtures_that_already_kicked_off_are_dropped():
    # an odd scraped after kickoff is an IN-PLAY price, not a pre-match forecast
    sels = selections_from_matrix(MATRIX, lo=1.25, hi=1.50, now="2099-01-01T23:00:00Z")
    assert sels == []


def test_unnamed_competitions_are_dropped():
    text = MATRIX.replace("Premier League", "League 2932")
    assert selections_from_matrix(text, lo=1.25, hi=1.50, now="2026-08-04T00:00:00Z") == []


def test_slips_have_distinct_matches_and_families():
    slips = build_from_matrix(MATRIX, legs=3, slips=2, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    assert slips
    for slip in slips:
        assert len({s["match"] for s in slip}) == len(slip)
        assert len({s["family"] for s in slip}) == len(slip)


def test_only_complete_slips_are_emitted():
    slips = build_from_matrix(MATRIX, legs=3, slips=99, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    assert all(len(s) == 3 for s in slips), "a partial slip is never emitted"


def test_same_seed_reproduces_the_same_slips():
    a = build_from_matrix(MATRIX, legs=3, slips=2, lo=1.25, hi=1.50,
                          now="2026-08-04T00:00:00Z", seed=7)
    b = build_from_matrix(MATRIX, legs=3, slips=2, lo=1.25, hi=1.50,
                          now="2026-08-04T00:00:00Z", seed=7)
    assert [[x["match"] for x in s] for s in a] == [[x["match"] for x in s] for s in b]


def test_render_states_that_nothing_was_reserved():
    slips = build_from_matrix(MATRIX, legs=3, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    text = render(slips, legs=3, lo=1.25, hi=1.50, seed=1)
    assert "NO BOOKING CODE" in text.upper()
    assert "offline" in text.lower()


def test_render_shows_combined_odds_and_win_pct():
    slips = build_from_matrix(MATRIX, legs=3, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    text = render(slips, legs=3, lo=1.25, hi=1.50, seed=1)
    assert "combined odds x" in text and "win%" in text


def test_render_carries_the_measured_expectation():
    # the file must not read as a tip sheet: the measured per-leg ROI is negative and the reader
    # sees that on the same page as the picks
    slips = build_from_matrix(MATRIX, legs=3, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    text = render(slips, legs=3, lo=1.25, hi=1.50, seed=1)
    assert "-6.6" in text or "−6.6" in text


# ---- long slips: families must repeat, matches must not ----------------------------------------

LONG_MATRIX = "League,Match,Kickoff (UTC),1x2,1st half - 1x2,2nd half - 1x2,1 or over 2.5\n" + "".join(
    f"Premier League,T{i} vs U{i},2099-01-01T18:00:00Z,1 @ 1.30,1 @ 1.45,1 @ 1.40,Yes @ 1.35\n"
    for i in range(20))


def test_a_slip_longer_than_the_family_count_still_builds():
    # only four families exist in this matrix; a 10-leg slip therefore MUST repeat families
    slips = build_from_matrix(LONG_MATRIX, legs=10, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=3)
    assert slips and len(slips[0]) == 10


def test_matches_stay_distinct_however_long_the_slip():
    # THE correctness rule: two legs on one fixture resolve off the same scoreline, so the
    # combined odds would overstate the true win probability. Family repetition is cosmetic;
    # match repetition would make the printed win% a lie.
    slips = build_from_matrix(LONG_MATRIX, legs=12, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=5)
    slip = slips[0]
    assert len({s["match"] for s in slip}) == len(slip) == 12


def test_every_family_is_used_before_any_repeats():
    slips = build_from_matrix(LONG_MATRIX, legs=10, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=9)
    fams = [s["family"] for s in slips[0]]
    first_repeat = next(i for i in range(1, len(fams)) if fams[i] in fams[:i])
    assert len(set(fams[:first_repeat])) == first_repeat, (
        "diversity is spent before it is reused: no family repeats while an unused one remains")


def test_a_slip_longer_than_the_fixture_count_is_not_emitted():
    slips = build_from_matrix(MATRIX, legs=10, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=1)
    assert slips == [], "4 fixtures cannot support a 10-leg slip with distinct matches"


def test_render_shows_the_compounded_expectation_for_a_long_slip():
    from offline_betslips import MEASURED_LEG_ROI
    slips = build_from_matrix(LONG_MATRIX, legs=10, slips=1, lo=1.25, hi=1.50,
                              now="2026-08-04T00:00:00Z", seed=3)
    text = render(slips, legs=10, lo=1.25, hi=1.50, seed=3)
    expected = f"{100 * ((1 + MEASURED_LEG_ROI) ** 10 - 1):+.1f}"      # -49.5 at 10 legs
    assert expected in text, "a longer slip must show ITS compounded loss, not the 4-leg one"


def test_empty_matrix_renders_without_crashing():
    text = render([], legs=4, lo=1.25, hi=1.50, seed=1)
    assert "no slips" in text.lower()


@pytest.mark.parametrize("bad", ["", "League,Match\n", "not,a,matrix\n1,2,3\n"])
def test_malformed_matrix_yields_no_selections(bad):
    assert selections_from_matrix(bad, lo=1.25, hi=1.50, now="2026-08-04T00:00:00Z") == []
