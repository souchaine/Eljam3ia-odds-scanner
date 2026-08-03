"""Odds-band calibration — the pre-registered favourite–longshot test.

The bands, the prediction and the decision rule were fixed in
`docs/superpowers/specs/2026-08-03-odds-window-widening-design.md` BEFORE any wide-window data
existed. These tests exist to keep them fixed: the bands are hard-coded so the analysis cannot be
re-cut until it passes, and a lone band clearing its interval without the monotone pattern must be
reported as a multiple-comparisons artifact rather than an edge.
"""
import pytest

from calibrate import (BANDS, band_of, calibrate_by_band, monotone_verdict,
                       print_band_report)


def _row(odd, verdict, match="m", date="2026-08-04", family="main", selection="1"):
    return {"family": family, "match": match, "market": "1x2", "selection": selection,
            "odd": str(odd), "verdict": verdict, "kickoff_date": date}


# ---- the bands are pre-registered and must not drift -------------------------------------------

def test_bands_are_exactly_the_pre_registered_seven():
    assert [f"{lo:.2f}-{hi:.2f}" for lo, hi in BANDS] == [
        "1.20-1.30", "1.30-1.40", "1.40-1.50", "1.50-1.75", "1.75-2.00", "2.00-2.50", "2.50-3.00"]


@pytest.mark.parametrize("odd,expected", [
    (1.20, "1.20-1.30"), (1.29, "1.20-1.30"), (1.30, "1.30-1.40"), (1.499, "1.40-1.50"),
    (1.50, "1.50-1.75"), (1.99, "1.75-2.00"), (2.00, "2.00-2.50"), (2.99, "2.50-3.00"),
])
def test_band_edges_are_half_open_low_inclusive(odd, expected):
    assert band_of(odd) == expected


@pytest.mark.parametrize("odd", [1.01, 1.19, 3.00, 4.5, 0, -1])
def test_odds_outside_the_registered_range_belong_to_no_band(odd):
    # 1.01-1.20 is COLLECTED but deliberately not analysed; re-analysing it later is post-hoc
    assert band_of(odd) is None


def test_rows_outside_the_bands_are_excluded_from_the_report():
    rows = [_row(1.10, "won"), _row(1.25, "won")]
    cal = calibrate_by_band(rows)
    assert "1.20-1.30" in cal
    assert all(c["graded"] == 0 for b, c in cal.items() if b != "1.20-1.30")


# ---- aggregation reuses the family logic -------------------------------------------------------

def test_band_stats_count_legs_matches_and_dates():
    rows = [_row(1.25, "won", match="a", date="2026-08-04"),
            _row(1.26, "lost", match="b", date="2026-08-04"),
            _row(1.27, "won", match="c", date="2026-08-05")]
    c = calibrate_by_band(rows)["1.20-1.30"]
    assert (c["graded"], c["matches"], c["dates"]) == (3, 3, 2)


def test_unsettleable_rows_do_not_count_as_graded():
    c = calibrate_by_band([_row(1.25, "unsettleable")])["1.20-1.30"]
    assert c["graded"] == 0 and c["roi_pct"] is None


def test_every_registered_band_appears_even_when_empty():
    cal = calibrate_by_band([_row(1.25, "won")])
    assert set(cal) == {f"{lo:.2f}-{hi:.2f}" for lo, hi in BANDS}, "an empty band shows, as '-'"


# ---- the decision rule ------------------------------------------------------------------------

def _band_stats(**by_band):
    """{band: (roi, band_halfwidth)} -> the shape monotone_verdict consumes."""
    return {b: {"roi_pct": r, "roi_band": h} for b, (r, h) in by_band.items()}


def test_no_band_above_zero_is_reported_as_no_edge():
    stats = _band_stats(**{"1.20-1.30": (-5.0, 2.0), "1.30-1.40": (-6.0, 2.0)})
    assert monotone_verdict(stats) == "no edge"


def test_a_lone_clearing_band_without_the_pattern_is_an_artifact():
    # a mid-range band clears while the short end does not -- exactly the multiple-comparisons
    # shape the pre-registration exists to reject
    stats = _band_stats(**{"1.20-1.30": (-6.0, 2.0), "1.30-1.40": (-7.0, 2.0),
                           "1.40-1.50": (+5.0, 2.0), "1.50-1.75": (-8.0, 2.0)})
    assert monotone_verdict(stats) == "artifact"


def test_a_clearing_short_band_with_the_declining_pattern_is_the_predicted_finding():
    stats = _band_stats(**{"1.20-1.30": (+4.0, 2.0), "1.30-1.40": (-1.0, 2.0),
                           "1.40-1.50": (-5.0, 2.0), "1.50-1.75": (-9.0, 2.0)})
    assert monotone_verdict(stats) == "predicted pattern"


def test_a_band_whose_interval_straddles_zero_does_not_clear():
    stats = _band_stats(**{"1.20-1.30": (+1.0, 3.0), "1.30-1.40": (-5.0, 2.0)})
    assert monotone_verdict(stats) == "no edge"


def test_bands_below_the_floors_are_ignored_by_the_verdict():
    # a withheld band must not participate at all -- neither creating a finding nor blocking one
    stats = _band_stats(**{"1.20-1.30": (-5.0, 2.0), "1.30-1.40": (-6.0, 2.0)})
    stats["2.50-3.00"] = {"roi_pct": None, "roi_band": None}
    assert monotone_verdict(stats) == "no edge"


def test_verdict_needs_two_qualifying_bands():
    assert monotone_verdict(_band_stats(**{"1.20-1.30": (+4.0, 2.0)})) == "insufficient"


# ---- the printed report ------------------------------------------------------------------------

def test_roi_band_is_clustered_on_match_day():
    # identical outcomes on every match-day -> no between-day variance -> a tight interval
    same = [_row(1.25, "won" if i % 4 else "lost", match=f"m{i}", date=f"2026-08-{4 + i // 4:02d}")
            for i in range(40)]
    tight = calibrate_by_band(same)["1.20-1.30"]["roi_band"]
    # one day wins everything, another loses everything -> the SAME leg count, far less certainty
    split = ([_row(1.25, "won", match=f"a{i}", date="2026-08-04") for i in range(20)]
             + [_row(1.25, "lost", match=f"b{i}", date="2026-08-05") for i in range(20)])
    wide = calibrate_by_band(split)["1.20-1.30"]["roi_band"]
    assert wide > tight, "clustering on match-day must widen when days disagree"


def test_roi_band_is_none_without_enough_clusters():
    one_day = [_row(1.25, "won", match=f"m{i}", date="2026-08-04") for i in range(30)]
    assert calibrate_by_band(one_day)["1.20-1.30"]["roi_band"] is None


def test_report_states_the_prediction_and_the_verdict(capsys):
    rows = ([_row(1.25, "won", match=f"a{i}", date=f"2026-08-{4 + i % 6:02d}") for i in range(25)]
            + [_row(1.25, "lost", match=f"b{i}", date=f"2026-08-{4 + i % 6:02d}")
               for i in range(15)])
    print_band_report(calibrate_by_band(rows))
    out = capsys.readouterr().out.lower()
    assert "lowest at short odds" in out, "the prediction must be printed WITH the table"
    assert "artifact" in out, "the multiple-comparisons rule must be visible next to the numbers"


def test_report_withholds_a_rate_below_the_floors(capsys):
    print_band_report(calibrate_by_band([_row(1.25, "won", match=f"m{i}") for i in range(4)]))
    row = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("1.20-1.30")][0]
    assert row.rstrip().endswith("-"), "4 legs on 4 matches cannot support a rate"
