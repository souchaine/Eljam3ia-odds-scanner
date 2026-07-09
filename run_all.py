"""One-command pipeline: scan Top Leagues -> odds matrix -> 10-leg betslips -> booking codes.

Runs the existing scripts in sequence (no logic duplicated here):
  1. eljam3ia_odds_scanner.py  -> odds_matrix_*.csv + _meta.csv
  2. make_betslips.py          -> betslips_*.txt with one Booking Code per 10-leg slip

Each run writes into its own dated folder  output/run_YYYYMMDD_HHMM/  and finishes with a
summary.txt (and console summary) listing the matrix stats and all booking codes.

Booking codes go stale as matches kick off, so codes are always minted fresh at run time.

Usage:
    py run_all.py                    # full pipeline with project defaults
    py run_all.py --size 10          # forwarded to make_betslips.py
    py run_all.py --skip-betslips    # matrix only

Scheduled use: run_all.cmd wraps this for Windows Task Scheduler (see README).
"""

import argparse
import csv
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def run_step(name: str, script: str, args: list[str]) -> int:
    print(f"\n=== {name} ===", flush=True)
    proc = subprocess.run([sys.executable, str(PROJECT_DIR / script), *args],
                          cwd=PROJECT_DIR)
    if proc.returncode != 0:
        print(f"! {name} exited with code {proc.returncode}", flush=True)
    return proc.returncode


def summarize(run_dir: Path) -> str:
    lines = [f"Eljam3ia pipeline run - {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

    metas = sorted(run_dir.glob("odds_matrix_*_meta.csv"))
    if metas:
        meta = dict(list(csv.reader(metas[-1].open(encoding="utf-8-sig")))[1:])
        lines += ["MATRIX",
                  f"  file: {metas[-1].name.replace('_meta', '')}",
                  f"  events scanned: {meta.get('events_scanned', '?')}  "
                  f"(failed: {meta.get('events_failed', '?')}, partial: {meta.get('partial_run', '?')})",
                  f"  market columns: {meta.get('market_columns', '?')}, "
                  f"qualifying cells: {meta.get('qualifying_cells', '?')}",
                  f"  window: {meta.get('accept_window', '?')}", ""]
    else:
        lines += ["MATRIX: no output found (step failed?)", ""]

    slips = sorted(run_dir.glob("betslips_*.txt"))
    if slips:
        text = slips[-1].read_text(encoding="utf-8")
        codes = re.findall(r">> BOOKING CODE: (\S+)", text)
        headers = re.findall(r"^(BETSLIP \d+.*)$", text, re.M)
        lines.append(f"BETSLIPS ({slips[-1].name})")
        for header, code in zip(headers, codes):
            lines.append(f"  {code}  <-  {header}")
        failed = len(headers) - len(codes)
        if failed > 0:
            lines.append(f"  ! {failed} slip(s) failed to reserve - see {slips[-1].name}")
        lines.append("")
        lines.append("Load a code on eljam3ia.com: BETSLIP panel -> Enter Booking Code (before kickoff).")
    else:
        lines += ["BETSLIPS: none (skipped or failed)"]

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Full eljam3ia pipeline: matrix + betslips.")
    parser.add_argument("--size", type=int, default=None, help="legs per betslip (default 10)")
    parser.add_argument("--target", type=float, default=None)
    parser.add_argument("--tolerance", type=float, default=None)
    parser.add_argument("--skip-betslips", action="store_true", help="matrix only")
    parser.add_argument("--hours", type=float, default=None, help="kickoff window in hours (forwarded)")
    parser.add_argument("--scope", choices=["all", "top"], default=None, help="league scope (forwarded)")
    args = parser.parse_args()

    run_dir = PROJECT_DIR / "output" / f"run_{datetime.now().strftime('%Y%m%d_%H%M')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    forward = ["--out", str(run_dir)]
    for flag in ("target", "tolerance", "hours", "scope"):
        if getattr(args, flag) is not None:
            forward += [f"--{flag}", str(getattr(args, flag))]

    rc = run_step("Step 1/2: odds matrix scan", "eljam3ia_odds_scanner.py", forward)
    if rc != 0:
        print("Scan failed - stopping (nothing to build betslips from).")
        return rc

    if not args.skip_betslips:
        slip_args = list(forward)
        if args.size is not None:
            slip_args += ["--size", str(args.size)]
        run_step("Step 2/2: betslips + booking codes", "make_betslips.py", slip_args)

    summary = summarize(run_dir)
    (run_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print(f"\n{'=' * 60}\n{summary}\n{'=' * 60}")
    print(f"\nAll artifacts in: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
