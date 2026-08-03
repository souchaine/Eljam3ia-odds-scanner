"""Per-slate view: does a family's gap SURVIVE the next slate, or reverse?

The combined table cannot answer this. Slate 1 reported htft at +28 gap / +39 roi; slate 2 put it
at -0.9. Averaging hides that -- the average of a fluke and a nothing is a small something. The
per-run view is what makes a reversal visible, so it is a first-class, floored report, not a
one-off script.
"""
from calibrate import calibrate, calibrate_by_run, print_run_comparison, sign_history


def _row(family, match, market, selection, odd, verdict, run="runA"):
    return {"run_dir": run, "family": family, "match": match, "market": market,
            "selection": selection, "odd": odd, "verdict": verdict}


def _spread(family, n_legs, n_matches, won_every, run, odd="1.4"):
    """n_legs graded legs over n_matches distinct matches, 1 in `won_every` won."""
    return [_row(family, f"{run}-m{i % n_matches}", "1x2", f"s{i}", odd,
                 "won" if i % won_every == 0 else "lost", run) for i in range(n_legs)]


# ---- partitioning ------------------------------------------------------------------------------

def test_by_run_partitions_and_each_slice_matches_plain_calibrate():
    rows = _spread("main", 30, 6, 2, "runA") + _spread("main", 30, 6, 3, "runB")
    by = calibrate_by_run(rows)
    assert set(by) == {"runA", "runB"}
    for run in ("runA", "runB"):
        expected = calibrate([r for r in rows if r["run_dir"] == run])
        assert by[run]["main"] == expected["main"], "a slice must be exactly calibrate() of it"


def test_rows_without_a_run_are_kept_under_a_named_key_not_dropped():
    rows = [{"family": "main", "match": "m", "market": "1x2", "selection": "1",
             "odd": "1.4", "verdict": "won"}]
    by = calibrate_by_run(rows)
    assert sum(c["main"]["graded"] for c in by.values()) == 1, "a legless run key must not lose data"


def test_family_absent_from_one_run_is_missing_there_not_zero():
    rows = _spread("main", 4, 4, 2, "runA") + _spread("htft", 4, 4, 2, "runB")
    by = calibrate_by_run(rows)
    assert "htft" not in by["runA"], "absent must be absent, never a fabricated 0% row"
    assert by["runB"]["htft"]["graded"] == 4


# ---- the reversal verdict ----------------------------------------------------------------------

def test_sign_history_flags_a_reversal():
    # runA: 24/30 won @1.4 (hit 80 vs implied 71 -> positive). runB: 10/30 (hit 33 -> negative).
    rows = _spread("htft", 30, 6, 1, "runA")[:24] + _spread("htft", 6, 6, 99, "runA")
    rows += _spread("htft", 30, 6, 3, "runB")
    assert sign_history(calibrate_by_run(rows), "htft") == "reversed"


def test_sign_history_flags_a_stable_sign():
    rows = _spread("main", 30, 6, 3, "runA") + _spread("main", 30, 6, 3, "runB")
    assert sign_history(calibrate_by_run(rows), "main") == "stable -"


def test_sign_history_is_insufficient_when_a_run_is_below_the_floors():
    # runB has plenty of matches but only 4 graded legs -- under the leg floor, so its sign is not
    # a fact and must not be used to claim a family "held" or "reversed".
    rows = _spread("main", 30, 6, 3, "runA") + _spread("main", 4, 4, 3, "runB")
    assert sign_history(calibrate_by_run(rows), "main") == "insufficient"


def test_sign_history_is_insufficient_for_a_single_run():
    # one slate can never establish that a gap survives; that is the whole point of the log
    rows = _spread("main", 30, 6, 3, "runA")
    assert sign_history(calibrate_by_run(rows), "main") == "insufficient"


# ---- the printed table -------------------------------------------------------------------------

def test_comparison_prints_a_column_per_run_and_withholds_below_floors(capsys):
    rows = _spread("main", 30, 6, 2, "runA") + _spread("main", 8, 8, 2, "runB")
    print_run_comparison(calibrate_by_run(rows))
    out = capsys.readouterr().out
    assert "runA" in out and "runB" in out
    row = [l for l in out.splitlines() if l.strip().startswith("main")][0]
    # runA clears both floors (30 legs / 6 matches) and prints a gap; runB (8 legs) must not
    assert row.count("-") >= 1
    assert "insufficient" in row, "a floored-out run cannot support a survival claim"


def test_comparison_never_prints_a_blended_aggregate(capsys):
    rows = _spread("main", 30, 6, 2, "runA") + _spread("htft", 30, 6, 3, "runB")
    print_run_comparison(calibrate_by_run(rows))
    out = capsys.readouterr().out
    assert not any(l.strip().startswith(("total", "TOTAL", "overall")) for l in out.splitlines())
    assert "No blended aggregate" in out


def test_comparison_explains_what_a_reversal_means(capsys):
    rows = _spread("htft", 30, 6, 1, "runA") + _spread("htft", 30, 6, 3, "runB")
    print_run_comparison(calibrate_by_run(rows))
    out = capsys.readouterr().out.lower()
    assert "reversed" in out and "noise" in out
