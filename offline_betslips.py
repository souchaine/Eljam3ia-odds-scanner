"""Build the daily betslips OFFLINE, from the matrix the scan already wrote.

The daily job runs `--skip-betslips`, so the pipeline itself cannot mint a booking code. Slips are
still wanted for inspection, so they are rebuilt here from the scanned matrix: no second scan, no
network, no client — and therefore no way to reserve anything. "No codes" is not a flag that could
be dropped by accident; it is an absence of the capability.

Slips are drawn from the historical betting window (1.25–1.50 by default) even when the scan is
wider, so what you read each day stays comparable to everything already in the calibration log.

Usage:
    py offline_betslips.py --matrix output/run_X/odds_matrix_*.csv --out output/run_X/betslips.txt
"""

import argparse
import glob
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from backlog import is_named_competition
from make_betslips import build_settleable_slips
from settle import _market_family, is_settleable, is_void_capable, read_odds_matrix

# Measured 2026-08-04 over 9,793 graded observations / 505 matches: flat-stake return per leg,
# uniform across every family, odds band and market with enough data to test. Printed with the
# picks so the file cannot read as a tip sheet.
MEASURED_LEG_ROI = -0.066


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def selections_from_matrix(text: str, lo: float, hi: float, now=None) -> list[dict]:
    """Gate-eligible, pre-match, named-competition selections priced inside [lo, hi]."""
    cutoff = _parse(now) or datetime.now(timezone.utc)
    out = []
    try:
        rows = read_odds_matrix(text)
    except (ValueError, IndexError):
        return []
    for s in rows:
        ko = _parse(s.get("kickoff"))
        if ko is None or ko <= cutoff:          # already under way -> in-play, not a forecast
            continue
        if not is_named_competition(s.get("league", "")):
            continue
        if not is_settleable(s.get("market"), s.get("selection")):
            continue
        try:
            price = float(s["odd"])
        except (TypeError, ValueError, KeyError):
            continue
        if not lo <= price <= hi:
            continue
        out.append({"league": s["league"], "match": s["match"], "market_name": s["market"],
                    "label": s["selection"], "price": price, "kickoff": s.get("kickoff", ""),
                    "family": _market_family(s["market"])})
    return out


def build_from_matrix(text: str, legs: int, slips: int, lo: float, hi: float,
                      now=None, seed: int = 0) -> list[list[dict]]:
    """Slips from a matrix, using the SAME builder the live pipeline uses.

    Reusing `build_settleable_slips` rather than re-implementing it keeps the distinct-match and
    distinct-family guarantees identical to every slip already in the backtest, so today's file is
    comparable to the history rather than a lookalike.
    """
    sels = selections_from_matrix(text, lo, hi, now)
    pools: dict[str, list[dict]] = {}
    for s in sels:
        pools.setdefault(s["family"], []).append(s)
    return build_settleable_slips(pools, legs, slips, random.Random(seed))


def render(slips: list[list[dict]], legs: int, lo: float, hi: float, seed: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    out = [f"OFFLINE BETSLIPS — {stamp}Z",
           f"window {lo:g}..{hi:g}, {legs} legs/slip, seed {seed}",
           "",
           "*** NO BOOKING CODE WAS MINTED. Nothing here is reserved or staked. ***",
           "Built offline from the scanned matrix; this file has no bookmaker client and cannot",
           "place a bet. To play one, enter the legs by hand on eljam3ia before kickoff.",
           ""]
    ev = (1 + MEASURED_LEG_ROI) ** legs - 1
    out += [f"MEASURED EXPECTATION: each leg returns {100 * MEASURED_LEG_ROI:+.1f}% long-run "
            f"(9,793 graded legs,",
            f"505 matches), so a {legs}-fold compounds to {100 * ev:+.1f}% per unit staked. An",
            "accumulator amplifies the SIGN of the per-leg edge, and the measured edge is negative.",
            ""]
    if not slips:
        out.append("no slips — the gated pool was too thin to complete one")
        return "\n".join(out) + "\n"
    for i, slip in enumerate(slips, 1):
        combined = 1.0
        for s in slip:
            combined *= s["price"]
        fams = ", ".join(sorted({s["family"] for s in slip}))
        pushable = sum(1 for s in slip if is_void_capable(s["market_name"], s["label"]))
        extra = f", {pushable} push-capable leg{'s' if pushable != 1 else ''}" if pushable else ""
        out.append(f"BETSLIP {i}  ({len(slip)} legs, combined odds x{combined:.2f}, "
                   f"win% {100 / combined:.3g}, families: {fams}{extra})")
        for j, s in enumerate(slip, 1):
            out.append(f"  {j:2}. {s['league']} - {s['match']} - {s['market_name']}: "
                       f"{s['label']} @ {s['price']:.2f}  (ko {s['kickoff']})")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Build betslips offline from a scanned matrix.")
    ap.add_argument("--matrix", default=None,
                    help="matrix CSV; defaults to the newest odds_matrix_*.csv under --output")
    ap.add_argument("--output", default="output")
    ap.add_argument("--out", default=None, help="where to write; defaults beside the matrix")
    ap.add_argument("--legs", type=int, default=4)
    ap.add_argument("--slips", type=int, default=25)
    ap.add_argument("--window", default="1.25..1.50",
                    help="odds range for the LEGS (the scan may be wider); keeping the historical "
                         "window makes each day comparable to the calibration log")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    matrix = Path(args.matrix) if args.matrix else None
    if matrix is None:
        found = sorted(p for p in glob.glob(f"{args.output}/run_*/odds_matrix_*.csv")
                       if "meta" not in p)
        if not found:
            print(f"no matrix found under {args.output}")
            return 1
        matrix = Path(found[-1])
    lo, _, hi = args.window.partition("..")
    seed = random.SystemRandom().randrange(2 ** 32) if args.seed is None else args.seed

    slips = build_from_matrix(matrix.read_text(encoding="utf-8-sig"), args.legs, args.slips,
                              float(lo), float(hi), seed=seed)
    text = render(slips, args.legs, float(lo), float(hi), seed)
    out = Path(args.out) if args.out else matrix.parent / "betslips_offline.txt"
    out.write_text(text, encoding="utf-8")
    print(f"{len(slips)} slip(s) -> {out}   (from {matrix.name}; no booking code minted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
