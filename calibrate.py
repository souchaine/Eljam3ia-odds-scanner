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
import math
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
    matches: dict[str, set] = {}
    dates: dict[str, set] = {}
    for r in rows:
        fam = r.get("family", "") or "other"
        d = acc.setdefault(fam, {"n": 0, "graded": 0, "won": 0, "inv_sum": 0.0, "inv_n": 0})
        d["n"] += 1
        distinct.setdefault(fam, set()).add((r.get("match"), r.get("market"), r.get("selection")))
        matches.setdefault(fam, set())
        dates.setdefault(fam, set())
        verdict = r.get("verdict")
        if verdict in ("won", "lost"):
            matches[fam].add(r.get("match"))     # matches contributing GRADED legs
            day = (r.get("kickoff_date") or "").strip()
            if day:                              # blank = unknown, NOT a distinct day
                dates[fam].add(day)
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
                d["ret_sum"] = d.get("ret_sum", 0.0) + (odd if verdict == "won" else 0.0)
    out: dict[str, dict] = {}
    for fam, d in acc.items():
        graded, inv_n = d["graded"], d["inv_n"]
        hit = 100.0 * d["won"] / graded if graded else None
        implied = 100.0 * d["inv_sum"] / inv_n if inv_n else None
        gap = (hit - implied) if (hit is not None and implied is not None) else None
        # ROI: stake 1 unit on every graded leg with a valid odd; profit per unit staked. Voids are
        # a returned stake (EV 0) and unsettleable legs were never staked -- both excluded, keeping
        # ROI on the SAME leg set as hit% and implied%. This is the money answer: a family only
        # wins money long-run if roi > 0, which requires hit% ABOVE implied%, not a high hit%.
        roi = 100.0 * (d.get("ret_sum", 0.0) - inv_n) / inv_n if inv_n else None
        out[fam] = {"n": d["n"], "distinct": len(distinct[fam]), "matches": len(matches[fam]),
                    "dates": len(dates[fam]), "graded": graded, "won": d["won"], "hit_pct": hit,
                    "implied_pct": implied, "gap": gap, "roi_pct": roi}
    return out


def _fmt_pct(v) -> str:
    return "   -" if v is None else f"{v:4.0f}"


def _fmt_gap(v) -> str:
    return "    -" if v is None else f"{v:+5.0f}"


DEFAULT_MIN_N = 20        # below this many graded legs, a family's hit rate is not reportable
DEFAULT_MIN_MATCHES = 5   # ...and below this many distinct MATCHES it is not reportable either
# Why 5 matches: legs are NOT independent. Every leg on one fixture resolves off the same scoreline,
# so a family's effective sample size is bounded by its MATCH count, not its leg count. Below 5
# matches a single fixture contributes >20% of the observations and one scoreline can swing the
# whole "rate". Five is deliberately modest -- it is the floor at which the number stops being a
# description of three or four football matches.


def print_report(cal: dict[str, dict], min_n: int = DEFAULT_MIN_N,
                 min_matches: int = DEFAULT_MIN_MATCHES) -> None:
    """Per-family table. A family reports a RATE only when it clears BOTH floors:
    `graded >= min_n` legs AND `matches >= min_matches` distinct fixtures.

    Why suppress at all: hit% is a sample estimate. At an implied rate near 0.72 the standard error
    at n=10 is ~14pp, so a 95% band spans ~±28pp -- wider than any gap this project is trying to
    detect. Printing "60%" there reads as signal when it is noise, and a printed number is hard to
    un-see.

    Why matches bind: pool legs are heavily within-match correlated -- ~1,900 legs drawn from 22
    fixtures is nowhere near 1,900 independent observations. Gating on legs alone would let a
    2-fixture family with 300 legs print a confident-looking rate that is really two scorelines.

    Counts (n / distinct / matches / graded / won) are facts and stay. implied% is exact given the
    odds -- not a sample estimate -- and stays too. Only hit% and gap are withheld.
    """
    print("Per-family calibration (hit% = won/graded; implied% = mean 1/odd over graded legs; "
          "gap = hit - implied, in pts; roi% = flat-stake profit per unit).")
    print("No blended aggregate: families differ in sample size and the gradeable subset is biased.\n")
    print(f"  {'family':<12} {'n':>5} {'distinct':>8} {'matches':>7} {'dates':>5} {'graded':>7} "
          f"{'won':>5} {'hit%':>5} {'impl%':>6} {'gap':>6} {'roi%':>6}")
    few_legs = few_matches = 0
    # sort by number of graded legs (the calibration signal), then by n
    for fam in sorted(cal, key=lambda k: (-cal[k]["graded"], -cal[k]["n"])):
        c = cal[fam]
        hit, gap, roi = c["hit_pct"], c["gap"], c["roi_pct"]
        if hit is not None and (c["graded"] < min_n or c["matches"] < min_matches):
            if c["graded"] < min_n:
                few_legs += 1
            if c["matches"] < min_matches:
                few_matches += 1
            hit = gap = roi = None               # sample cannot support a rate
        print(f"  {fam:<12} {c['n']:>5} {c['distinct']:>8} {c['matches']:>7} "
              f"{c.get('dates', 0):>5} {c['graded']:>7} {c['won']:>5} {_fmt_pct(hit)} "
              f"{_fmt_pct(c['implied_pct']):>6} {_fmt_gap(gap)} {_fmt_gap(roi)}")
    if few_legs or few_matches:
        print(f"\n  hit%/gap withheld where the sample cannot support a rate "
              f"({few_legs} family/families under {min_n} graded legs, "
              f"{few_matches} under {min_matches} matches).")
        print("  Legs on the same fixture are CORRELATED -- they all resolve off one scoreline -- so "
              "the number of\n  distinct matches, not the number of legs, governs the error bars. "
              "(--min-n / --min-matches to change.)")
    if any(c.get("dates", 0) for c in cal.values()):
        print("\n  dates = distinct MATCH-DAYS contributing graded legs. Matches cluster inside "
              "dates: on one\n  match-day, market-wide pricing conditions are shared. So the true "
              "band is WIDER than the one\n  implied by `matches` alone — read every gap above as "
              "less precise than its match count suggests.")
    total_graded = sum(c["graded"] for c in cal.values())
    if total_graded < 200:
        leg_word = "leg" if total_graded == 1 else "legs"
        print(f"\n  NOTE: only {total_graded} graded {leg_word} total — per-family n is small; "
              "accumulate several real settlements before drawing calibration conclusions.")


# --- the pre-registered favourite-longshot test -------------------------------------------------
# Fixed in docs/superpowers/specs/2026-08-03-odds-window-widening-design.md BEFORE any wide-window
# data existed, and hard-coded here so the analysis cannot be re-cut until it passes. 1.01-1.20 is
# COLLECTED but deliberately not analysed; re-analysing it later is an explicitly post-hoc test.
BANDS = ((1.20, 1.30), (1.30, 1.40), (1.40, 1.50), (1.50, 1.75), (1.75, 2.00), (2.00, 2.50),
         (2.50, 3.00))

PREDICTION = ("Favourite-longshot bias predicts the margin is LOWEST at short odds and rises "
              "toward longshots,\n  so roi% should DECLINE as odds lengthen.")


def band_of(odd) -> str | None:
    """The pre-registered band containing `odd`, or None if it falls outside them.

    Half-open, low-inclusive, so a boundary price lands in exactly one band.
    """
    try:
        value = float(odd)
    except (TypeError, ValueError):
        return None
    for lo, hi in BANDS:
        if lo <= value < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return None


def calibrate_by_band(rows: list[dict]) -> dict[str, dict]:
    """Per-odds-band stats, using the same aggregation as the per-family report.

    Every registered band appears even when empty -- a band with no data must read as `-`, never be
    silently dropped, because a missing row is easy to mistake for a band that was never tested.
    """
    tagged = []
    for r in rows:
        b = band_of(r.get("odd"))
        if b is not None:
            tagged.append({**r, "family": b})
    out = calibrate(tagged)
    for band, cell in out.items():
        cell["roi_band"] = _cluster_roi_band(
            [r for r in tagged if r["family"] == band])
    empty = {"n": 0, "distinct": 0, "matches": 0, "dates": 0, "graded": 0, "won": 0,
             "hit_pct": None, "implied_pct": None, "gap": None, "roi_pct": None,
             "roi_band": None}
    for lo, hi in BANDS:
        out.setdefault(f"{lo:.2f}-{hi:.2f}", dict(empty))
    return out


def _cluster_roi_band(rows: list[dict]) -> float | None:
    """95% half-width on roi%, clustering on MATCH-DAY.

    Legs cluster inside matches and matches cluster inside dates: on one match-day, market-wide
    pricing conditions are shared. Treating legs as independent produces an interval far too narrow,
    and too narrow is the dangerous direction -- it turns noise into a finding. Returns None with
    fewer than two match-days, because a single day cannot bound its own variability.
    """
    days: dict[str, list[float]] = {}
    for r in rows:
        if r.get("verdict") not in ("won", "lost"):
            continue
        try:
            odd = float(r.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if odd <= 0:
            continue
        ret = odd if r["verdict"] == "won" else 0.0
        days.setdefault((r.get("kickoff_date") or "").strip() or "?", []).append(ret - 1.0)
    if len(days) < 2:
        return None
    vals = [(100 * sum(v) / len(v), len(v)) for v in days.values()]
    total = sum(w for _, w in vals)
    mean = sum(v * w for v, w in vals) / total
    var = sum(w * (v - mean) ** 2 for v, w in vals) / total
    return 1.96 * math.sqrt(var / (len(vals) - 1))


DEFAULT_MIN_DATES = 5
# Why a THIRD floor: the interval clusters on match-day, so match-days are its sample size. Floors
# on legs and matches do not constrain it. Found live -- 2.00-2.50 printed -61.3% +/- 8.7 off two
# match-days; the interval excludes zero and reads like a finding, but with one degree of freedom
# between clusters it estimates nothing.


def _band_reportable(c: dict, min_n: int, min_matches: int, min_dates: int) -> bool:
    return (c.get("gap") is not None and c.get("graded", 0) >= min_n
            and c.get("matches", 0) >= min_matches and c.get("dates", 0) >= min_dates)


def monotone_verdict(stats: dict[str, dict], min_dates: int = DEFAULT_MIN_DATES) -> str:
    """Apply the PRE-REGISTERED decision rule to per-band ROI intervals.

    A positive finding requires BOTH a band whose interval sits entirely above zero AND the
    predicted monotone shape, with the clearing band at the SHORT end. With 7 bands at 95%, a lone
    clearing band is roughly what chance produces every third run -- so without the pattern it is
    reported as an artifact, not an edge. This function exists so that rule cannot quietly soften.
    """
    order = [f"{lo:.2f}-{hi:.2f}" for lo, hi in BANDS]
    live = [(b, stats[b]) for b in order
            if b in stats and stats[b].get("roi_pct") is not None
            and stats[b].get("roi_band") is not None
            and stats[b].get("dates", min_dates) >= min_dates]
    if len(live) < 2:
        return "insufficient"
    clearing = [b for b, c in live if c["roi_pct"] - c["roi_band"] > 0]
    if not clearing:
        return "no edge"
    # predicted shape: roi declines as odds lengthen, and the clearing band is the shortest tested
    rois = [c["roi_pct"] for _, c in live]
    declining = rois[0] == max(rois) and rois[-1] == min(rois)
    return "predicted pattern" if (declining and clearing[0] == live[0][0]) else "artifact"


def print_band_report(cal: dict[str, dict], min_n: int = None, min_matches: int = None,
                      min_dates: int = DEFAULT_MIN_DATES) -> None:
    """Per-band table, printed WITH the prediction and the artifact rule.

    The rule sits next to the numbers on purpose: a tempting band is exactly when a reader stops
    scrolling to find the caveat.
    """
    min_n = DEFAULT_MIN_N if min_n is None else min_n
    min_matches = DEFAULT_MIN_MATCHES if min_matches is None else min_matches
    print("Per-odds-band calibration — the PRE-REGISTERED favourite-longshot test.")
    print(f"  {PREDICTION}\n")
    print(f"  {'band':<12} {'n':>6} {'matches':>8} {'dates':>6} {'graded':>7} {'won':>5} "
          f"{'hit%':>5} {'impl%':>6} {'gap':>6} {'roi%':>6}")
    for lo, hi in BANDS:
        b = f"{lo:.2f}-{hi:.2f}"
        c = cal.get(b, {})
        show = _band_reportable(c, min_n, min_matches, min_dates)
        print(f"  {b:<12} {c.get('n', 0):>6} {c.get('matches', 0):>8} {c.get('dates', 0):>5} "
              f"{c.get('graded', 0):>7} {c.get('won', 0):>5} "
              f"{_fmt_pct(c.get('hit_pct') if show else None)} "
              f"{_fmt_pct(c.get('implied_pct')):>6} {_fmt_gap(c.get('gap') if show else None)} "
              f"{_fmt_gap(c.get('roi_pct') if show else None)}")
    print("\n  DECISION RULE (fixed before the data existed): a positive finding needs BOTH a band "
          "whose\n  interval sits above zero AND the declining pattern, with the clearing band at "
          "the SHORT end.\n  A lone clearing band without the pattern is a multiple-comparisons "
          "ARTIFACT, not an edge —\n  with 7 bands at 95%, chance produces one about every third "
          "run.")
    print("  1.01-1.20 is collected but NOT analysed here; re-analysing it later is post-hoc.")
    print(f"  A band is withheld below {min_n} graded legs, {min_matches} matches OR {min_dates} "
          "MATCH-DAYS — the interval\n  clusters on match-day, so match-days are its sample size, "
          "not legs.")
    print(f"\n  VERDICT: {monotone_verdict(cal, min_dates)}")


NO_RUN = "(no run)"


def calibrate_by_run(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Same per-family stats as `calibrate`, but partitioned by the slate (`run_dir`) they came from.

    The combined table averages slates together, which is exactly where a fluke hides: the mean of
    a +28 and a -1 is a modest +11 that reads like a weak edge rather than the noise it is. A family
    that is absent from a slate is ABSENT from that slate's dict -- never a 0% row.
    """
    partitions: dict[str, list[dict]] = {}
    for r in rows:
        partitions.setdefault(r.get("run_dir") or NO_RUN, []).append(r)
    return {run: calibrate(rs) for run, rs in partitions.items()}


def _clears_floors(c: dict, min_n: int, min_matches: int) -> bool:
    """A slate's cell is reportable only under the same two floors the combined table uses."""
    return (c["gap"] is not None and c["graded"] >= min_n and c["matches"] >= min_matches)


def sign_history(by_run: dict[str, dict[str, dict]], family: str,
                 min_n: int = DEFAULT_MIN_N, min_matches: int = DEFAULT_MIN_MATCHES) -> str:
    """Did this family's gap keep its sign across slates? One of:

        "stable +" / "stable -"  every reportable slate agreed on the direction
        "reversed"               slates disagreed -- the gap is noise, whatever the combined row says
        "insufficient"           fewer than two slates clear the floors, so nothing can be claimed

    A slate under the floors is NOT evidence of anything, so it cannot be used to say a gap "held".
    This deliberately makes "insufficient" the common answer early on; that is the honest answer.
    """
    cells = [c[family] for c in by_run.values()
             if family in c and _clears_floors(c[family], min_n, min_matches)]
    if len(cells) < 2:
        return "insufficient"
    gaps = [c["gap"] for c in cells]
    if all(g >= 0 for g in gaps):
        return "stable +"
    if all(g <= 0 for g in gaps):
        return "stable -"
    return "reversed"


def print_run_comparison(by_run: dict[str, dict[str, dict]], min_n: int = DEFAULT_MIN_N,
                         min_matches: int = DEFAULT_MIN_MATCHES) -> None:
    """One row per family, one column per slate, plus whether the sign survived.

    Read this BEFORE the combined table. A family marked `reversed` has no edge, however good its
    combined gap looks -- it changed direction the moment new matches arrived.
    """
    families = sorted({f for c in by_run.values() for f in c},
                      key=lambda f: -sum(c.get(f, {}).get("graded", 0) for c in by_run.values()))
    print("Per-slate calibration — does a family's gap SURVIVE the next slate?")
    print("No blended aggregate: each slate is floored independently; slates under the floors are\n"
          "ignored as evidence rather than treated as disqualifying.\n")
    print(f"  {'family':<12}{'slates':>7}{'ok':>4}{'+':>4}{'-':>4}{'worst':>8}{'best':>7}"
          f"{'median':>8}  history")
    for fam in families:
        cells = [c[fam] for c in by_run.values() if fam in c]
        ok = [c for c in cells if _clears_floors(c, min_n, min_matches)]
        gaps = sorted(c["gap"] for c in ok)
        pos = sum(1 for g in gaps if g > 0)
        med = f"{gaps[len(gaps) // 2]:+.1f}" if gaps else "-"
        worst = f"{gaps[0]:+.1f}" if gaps else "-"
        best = f"{gaps[-1]:+.1f}" if gaps else "-"
        print(f"  {fam:<12}{len(cells):>7}{len(ok):>4}{pos:>4}{len(gaps) - pos:>4}"
              f"{worst:>8}{best:>7}{med:>8}  "
              f"{sign_history(by_run, fam, min_n, min_matches)}")
    print("\n  slates = slates containing the family; ok = those clearing BOTH floors "
          f"({min_n} graded legs\n  AND {min_matches} matches). +/- count the sign of the gap "
          "among those. A family that is\n  negative in most qualifying slates has no edge, "
          "however good one slate looked.")
    print("\n  reversed     = the sign flipped between slates; the gap is noise regardless of how "
          "the\n                 combined row reads. This is the column that falsifies an edge.")
    print("  insufficient = fewer than two slates clear both floors "
          f"({min_n} graded legs AND {min_matches} matches).")
    print("  stable +/-   = direction held so far. NOT significance — check the combined band too.")


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):   # tolerate non-cp1252 names on Windows
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Per-family calibration of the settled backtest.")
    ap.add_argument("--legs", default="output/backtest_legs.csv",
                    help="per-leg backtest log written by settle.py")
    ap.add_argument("--min-matches", type=int, default=DEFAULT_MIN_MATCHES, dest="min_matches",
                    help=f"minimum DISTINCT MATCHES before a family's hit%%/gap is reported "
                         f"(default {DEFAULT_MIN_MATCHES}); legs on one fixture are correlated, so "
                         f"matches govern the error bars")
    ap.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, dest="min_n",
                    help=f"minimum graded legs before a family's hit%%/gap is reported "
                         f"(default {DEFAULT_MIN_N}); below it, counts show but the rate does not")
    ap.add_argument("--by-band", action="store_true", dest="by_band",
                    help="ALSO run the PRE-REGISTERED favourite-longshot test over the fixed odds "
                         "bands, with the multiple-comparisons rule printed beside the numbers")
    ap.add_argument("--by-run", action="store_true", dest="by_run",
                    help="ALSO break the gaps out per slate and flag families whose sign reversed "
                         "-- the combined table averages a fluke and a nothing into a weak edge")
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
    if args.by_band:
        print_band_report(calibrate_by_band(rows), min_n=args.min_n,
                          min_matches=args.min_matches)
        print()
    if args.by_run:
        print_run_comparison(calibrate_by_run(rows), min_n=args.min_n, min_matches=args.min_matches)
        print()
    print_report(calibrate(rows), min_n=args.min_n, min_matches=args.min_matches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
