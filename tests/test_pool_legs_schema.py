"""`kickoff_date` on the pool log, and the migration that makes adding it safe.

n_dates is a reported statistic, so the pool log has to carry a date. The danger is the append
path: `backtest_pool_legs.csv` already holds 1,475 rows written under the old 9-column header, and
appending 10-column rows to it would misalign EVERY retro row -- verdicts landing in the odd
column, odds in the selection column -- while still parsing as valid CSV. That is silent
corruption of the permanent record, so the writer refuses rather than guesses.
"""
import csv

import pytest

from settle import append_backtest_pool_legs, migrate_pool_legs_kickoff_date

POOL_HEADER = ["settled_at", "run_dir", "source", "match", "family", "market", "selection",
               "odd", "verdict", "kickoff_date"]
LEGACY_HEADER = POOL_HEADER[:-1]


def _rec(match="A vs B", verdict="won", odd=1.4, family="main"):
    return {"match": match, "family": family, "market": "1x2", "selection": "1",
            "odd": odd, "verdict": verdict}


def _rows(path):
    return list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))


def test_new_file_gets_the_kickoff_date_column(tmp_path):
    p = tmp_path / "pool.csv"
    append_backtest_pool_legs(p, "run_x", [_rec()], kickoff_dates={"A vs B": "2026-07-10"})
    rows = _rows(p)
    assert rows[0] == POOL_HEADER
    assert rows[1][-1] == "2026-07-10"


def test_missing_kickoff_date_is_blank_never_invented(tmp_path):
    p = tmp_path / "pool.csv"
    append_backtest_pool_legs(p, "run_x", [_rec()], kickoff_dates={})
    assert _rows(p)[1][-1] == "", "an unknown date must read as unknown, not as a plausible day"


def test_appending_to_a_legacy_header_refuses_instead_of_misaligning(tmp_path):
    p = tmp_path / "pool.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LEGACY_HEADER)
        w.writerow(["2026-08-01T00:00:00Z", "run_old", "pool", "X vs Y", "main", "1x2", "1",
                    "1.4", "won"])
    with pytest.raises(ValueError, match="kickoff_date"):
        append_backtest_pool_legs(p, "run_x", [_rec()], kickoff_dates={"A vs B": "2026-07-10"})
    assert len(_rows(p)) == 2, "a refused append must not have written a partial row"


def test_migration_adds_the_column_and_backfills_from_a_lookup(tmp_path):
    p = tmp_path / "pool.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LEGACY_HEADER)
        w.writerow(["2026-08-01T00:00:00Z", "run_old", "pool", "X vs Y", "main", "1x2", "1",
                    "1.4", "won"])
        w.writerow(["2026-08-01T00:00:00Z", "run_old", "pool", "Z vs W", "main", "1x2", "1",
                    "1.4", "lost"])
    n = migrate_pool_legs_kickoff_date(p, {"X vs Y": "2026-07-31"})
    rows = _rows(p)
    assert n == 2
    assert rows[0] == POOL_HEADER
    assert rows[1][-1] == "2026-07-31"
    assert rows[2][-1] == "", "a fixture with no known date is left blank, not back-filled wrongly"


def test_migration_is_idempotent(tmp_path):
    p = tmp_path / "pool.csv"
    append_backtest_pool_legs(p, "run_x", [_rec()], kickoff_dates={"A vs B": "2026-07-10"})
    before = p.read_text(encoding="utf-8-sig")
    assert migrate_pool_legs_kickoff_date(p, {"A vs B": "2026-07-11"}) == 0
    assert p.read_text(encoding="utf-8-sig") == before, "re-running must not rewrite live dates"


def test_migration_preserves_every_existing_value(tmp_path):
    p = tmp_path / "pool.csv"
    original = ["2026-08-01T00:00:00Z", "run_old", "pool", "X vs Y", "1st half",
                "1st half - 1x2", "1", "1.33", "void"]
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LEGACY_HEADER)
        w.writerow(original)
    migrate_pool_legs_kickoff_date(p, {})
    assert _rows(p)[1][:-1] == original, "migration must only ADD a column"


def test_append_after_migration_works(tmp_path):
    p = tmp_path / "pool.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LEGACY_HEADER)
        w.writerow(["2026-08-01T00:00:00Z", "run_old", "pool", "X vs Y", "main", "1x2", "1",
                    "1.4", "won"])
    migrate_pool_legs_kickoff_date(p, {"X vs Y": "2026-07-31"})
    append_backtest_pool_legs(p, "backlog_2026-07-10", [_rec()],
                              kickoff_dates={"A vs B": "2026-07-10"})
    rows = _rows(p)
    assert len(rows) == 3 and rows[2][1] == "backlog_2026-07-10" and rows[2][-1] == "2026-07-10"
