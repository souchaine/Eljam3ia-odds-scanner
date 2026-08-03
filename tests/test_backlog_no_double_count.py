"""The retro-load must not double-count what the live slates already recorded.

`run_20260801_0900` sits in the backlog while `run_20260801_1007` is already settled, and they
share fixtures: 6,514 of 24,069 backlog triples (27%, across 681 fixtures) are already in
backtest_pool_legs.csv. Deduping only WITHIN the backlog misses all of them.

Two cases, treated differently on purpose:

- already loaded with a REAL verdict (won/lost/void) -> drop the backlog row. It is the same
  observation; re-adding it inflates `graded` and shrinks the error bars.
- already loaded as `unsettleable` -> that row carries NO measurement content (calibrate excludes
  it from hit%, implied% and roi entirely), so replacing it with a graded row for the same triple
  strictly adds information and cannot bias anything. The stale row is purged first, so the file
  never holds the triple twice.
"""
import csv

from backlog import already_loaded_triples, exclude_already_loaded, purge_unsettleable
from settle import POOL_LEGS_HEADER


def _sel(match, market, selection, run="runA", end="2026-07-10T08:00:00Z"):
    return {"league": "Premier League", "match": match, "market": market, "selection": selection,
            "odd": "1.4", "kickoff": "2026-07-10T18:00:00Z", "run": run, "scrape_end": end}


def _pool(tmp_path, *rows):
    p = tmp_path / "pool.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(POOL_LEGS_HEADER)
        for match, market, selection, verdict in rows:
            w.writerow(["2026-08-01T00:00:00Z", "run_old", "pool", match, "main", market,
                        selection, "1.4", verdict, "2026-07-10"])
    return p


def _triples(path):
    return [(r["match"], r["market"], r["selection"])
            for r in csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())]


def test_already_loaded_triples_reports_the_verdict(tmp_path):
    p = _pool(tmp_path, ("A vs B", "1x2", "1", "won"), ("C vs D", "1x2", "1", "unsettleable"))
    loaded = already_loaded_triples(p)
    assert loaded[("A vs B", "1x2", "1")] == "won"
    assert loaded[("C vs D", "1x2", "1")] == "unsettleable"


def test_already_loaded_triples_on_a_missing_file_is_empty(tmp_path):
    assert already_loaded_triples(tmp_path / "nope.csv") == {}


def test_a_graded_triple_is_dropped_from_the_backlog(tmp_path):
    p = _pool(tmp_path, ("A vs B", "1x2", "1", "won"))
    out = exclude_already_loaded([_sel("A vs B", "1x2", "1")], already_loaded_triples(p))
    assert out == [], "re-adding a graded observation inflates `graded` and narrows the band"


def test_a_void_triple_counts_as_graded_and_is_dropped(tmp_path):
    p = _pool(tmp_path, ("A vs B", "Total", "Over 2", "void"))
    out = exclude_already_loaded([_sel("A vs B", "Total", "Over 2")], already_loaded_triples(p))
    assert out == [], "a void is a real settlement outcome, not a gap to be refilled"


def test_an_unsettleable_triple_is_kept_for_upgrade(tmp_path):
    p = _pool(tmp_path, ("A vs B", "1x2", "1", "unsettleable"))
    out = exclude_already_loaded([_sel("A vs B", "1x2", "1")], already_loaded_triples(p))
    assert len(out) == 1, "an unsettleable row is a non-measurement; a graded row strictly improves it"


def test_an_unseen_triple_is_kept(tmp_path):
    p = _pool(tmp_path, ("A vs B", "1x2", "1", "won"))
    out = exclude_already_loaded([_sel("X vs Y", "1x2", "1")], already_loaded_triples(p))
    assert len(out) == 1


def test_purge_removes_only_the_named_unsettleable_rows(tmp_path):
    p = _pool(tmp_path,
              ("A vs B", "1x2", "1", "unsettleable"),
              ("A vs B", "Total", "Over 2.5", "unsettleable"),
              ("C vs D", "1x2", "1", "won"))
    n = purge_unsettleable(p, {("A vs B", "1x2", "1")})
    assert n == 1
    assert _triples(p) == [("A vs B", "Total", "Over 2.5"), ("C vs D", "1x2", "1")]


def test_purge_never_removes_a_graded_row(tmp_path):
    p = _pool(tmp_path, ("A vs B", "1x2", "1", "won"))
    assert purge_unsettleable(p, {("A vs B", "1x2", "1")}) == 0
    assert len(_triples(p)) == 1, "a real verdict is a measurement and is never deleted"


def test_purge_is_a_no_op_on_a_missing_file(tmp_path):
    assert purge_unsettleable(tmp_path / "nope.csv", {("A", "B", "C")}) == 0


def test_end_to_end_zero_duplicate_triples_survive_a_retro_load(tmp_path):
    """The invariant, end to end: purge + filtered append leaves no triple twice."""
    p = _pool(tmp_path,
              ("A vs B", "1x2", "1", "unsettleable"),   # upgradeable
              ("C vs D", "1x2", "1", "won"),            # already measured
              ("E vs F", "1x2", "1", "lost"))
    backlog = [_sel("A vs B", "1x2", "1"), _sel("C vs D", "1x2", "1"),
               _sel("E vs F", "1x2", "1"), _sel("G vs H", "1x2", "1")]
    loaded = already_loaded_triples(p)
    keep = exclude_already_loaded(backlog, loaded)
    assert {s["match"] for s in keep} == {"A vs B", "G vs H"}

    purge_unsettleable(p, {(s["match"], s["market"], s["selection"]) for s in keep})
    from settle import append_backtest_pool_legs
    append_backtest_pool_legs(p, "backlog_2026-07-10",
                              [{"match": s["match"], "family": "main", "market": s["market"],
                                "selection": s["selection"], "odd": 1.4, "verdict": "won"}
                               for s in keep],
                              kickoff_dates={s["match"]: "2026-07-10" for s in keep})
    triples = _triples(p)
    assert len(triples) == len(set(triples)), "zero duplicate triples may survive a retro-load"
    assert len(triples) == 4
