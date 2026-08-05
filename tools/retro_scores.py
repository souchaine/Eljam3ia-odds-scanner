"""Validate staged match reports and write the per-date score cache.

Every row passes `scores.validate_report`, which requires the report to be internally consistent:
half-time must agree with the goal minutes, full-time with the goal count, no penalty shootout, no
missing half. That check is computed from data already fetched, so it costs nothing per row and
runs on 100% of them -- unlike an independent cross-check, it does not decay as volume rises.

A row that fails is REJECTED and reported, never repaired. A repaired row enters the permanent
record looking exactly like a verified one.

Usage:
    py tools/retro_scores.py --staging output/.retro_staging --cache output/scores_cache
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backlog import is_permanent_rejection, write_rejections  # noqa: E402
from scores import validate_report  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", default="output/.retro_staging")
    ap.add_argument("--cache", default="output/scores_cache")
    ap.add_argument("--rejected", default="output/scores_rejected",
                    help="where PERMANENT rejections are remembered so the worklist stops "
                         "re-fetching them every run")
    ap.add_argument("--write", action="store_true",
                    help="write the CSVs; without it, validate and report only")
    args = ap.parse_args()

    staging, cache = Path(args.staging), Path(args.cache)
    joinmap = json.loads((staging / "joinmap.json").read_text(encoding="utf-8"))

    reports = {}
    for f in sorted((staging / "reports").glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            reports[r["ma"]] = r

    by_date: dict[str, list] = {}
    rejected, reasons = [], Counter()
    joins = Counter()
    for ma, meta in joinmap.items():
        rep = reports.get(ma)
        if rep is None:
            reasons["report not fetched"] += 1
            rejected.append((meta["match"], "report not fetched"))
            continue
        ok, why = validate_report(rep.get("ft"), rep.get("ht"), rep.get("goals") or [],
                                  bool(rep.get("pso")))
        if not ok:
            reasons[why.split("(")[0].strip()] += 1
            rejected.append((meta["match"], why))
            continue
        fh, fa = (int(x) for x in rep["ft"].split(":"))
        hh, ha = (int(x) for x in rep["ht"].split(":"))
        by_date.setdefault(meta["day"], []).append(
            {"match": meta["match"], "home": fh, "away": fa, "ht_home": hh, "ht_away": ha,
             "join": meta["join"], "comp": meta["comp"], "ma": ma})
        joins[meta["join"]] += 1

    total = sum(len(v) for v in by_date.values())
    print(f"staged reports: {len(reports)}   joined fixtures: {len(joinmap)}")
    print(f"VERIFIED (self-consistent): {total}")
    print(f"REJECTED: {len(rejected)}")
    for why, n in reasons.most_common():
        print(f"  {n:>4}  {why}")
    print(f"\njoin type of verified rows: exact={joins['exact']}  alias={joins['alias']}")
    print(f"self-consistency check rate: {100.0 if len(reports) else 0:.0f}% "
          f"(every fetched report is validated; failures are rejected, not repaired)")

    if args.write:
        cache.mkdir(parents=True, exist_ok=True)
        for day, rows in sorted(by_date.items()):
            with (cache / f"{day}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["match", "home", "away", "ht_home", "ht_away", "join", "comp", "ma"])
                for r in sorted(rows, key=lambda x: x["match"]):
                    w.writerow([r["match"], r["home"], r["away"], r["ht_home"], r["ht_away"],
                                r["join"], r["comp"], r["ma"]])
        print(f"\nwrote {len(by_date)} date file(s) to {cache}")
        scored_now = {r["match"] for rows in by_date.values() for r in rows}
        total = write_rejections(args.rejected, dict(rejected), succeeded=scored_now)
        permanent = sum(1 for _, why in rejected if is_permanent_rejection(why))
        print(f"remembered {permanent} PERMANENT rejection(s) this run "
              f"({total} on the list); the rest are transient and will be retried")
    else:
        print("\n(dry run — pass --write to persist the cache)")

    if rejected:
        print("\nrejected sample:")
        for name, why in rejected[:15]:
            print(f"  {name}  ->  {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
