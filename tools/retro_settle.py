"""Settle the retro backlog against the verified score cache.

Writes to whatever `--pool-out` names, so the default run lands in a THROWAWAY file: the join
report can be read before anything touches the permanent record. Pointing `--pool-out` at the real
log is the irreversible step and is never the default.

Rows are tagged `backlog_<kickoff-date>` rather than by run directory, because the match-day is the
natural slate unit -- 28 near-duplicate run columns would make `--by-run` unreadable, and retro
rows stay visibly distinct from live slates.

Usage:
    py tools/retro_settle.py --pool-out output/.retro_staging/pool_preview.csv
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backlog import (already_loaded_triples, backlog_selections, canonical_kickoffs,  # noqa: E402
                     dedupe_selections, exclude_already_loaded, purge_unsettleable)
from settle import (MatchOutcome, append_backtest_pool_legs, settle_pool)  # noqa: E402


def read_cache(cache: Path) -> dict[str, MatchOutcome]:
    out = {}
    for f in sorted(cache.glob("*.csv")):
        for r in csv.DictReader(f.read_text(encoding="utf-8-sig").splitlines()):
            if not r.get("match"):
                continue
            out[r["match"]] = MatchOutcome(r["match"], int(r["home"]), int(r["away"]),
                                           int(r["ht_home"]), int(r["ht_away"]))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="output")
    ap.add_argument("--cache", default="output/scores_cache")
    ap.add_argument("--pool", default="output/backtest_pool_legs.csv",
                    help="the LIVE log, read to avoid double-counting")
    ap.add_argument("--pool-out", default="output/.retro_staging/pool_preview.csv",
                    help="where to write; default is a throwaway preview")
    ap.add_argument("--commit", action="store_true",
                    help="required when --pool-out is the live log; also purges the stale "
                         "unsettleable rows the retro-load replaces")
    args = ap.parse_args()

    raw = dedupe_selections(backlog_selections(args.output))
    loaded = already_loaded_triples(args.pool)
    sels = exclude_already_loaded(raw, loaded)
    outcomes = read_cache(Path(args.cache))
    days = canonical_kickoffs(sels)

    scored = [s for s in sels if s["match"] in outcomes]
    recs = settle_pool(scored, outcomes)
    graded = [r for r in recs if r["verdict"] in ("won", "lost", "void")]

    triples = {(r["match"], r["market"], r["selection"]) for r in recs}
    assert len(triples) == len(recs), "duplicate triples reached settlement — dedupe failed"

    print(f"backlog triples after dedupe:            {len(raw)}")
    print(f"  already MEASURED in the live log:      {len(raw) - len(sels)}")
    print(f"  fixtures with a verified score:        {len({s['match'] for s in scored})}")
    print(f"  triples on those fixtures:             {len(scored)}")
    print(f"settled records:                         {len(recs)}")
    print(f"  graded (won/lost/void):                {len(graded)}")
    print(f"  distinct matches graded:               {len({r['match'] for r in graded})}")
    print(f"  distinct dates graded:                 "
          f"{len({days.get(r['match'], '') for r in graded} - {''})}")
    fam = Counter(r["family"] for r in graded)
    print("\ngraded legs by family:")
    for f, n in fam.most_common():
        print(f"  {n:>6}  {f}")

    out = Path(args.pool_out)
    is_live = out.resolve() == Path(args.pool).resolve()
    if is_live and not args.commit:
        print(f"\nREFUSING to write the live log without --commit: {out}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    if is_live:
        n = purge_unsettleable(out, triples)
        print(f"\npurged {n} stale unsettleable row(s) these observations replace")
    elif out.exists():
        out.unlink()

    by_day: dict[str, list] = {}
    for r in recs:
        by_day.setdefault(days.get(r["match"], "unknown"), []).append(r)
    for day, rows in sorted(by_day.items()):
        append_backtest_pool_legs(out, f"backlog_{day}", rows,
                                  kickoff_dates={r["match"]: day for r in rows})
    print(f"\nwrote {len(recs)} rows to {out} across {len(by_day)} match-day tag(s)")
    if not is_live:
        print("(preview only — the live log is untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
