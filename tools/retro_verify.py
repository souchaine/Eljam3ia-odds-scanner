"""Independent cross-check of the verified score cache, at a rate fixed in advance.

Slate 2 cross-checked 8 of 42 rows against a second source (~19%). That rate does not survive
hundreds of fixtures, and a verification rate that quietly decays toward zero as volume rises is
worse than a stated low one -- it looks like diligence while providing none. So the rule is set
here rather than discovered afterwards:

- 100% of ALIAS joins. Those matched only after orthographic folding, so they are where a wrong
  pairing can hide.
- A deterministic 5% random sample of exact joins, seeded so it is reproducible and cannot be
  re-rolled until it passes.

`--emit` prints the sample as JSON for the browser to look up on an independent source.
`--compare` reads what came back and reports the agreement rate, naming every disagreement.

A fixture the second source does not carry is reported as NOT CHECKED. It is never counted as
agreement -- that is the difference between a verification rate and a wish.

Usage:
    py tools/retro_verify.py --emit
    py tools/retro_verify.py --compare
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scores import normalize_key, qualifiers  # noqa: E402

SAMPLE_RATE = 0.05
SEED = 20260803


def load_cache(cache: Path) -> list[dict]:
    rows = []
    for f in sorted(cache.glob("*.csv")):
        for r in csv.DictReader(f.read_text(encoding="utf-8-sig").splitlines()):
            if r.get("match"):
                r["date"] = f.stem
                rows.append(r)
    return rows


def pick_sample(rows: list[dict]) -> list[dict]:
    alias = [r for r in rows if r.get("join") == "alias"]
    exact = [r for r in rows if r.get("join") != "alias"]
    rng = random.Random(SEED)
    k = max(1, round(len(exact) * SAMPLE_RATE)) if exact else 0
    return alias + rng.sample(exact, min(k, len(exact)))


def _key(name: str) -> tuple:
    parts = (name or "").split(" vs. ")
    if len(parts) != 2:
        return ()
    return (normalize_key(parts[0]), normalize_key(parts[1]),
            qualifiers(parts[0]), qualifiers(parts[1]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="output/scores_cache")
    ap.add_argument("--staging", default="output/.retro_staging")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()

    rows = load_cache(Path(args.cache))
    sample = pick_sample(rows)
    staging = Path(args.staging)

    if args.emit:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "verify_sample.json").write_text(
            json.dumps(sorted({r["date"] for r in sample})), encoding="utf-8")
        alias_n = sum(1 for r in sample if r.get("join") == "alias")
        print(f"verified rows: {len(rows)}")
        print(f"sample: {len(sample)}  (alias {alias_n} = 100%, "
              f"random {len(sample) - alias_n} of {len(rows) - alias_n} exact "
              f"= {100 * (len(sample) - alias_n) / max(len(rows) - alias_n, 1):.1f}%)")
        print(f"dates to look up: {len(set(r['date'] for r in sample))}")
        return 0

    if not args.compare:
        print("pass --emit or --compare")
        return 1

    ext = {}
    for f in sorted((staging / "verify").glob("*.json")):
        for m in json.loads(f.read_text(encoding="utf-8")):
            k = _key(f"{m['home']} vs. {m['away']}")
            if k:
                ext[k] = m
    agree, disagree, missing = 0, [], 0
    for r in sample:
        m = ext.get(_key(r["match"]))
        if not m or m.get("h") is None or m.get("a") is None:
            missing += 1
            continue
        if [int(m["h"]), int(m["a"])] == [int(r["home"]), int(r["away"])]:
            agree += 1
        else:
            disagree.append(f"{r['match']}  ours {r['home']}:{r['away']}  "
                            f"theirs {m['h']}:{m['a']}  [{r.get('comp')}]")
    checked = agree + len(disagree)
    print(f"sample: {len(sample)}   independently CHECKED: {checked}   "
          f"NOT CHECKED (second source lacks the fixture): {missing}")
    print(f"agreement: {agree}/{checked} "
          f"({100 * agree / checked if checked else 0:.1f}%)")
    print(f"achieved cross-check rate over the whole cache: "
          f"{100 * checked / max(len(rows), 1):.1f}%  (target 5% + all aliases)")
    if disagree:
        print("\nDISAGREEMENTS — every one must be resolved before loading:")
        for d in disagree:
            print(f"  {d}")
    else:
        print("\nno disagreements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
