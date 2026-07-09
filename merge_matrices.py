"""Merge several odds-matrix CSVs into one clean matrix.

Combines the outputs of eljam3ia_odds_scanner.py into a single file:
- rows deduplicated by Event ID (on a clash, the most recently scraped row wins)
- one unified column set (union of every market seen across the inputs)
- columns re-ordered by how many matches have a qualifying selection (desc, then A-Z)
- rows sorted by league then kickoff

Usage:
    py merge_matrices.py                      # merge all output/odds_matrix_*.csv
    py merge_matrices.py a.csv b.csv          # merge specific files
    py merge_matrices.py --out output         # output folder (default: output/)
"""

import argparse
import csv
import glob
import sys
from datetime import datetime
from pathlib import Path

LEAD = ["League", "Match", "Kickoff (UTC)", "Event ID", "Scraped At (UTC)"]


def load(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def merge(paths: list[Path]) -> list[dict]:
    """event id -> record; later Scraped At wins on duplicates."""
    by_event: dict[str, dict] = {}
    for path in paths:
        for row in load(path):
            eid = (row.get("Event ID") or "").strip()
            if not eid:
                continue
            row = {k: (v or "").strip() for k, v in row.items()}
            existing = by_event.get(eid)
            if existing is None or row.get("Scraped At (UTC)", "") >= existing.get("Scraped At (UTC)", ""):
                by_event[eid] = row
    return list(by_event.values())


def write_matrix(rows: list[dict], path: Path) -> tuple[list[str], int]:
    counts: dict[str, int] = {}
    for row in rows:
        for col, val in row.items():
            if col in LEAD:
                continue
            if val:
                counts[col] = counts.get(col, 0) + 1
            else:
                counts.setdefault(col, 0)
    columns = sorted(counts, key=lambda m: (-counts[m], m.casefold()))
    rows = sorted(rows, key=lambda r: (r.get("League", ""), r.get("Kickoff (UTC)", "")))
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(LEAD + columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in LEAD] + [row.get(c, "") for c in columns])
    return columns, sum(counts.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge odds-matrix CSVs into one clean matrix.")
    parser.add_argument("files", nargs="*", help="matrix CSVs to merge (default: output/odds_matrix_*.csv)")
    parser.add_argument("--out", default="output")
    args = parser.parse_args()

    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = [Path(p) for p in glob.glob("output/odds_matrix_*.csv")
                 if "_meta" not in p and "_merged" not in p]
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("No matrix CSVs found to merge.")
        return 1

    rows = merge(paths)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    matrix_path = out_dir / f"odds_matrix_merged_{stamp}.csv"
    meta_path = out_dir / f"odds_matrix_merged_{stamp}_meta.csv"

    columns, cells = write_matrix(rows, matrix_path)
    leagues = sorted({r.get("League", "") for r in rows})
    with meta_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "value"])
        writer.writerow(["merged_from", "; ".join(p.name for p in paths)])
        writer.writerow(["merged_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")])
        writer.writerow(["unique_matches", len(rows)])
        writer.writerow(["leagues", "; ".join(leagues)])
        writer.writerow(["market_columns", len(columns)])
        writer.writerow(["qualifying_cells", cells])

    print(f"Merged {len(paths)} file(s) -> {matrix_path}")
    print(f"  {len(rows)} unique matches x {len(columns)} market columns, {cells} qualifying cells")
    print(f"  leagues: {', '.join(leagues)}")
    print(f"Wrote {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
