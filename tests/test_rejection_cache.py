"""Caching rejections so the daily loop does not re-fetch its own failures forever.

Measured 2026-08-04: of 212 fixtures fetched, only 33 were new. The other 179 were fixtures that
had already failed validation on a previous run and were re-fetched because rejections were not
recorded. That cost grows monotonically -- every run inherits every past failure -- and it is the
kind of drag that quietly ends up being the reason a loop stops being run.

The distinction that matters: a rejection is cached only when re-fetching CANNOT change it. A
shootout, a missing goal timeline or a self-contradictory report will read the same tomorrow. A
report that simply did not arrive is transient -- caching that would permanently discard a fixture
because of one throttled request.
"""
import pytest

from backlog import handled_fixtures, is_permanent_rejection, read_rejections, write_rejections


@pytest.mark.parametrize("reason", [
    "penalty shootout: the headline score is not the match result",
    "a non-goalless score with no goal events cannot be cross-checked",
    "half-time 1:0 disagrees with goal minutes (they give 0:0)",
    "full-time 4:5 disagrees with 2 goal event(s)",
    "no half-time score published; it is never inferred from full-time",
    "half-time exceeds full-time -- goals do not un-score",
])
def test_source_level_failures_are_permanent(reason):
    assert is_permanent_rejection(reason) is True


@pytest.mark.parametrize("reason", [
    "report not fetched",
    "not played / no result published (full-time reads None)",
])
def test_transient_failures_are_not_cached(reason):
    # a throttled fetch returns a page with no result, which validates as "not played". Caching it
    # would discard a real fixture permanently because of one bad request -- exactly the hollow-page
    # failure mode, made irreversible.
    assert is_permanent_rejection(reason) is False


def test_rejections_round_trip(tmp_path):
    write_rejections(tmp_path, {"A vs B": "penalty shootout: ...",
                                "C vs D": "report not fetched"})
    got = read_rejections(tmp_path)
    assert got == {"A vs B"}, "only the permanent one is remembered"


def test_rejections_accumulate_across_runs(tmp_path):
    write_rejections(tmp_path, {"A vs B": "penalty shootout: ..."})
    write_rejections(tmp_path, {"C vs D": "half-time 1:0 disagrees with goal minutes"})
    assert read_rejections(tmp_path) == {"A vs B", "C vs D"}


def test_a_fixture_that_later_succeeds_is_forgotten(tmp_path):
    write_rejections(tmp_path, {"A vs B": "penalty shootout: ..."})
    write_rejections(tmp_path, {}, succeeded={"A vs B"})
    assert read_rejections(tmp_path) == set(), (
        "a fixture that has since been scored must not stay on the reject list")


def test_read_rejections_on_a_missing_dir_is_empty(tmp_path):
    assert read_rejections(tmp_path / "nope") == set()


def test_handled_is_scored_plus_permanently_rejected(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "2026-08-03.csv").write_text(
        "match,home,away,ht_home,ht_away\nA vs B,1,0,0,0\n", encoding="utf-8")
    rej = tmp_path / "rejected"
    write_rejections(rej, {"C vs D": "penalty shootout: ..."})
    assert handled_fixtures(cache, rej) == {"A vs B", "C vs D"}


def test_handled_survives_missing_directories(tmp_path):
    assert handled_fixtures(tmp_path / "no_cache", tmp_path / "no_rej") == set()
