"""Join the backlog worklist to the staged match-report index, and emit the fetch list.

All matching happens here rather than in the browser: this is the logic that can silently produce
a plausible wrong number, so it lives in tested Python (`scores.py`, `tests/test_scores.py`) and
the browser is left as a dumb fetcher.

Usage:
    py tools/retro_join.py --output <kora>/output --staging <kora>/output/.retro_staging
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backlog import (already_loaded_triples, backlog_selections, canonical_kickoffs,  # noqa: E402
                     dedupe_selections, exclude_already_loaded, worklist_by_date)
from scores import Fixture, match_fixtures  # noqa: E402


def next_day(day: str) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in day.split("-"))
    return (date(y, m, d) + timedelta(days=1)).isoformat()


def load_index(staging: Path, day: str) -> list[Fixture]:
    f = staging / "index" / f"{day.replace('-', '')}.json"
    if not f.exists():
        return []
    return [Fixture(ma=r["ma"], comp=r["comp"], home=r["home"], away=r["away"], href=r["href"])
            for r in json.loads(f.read_text(encoding="utf-8"))]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="output")
    ap.add_argument("--staging", default="output/.retro_staging")
    ap.add_argument("--pool", default="output/backtest_pool_legs.csv")
    ap.add_argument("--cache", default="output/scores_cache")
    ap.add_argument("--finished-before", default="2026-08-03T06:00:00Z", dest="finished_before")
    args = ap.parse_args()

    staging = Path(args.staging)
    sels = exclude_already_loaded(dedupe_selections(backlog_selections(args.output)),
                                  already_loaded_triples(args.pool))
    days = canonical_kickoffs(sels)
    scored = set()
    cache = Path(args.cache)
    if cache.exists():
        import csv
        for f in cache.glob("*.csv"):
            for row in csv.DictReader(f.read_text(encoding="utf-8-sig").splitlines()):
                if row.get("match"):
                    scored.add(row["match"])
    wl = worklist_by_date(sels, scored, finished_before=args.finished_before)

    fetch, per_day, comps = [], [], Counter()
    tot = {"want": 0, "exact": 0, "alias": 0, "ambig": 0, "unmatched": 0}
    alias_examples, unmatched_examples, ambiguous_examples = [], [], []
    join_map = {}
    for day, names in wl.items():
        index = load_index(staging, day) + load_index(staging, next_day(day))
        r = match_fixtures(names, index)
        by_ma = {f.ma: f for f in index}
        for i, ma, comp in r["matched"]:
            fetch.append({"ma": ma, "href": by_ma[ma].href})
            join_map[ma] = {"match": names[i], "day": days.get(names[i], day), "comp": comp,
                            "join": "exact"}
            comps[comp] += 1
        for i, ma, comp, pair in r["aliased"]:
            fetch.append({"ma": ma, "href": by_ma[ma].href})
            join_map[ma] = {"match": names[i], "day": days.get(names[i], day), "comp": comp,
                            "join": "alias"}
            comps[comp] += 1
            if len(alias_examples) < 25:
                alias_examples.append(f"{names[i]}  ->  {pair}  [{comp}]")
        for i in r["unmatched"][:3]:
            if len(unmatched_examples) < 25:
                unmatched_examples.append(f"{day}  {names[i]}")
        for i in r["ambiguous"][:3]:
            if len(ambiguous_examples) < 15:
                ambiguous_examples.append(f"{day}  {names[i]}")
        per_day.append((day, len(names), len(r["matched"]), len(r["aliased"]),
                        len(r["ambiguous"]), len(r["unmatched"])))
        tot["want"] += len(names)
        tot["exact"] += len(r["matched"])
        tot["alias"] += len(r["aliased"])
        tot["ambig"] += len(r["ambiguous"])
        tot["unmatched"] += len(r["unmatched"])

    staging.mkdir(parents=True, exist_ok=True)
    (staging / "fetchlist.json").write_text(json.dumps(fetch), encoding="utf-8")
    (staging / "joinmap.json").write_text(json.dumps(join_map), encoding="utf-8")

    print(f"{'date':<12}{'want':>6}{'exact':>7}{'alias':>7}{'ambig':>7}{'unmatched':>11}")
    for row in per_day:
        print(f"{row[0]:<12}{row[1]:>6}{row[2]:>7}{row[3]:>7}{row[4]:>7}{row[5]:>11}")
    joined = tot["exact"] + tot["alias"]
    print(f"\n{'TOTAL':<12}{tot['want']:>6}{tot['exact']:>7}{tot['alias']:>7}"
          f"{tot['ambig']:>7}{tot['unmatched']:>11}")
    print(f"\njoined {joined}/{tot['want']} ({100 * joined / max(tot['want'], 1):.1f}%)  "
          f"-> {len(fetch)} match reports to fetch")
    print(f"alias joins: {tot['alias']} (each carries a 100% independent cross-check)")
    print(f"ambiguous (rejected, never guessed): {tot['ambig']}")
    if alias_examples:
        print("\nalias joins (sample):")
        for e in alias_examples:
            print(f"  {e}")
    if ambiguous_examples:
        print("\nambiguous, rejected (sample):")
        for e in ambiguous_examples:
            print(f"  {e}")
    if unmatched_examples:
        print("\nunmatched, skipped (sample):")
        for e in unmatched_examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
