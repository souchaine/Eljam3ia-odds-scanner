"""Per-family calibration of the settled backtest: is each market family winning at the rate its
odds imply?

Reads the per-leg log written by settle.py (output/backtest_legs.csv) and, for every market
family, compares the REAL hit rate (won / graded, where graded = won + lost; voids and
unsettleable legs are excluded) against the odds' IMPLIED rate (mean of 1/odd over the same graded
legs). The gap = hit% - implied% is the family's edge in percentage points: positive means the
1.25-1.50 legs in that family beat their break-even rate, negative means the margin ate them.

No blended aggregate is ever printed -- the gradeable subset is a biased sample of all legs, and
different families have very different sample sizes, so only per-family rows are meaningful
(invariant #7). `n` counts every leg occurrence; `distinct` counts unique (match, market,
selection) triples, so a small `distinct` warns that a big `n` is mostly pseudo-replication.

Usage:
    py calibrate.py [--legs output/backtest_legs.csv]
"""

import argparse
import csv
import sys
from pathlib import Path


def read_legs_csv(text: str) -> list[dict]:
    """Parse a backtest_legs.csv into a list of row dicts (values left as strings)."""
    return list(csv.DictReader(text.splitlines()))


def calibrate(rows: list[dict]) -> dict[str, dict]:
    """Aggregate per-leg rows into per-family calibration stats.

    Each family maps to {n, distinct, graded, won, hit_pct, implied_pct, gap}. hit_pct/implied_pct/
    gap are None when there is nothing to compute (no graded legs, or no graded leg with a valid
    odd), never a fabricated 0 -- an empty family must read as "no signal", not "0% hit".
    """
    acc: dict[str, dict] = {}
    distinct: dict[str, set] = {}
    for r in rows:
        fam = r.get("family", "") or "other"
        d = acc.setdefault(fam, {"n": 0, "graded": 0, "won": 0, "inv_sum": 0.0, "inv_n": 0})
        d["n"] += 1
        distinct.setdefault(fam, set()).add((r.get("match"), r.get("market"), r.get("selection")))
        verdict = r.get("verdict")
        if verdict in ("won", "lost"):
            d["graded"] += 1
            if verdict == "won":
                d["won"] += 1
            try:
                odd = float(r.get("odd") or 0)
            except ValueError:
                odd = 0.0
            if odd > 0:                       # a graded leg with no valid odd counts toward the
                d["inv_sum"] += 1.0 / odd     # hit rate but cannot contribute an implied prob
                d["inv_n"] += 1
    out: dict[str, dict] = {}
    for fam, d in acc.items():
        graded, inv_n = d["graded"], d["inv_n"]
        hit = 100.0 * d["won"] / graded if graded else None
        implied = 100.0 * d["inv_sum"] / inv_n if inv_n else None
        gap = (hit - implied) if (hit is not None and implied is not None) else None
        out[fam] = {"n": d["n"], "distinct": len(distinct[fam]), "graded": graded,
                    "won": d["won"], "hit_pct": hit, "implied_pct": implied, "gap": gap}
    return out


def _fmt_pct(v) -> str:
    return "   -" if v is None else f"{v:4.0f}"


def _fmt_gap(v) -> str:
    return "    -" if v is None else f"{v:+5.0f}"


DEFAULT_MIN_N = 20   # below this many graded legs, a family's hit rate is not reportable


def print_report(cal: dict[str, dict], min_n: int = DEFAULT_MIN_N) -> None:
    """Per-family table. Families with fewer than `min_n` graded legs report counts but NOT a rate.

    Why suppress: a family's hit% is a sample estimate. At an implied rate near 0.72 the standard
    error at n=10 is ~14pp, so a 95% band spans ~±28pp -- wider than any gap this project is trying
    to detect. Printing "60%" there reads as signal when it is noise, and a printed number is very
    hard to un-see. Counts (n / distinct / graded / won) are facts and stay; implied% is exact given
    the odds (not a sample estimate) and stays too; only hit% and gap -- the estimated quantities --
    are withheld until the sample can support them.
    """
    print("Per-family calibration (hit% = won/graded; implied% = mean 1/odd over graded legs; "
          "gap = hit - implied, in pts).")
    print("No blended aggregate: families differ in sample size and the gradeable subset is biased.\n")
    print(f"  {'family':<12} {'n':>5} {'distinct':>8} {'graded':>7} {'won':>5} "
          f"{'hit%':>5} {'impl%':>6} {'gap':>6}")
    suppressed = 0
    # sort by number of graded legs (the calibration signal), then by n
    for fam in sorted(cal, key=lambda k: (-cal[k]["graded"], -cal[k]["n"])):
        c = cal[fam]
        hit, gap = c["hit_pct"], c["gap"]
        if c["graded"] < min_n and hit is not None:
            hit = gap = None                     # too few graded legs to report a rate
            suppressed += 1
        print(f"  {fam:<12} {c['n']:>5} {c['distinct']:>8} {c['graded']:>7} {c['won']:>5} "
              f"{_fmt_pct(hit)} {_fmt_pct(c['implied_pct']):>6} {_fmt_gap(gap)}")
    if suppressed:
        print(f"\n  {suppressed} family/families show '-' for hit%/gap: n < {min_n} graded legs, "
              "where the sampling error is wider than any gap worth reading. Counts are shown; "
              "the rate is withheld until the sample supports it (--min-n to change).")
    total_graded = sum(c["graded"] for c in cal.values())
    if total_graded < 200:
        leg_word = "leg" if total_graded == 1 else "legs"
        print(f"\n  NOTE: only {total_graded} graded {leg_word} total — per-family n is small; "
              "accumulate several real settlements before drawing calibration conclusions.")


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):   # tolerate non-cp1252 names on Windows
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Per-family calibration of the settled backtest.")
    ap.add_argument("--legs", default="output/backtest_legs.csv",
                    help="per-leg backtest log written by settle.py")
    ap.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, dest="min_n",
                    help=f"minimum graded legs before a family's hit%%/gap is reported "
                         f"(default {DEFAULT_MIN_N}); below it, counts show but the rate does not")
    args = ap.parse_args()

    legs = Path(args.legs)
    if not legs.exists():
        print(f"per-leg backtest log not found: {legs}\n"
              "Run `py settle.py <betslips> --outcomes <scores.csv>` on real settlements first.")
        return 1
    rows = read_legs_csv(legs.read_text(encoding="utf-8-sig"))
    if not rows:
        print(f"{legs} has no leg rows yet.")
        return 1
    print_report(calibrate(rows), min_n=args.min_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
