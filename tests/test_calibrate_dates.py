"""n_dates: the third clustering level, reported so precision is under-claimed rather than over-.

Legs cluster inside matches -- that is why `matches` already gates the floors. Matches cluster
inside DATES too: on one match-day, market-wide pricing conditions are shared, so 1,600 fixtures
drawn from 22 dates are not 1,600 independent observations. The naive band computed from
n_matches is therefore too NARROW, and a too-narrow band is the dangerous direction: it turns
noise into a finding.
"""
from calibrate import calibrate, print_report


def _row(family, match, odd, verdict, date="2026-07-10", selection="1"):
    return {"family": family, "match": match, "market": "1x2", "selection": selection,
            "odd": odd, "verdict": verdict, "kickoff_date": date}


def test_calibrate_counts_distinct_dates_of_graded_legs():
    rows = [_row("main", "m1", "1.4", "won", "2026-07-10"),
            _row("main", "m2", "1.4", "lost", "2026-07-10"),
            _row("main", "m3", "1.4", "won", "2026-07-11")]
    assert calibrate(rows)["main"]["dates"] == 2


def test_ungraded_legs_do_not_contribute_a_date():
    rows = [_row("main", "m1", "1.4", "won", "2026-07-10"),
            _row("main", "m2", "1.4", "unsettleable", "2026-07-11")]
    assert calibrate(rows)["main"]["dates"] == 1


def test_missing_kickoff_date_is_not_counted_as_a_date():
    # a blank date is unknown, not a distinct day -- counting it inflates the independence claim
    rows = [_row("main", "m1", "1.4", "won", ""),
            _row("main", "m2", "1.4", "lost", "2026-07-11")]
    assert calibrate(rows)["main"]["dates"] == 1


def test_dates_is_zero_when_nothing_is_graded():
    assert calibrate([_row("corners", "m", "1.4", "unsettleable")])["corners"]["dates"] == 0


def test_rows_without_the_column_at_all_still_calibrate():
    # the slip log has no kickoff_date; calibrate must not crash on it
    rows = [{"family": "main", "match": "m", "market": "1x2", "selection": "1",
             "odd": "1.4", "verdict": "won"}]
    c = calibrate(rows)
    assert c["main"]["graded"] == 1 and c["main"]["dates"] == 0


def test_report_shows_a_dates_column(capsys):
    rows = [_row("main", f"m{i}", "1.4", "won" if i % 2 else "lost", f"2026-07-{10 + i % 4:02d}")
            for i in range(30)]
    print_report(calibrate(rows), min_n=20, min_matches=5)
    out = capsys.readouterr().out
    assert "dates" in out
    row = [line for line in out.splitlines() if line.strip().startswith("main")][0]
    assert " 4 " in row, "4 distinct match-days"


def test_report_warns_that_dates_widen_the_true_band(capsys):
    rows = [_row("main", f"m{i}", "1.4", "won" if i % 2 else "lost", "2026-07-10")
            for i in range(30)]
    print_report(calibrate(rows), min_n=20, min_matches=5)
    out = capsys.readouterr().out.lower()
    assert "dates" in out and "wider" in out, (
        "the report must say the true band is WIDER than the n_matches figure, so precision is "
        "under-claimed rather than over-claimed")
