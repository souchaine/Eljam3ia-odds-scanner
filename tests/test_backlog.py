"""Backlog retro-settlement: the selection side.

The load-bearing test here is `test_no_duplicate_triples_survive`. 40% of backlog fixtures were
scraped in more than one run; appending them naively inflates `graded`, shrinks the error bars and
makes the calibration lie IN THE CONFIDENT DIRECTION. That is the worst way for a bug to fail --
a plausible number carrying unearned precision -- so the invariant is pinned by a test rather than
left to a script step.
"""
import pytest

from backlog import (backlog_selections, canonical_kickoffs, dedupe_selections,
                     is_named_competition, worklist_by_date)


def _sel(match, market, selection, odd="1.4", run="runA", end="2026-07-10T08:00:00Z",
         kickoff="2026-07-10T18:00:00Z", league="Premier League"):
    return {"league": league, "match": match, "market": market, "selection": selection,
            "odd": odd, "kickoff": kickoff, "run": run, "scrape_end": end}


# ---- the 29% exclusion: a numbered league cannot be competition-cross-checked -------------------

@pytest.mark.parametrize("league", ["League 2932", "League 11070", "League 11365", "  League 987 ",
                                    "", "   ", "2932"])
def test_unnamed_or_numbered_competitions_are_not_named(league):
    assert is_named_competition(league) is False


@pytest.mark.parametrize("league", ["Premier League", "UEFA Conference League", "League Cup",
                                    "Kolmonen", "U20 Paulista", "Primera B", "MLS Next Pro"])
def test_real_competition_names_are_named(league):
    assert is_named_competition(league) is True


def test_league_cup_is_not_mistaken_for_a_numbered_league():
    # "League Cup" and "League 2932" differ by one token; a sloppy prefix rule drops 49 real fixtures
    assert is_named_competition("League Cup") is True
    assert is_named_competition("League 2932") is False


# ---- dedupe: the invariant -----------------------------------------------------------------

def test_no_duplicate_triples_survive():
    rows = [_sel("A vs B", "1x2", "1", run="r1", end="2026-07-10T08:00:00Z"),
            _sel("A vs B", "1x2", "1", run="r2", end="2026-07-11T08:00:00Z"),
            _sel("A vs B", "1x2", "1", run="r3", end="2026-07-12T08:00:00Z"),
            _sel("A vs B", "1x2", "X", run="r1", end="2026-07-10T08:00:00Z")]
    out = dedupe_selections(rows)
    keys = [(r["match"], r["market"], r["selection"]) for r in out]
    assert len(keys) == len(set(keys)), "a duplicate triple must never survive a retro-load"
    assert len(out) == 2


def test_earliest_prematch_scrape_wins_not_latest_and_not_best_odds():
    # latest is closest to kickoff and therefore the best-informed price -- it leaks late
    # information into what is meant to be a pre-match forecast. best-odds is selection bias.
    rows = [_sel("A vs B", "1x2", "1", odd="1.30", run="late", end="2026-07-12T08:00:00Z"),
            _sel("A vs B", "1x2", "1", odd="1.45", run="early", end="2026-07-10T08:00:00Z"),
            _sel("A vs B", "1x2", "1", odd="1.50", run="mid", end="2026-07-11T08:00:00Z")]
    out = dedupe_selections(rows)
    assert len(out) == 1
    assert out[0]["run"] == "early"
    assert out[0]["odd"] == "1.45", "not the longest odd -- the earliest scrape"


def test_dedupe_is_deterministic_under_tied_scrape_times():
    rows = [_sel("A vs B", "1x2", "1", odd="1.4", run="rB", end="2026-07-10T08:00:00Z"),
            _sel("A vs B", "1x2", "1", odd="1.5", run="rA", end="2026-07-10T08:00:00Z")]
    first = dedupe_selections(rows)
    second = dedupe_selections(list(reversed(rows)))
    assert first == second, "input order must not change which row survives"


def test_dedupe_keeps_distinct_markets_and_matches():
    rows = [_sel("A vs B", "1x2", "1"), _sel("A vs B", "Total", "Over 2.5"),
            _sel("C vs D", "1x2", "1")]
    assert len(dedupe_selections(rows)) == 3


def test_dedupe_reports_nothing_when_given_nothing():
    assert dedupe_selections([]) == []


def test_rows_without_a_scrape_time_are_dropped_not_ranked_first():
    # a row whose scrape time is unknown cannot be shown to be pre-match; exclude_inplay already
    # takes that view, and dedupe must not smuggle such a row back in by sorting it to the top
    rows = [_sel("A vs B", "1x2", "1", run="unknown", end=None),
            _sel("A vs B", "1x2", "1", run="known", end="2026-07-11T08:00:00Z")]
    out = dedupe_selections(rows)
    assert len(out) == 1 and out[0]["run"] == "known"


# ---- worklist: resumability ----------------------------------------------------------------

def test_worklist_groups_fixtures_by_kickoff_date():
    rows = [_sel("A vs B", "1x2", "1", kickoff="2026-07-10T18:00:00Z"),
            _sel("C vs D", "1x2", "1", kickoff="2026-07-10T20:00:00Z"),
            _sel("E vs F", "1x2", "1", kickoff="2026-07-11T18:00:00Z")]
    wl = worklist_by_date(rows, already_scored=set())
    assert set(wl) == {"2026-07-10", "2026-07-11"}
    assert sorted(wl["2026-07-10"]) == ["A vs B", "C vs D"]


def test_worklist_shrinks_as_the_score_cache_fills():
    rows = [_sel("A vs B", "1x2", "1", kickoff="2026-07-10T18:00:00Z"),
            _sel("C vs D", "1x2", "1", kickoff="2026-07-10T20:00:00Z")]
    wl = worklist_by_date(rows, already_scored={"A vs B"})
    assert wl["2026-07-10"] == ["C vs D"], "a cached fixture is never re-fetched"


def test_worklist_drops_a_date_once_fully_scored():
    rows = [_sel("A vs B", "1x2", "1", kickoff="2026-07-10T18:00:00Z")]
    assert worklist_by_date(rows, already_scored={"A vs B"}) == {}


def test_worklist_excludes_fixtures_with_no_kickoff():
    rows = [_sel("A vs B", "1x2", "1", kickoff="")]
    assert worklist_by_date(rows, already_scored=set()) == {}


def test_one_fixture_never_appears_under_two_dates():
    # dedupe is per (match, market, selection), so different MARKETS of one fixture can survive
    # from different runs -- and a rescheduled kickoff means those rows disagree about the date.
    # Left alone this lists the fixture twice AND inflates n_dates, which is a reported statistic.
    rows = [_sel("A vs B", "1x2", "1", run="early", end="2026-07-09T08:00:00Z",
                 kickoff="2026-07-10T18:00:00Z"),
            _sel("A vs B", "Total", "Over 2.5", run="late", end="2026-07-10T08:00:00Z",
                 kickoff="2026-07-11T18:00:00Z")]
    wl = worklist_by_date(rows, already_scored=set())
    assert sum(len(v) for v in wl.values()) == 1, "one fixture, one date"
    assert wl == {"2026-07-10": ["A vs B"]}, "the earliest scrape's kickoff is canonical"


def test_canonical_kickoff_is_exposed_for_tagging_rows():
    rows = [_sel("A vs B", "1x2", "1", run="early", end="2026-07-09T08:00:00Z",
                 kickoff="2026-07-10T18:00:00Z"),
            _sel("A vs B", "Total", "Over 2.5", run="late", end="2026-07-10T08:00:00Z",
                 kickoff="2026-07-11T18:00:00Z")]
    assert canonical_kickoffs(rows) == {"A vs B": "2026-07-10"}


def test_worklist_excludes_fixtures_that_have_not_finished():
    # a fixture still in progress has no result; asking for one invites a guess
    rows = [_sel("A vs B", "1x2", "1", kickoff="2026-08-03T18:00:00Z"),
            _sel("C vs D", "1x2", "1", kickoff="2026-08-01T18:00:00Z")]
    wl = worklist_by_date(rows, already_scored=set(), finished_before="2026-08-03T09:00:00Z")
    assert wl == {"2026-08-01": ["C vs D"]}


def test_worklist_without_a_cutoff_keeps_everything():
    rows = [_sel("A vs B", "1x2", "1", kickoff="2027-01-01T18:00:00Z")]
    assert worklist_by_date(rows, already_scored=set()) != {}


# ---- walking the real directory layout -----------------------------------------------------

def _write_run(tmp_path, name, scraped, kickoff, league="Premier League"):
    d = tmp_path / name
    d.mkdir()
    (d / f"odds_matrix_today_{name}.csv").write_text(
        "League,Match,Kickoff (UTC),1x2\n"
        f'{league},A vs B,{kickoff},1 @ 1.40\n', encoding="utf-8")
    (d / f"odds_matrix_today_{name}_meta.csv").write_text(
        f"scraped_utc\n{scraped}\n", encoding="utf-8")
    return d


def test_backlog_selections_skips_settled_runs(tmp_path):
    _write_run(tmp_path, "run_1", "2026-07-10T08:00:00Z", "2026-07-10T18:00:00Z")
    _write_run(tmp_path, "run_2", "2026-07-10T09:00:00Z", "2026-07-10T18:00:00Z")
    out = backlog_selections(tmp_path, settled={"run_2"})
    assert {r["run"] for r in out} == {"run_1"}


def test_backlog_selections_drops_unnamed_competitions(tmp_path):
    _write_run(tmp_path, "run_1", "2026-07-10T08:00:00Z", "2026-07-10T18:00:00Z",
               league="League 2932")
    assert backlog_selections(tmp_path, settled=set()) == []


def test_backlog_selections_excludes_inplay_rows(tmp_path):
    # kickoff BEFORE the scrape finished -> an in-play price, not a pre-match forecast
    _write_run(tmp_path, "run_1", "2026-07-10T20:00:00Z", "2026-07-10T18:00:00Z")
    assert backlog_selections(tmp_path, settled=set()) == []


def test_backlog_selections_tags_rows_with_run_and_scrape_end(tmp_path):
    _write_run(tmp_path, "run_1", "2026-07-10T08:00:00Z", "2026-07-10T18:00:00Z")
    out = backlog_selections(tmp_path, settled=set())
    assert out and out[0]["run"] == "run_1"
    assert out[0]["scrape_end"].startswith("2026-07-10T08:00")
