"""Regenerate the drift-guard fixtures from the real corpus.

Dev-only tool (the corpus under output/ is git-ignored, so this runs in the main working copy, not
in CI). It sweeps the FULL odds matrices -- every selection the scanner saw, not just the ones a
builder happened to put on a slip -- and writes two files:

  tests/data/gradeable_markets.tsv   GATE-ELIGIBLE pairs: is_settleable(market, selection) is True.
                                     test_market_family_property.py asserts none of these classify
                                     into the catch-all "other" family.
  tests/data/market_vocabulary.tsv   EVERY distinct pair, eligible or not, for the never-raises
                                     sweep in test_settleable_gate.py.

Why the matrix and not betslip legs: the previous fixture was built from betslip legs only, so it
could not see markets the old builder never picked. That blind spot hid a real lockstep bug
("1 to score" / "2 exact goals" were gate-eligible but classified "other").

Why is_settleable and not a single probe outcome: the guard must use the SAME predicate the builder
uses. A market that grades on some scorelines but not others (e.g. "Both halves over 2") is
correctly EXCLUDED by the gate, so it landing in "other" is fine and must not fail the guard --
only a gate-ELIGIBLE market in "other" is the bug.

Run from the repo root:  py tests/_gen_gradeable_fixture.py
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from settle import is_settleable  # noqa: E402

CELL = re.compile(r"^\s*(.+?)\s*@\s*([\d.]+)\s*$")


def _matrix_pairs(root: Path) -> set[tuple[str, str]]:
    """Every distinct (market, selection) across all odds_matrix_*.csv runs."""
    pairs: set[tuple[str, str]] = set()
    for f in sorted(root.glob("output/run_*/odds_matrix_*.csv")):
        rows = list(csv.reader(f.read_text(encoding="utf-8-sig").splitlines()))
        if not rows:
            continue
        header = rows[0]
        if "Match" not in header:
            continue
        mcol = header.index("Match")
        for row in rows[1:]:
            if len(row) <= mcol:
                continue
            for ci, cell in enumerate(row):
                if ci == mcol or ci >= len(header) or not cell.strip():
                    continue
                m = CELL.match(cell)
                market = header[ci].strip()
                if m and market:
                    pairs.add((market, m.group(1).strip()))
    return pairs


def _write(path: Path, header: list[str], pairs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = header + [f"{m}\t{s}" for m, s in sorted(pairs)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    pairs = _matrix_pairs(ROOT)
    if not pairs:
        print("no odds_matrix_*.csv under output/run_*/ -- run this from the main working copy")
        return 1
    eligible = {(m, s) for m, s in pairs if is_settleable(m, s)}

    _write(ROOT / "tests" / "data" / "market_vocabulary.tsv",
           ["# market<TAB>selection -- EVERY distinct pair across all odds_matrix_*.csv runs.",
            "# Used by the never-raises sweep. Regenerate: py tests/_gen_gradeable_fixture.py"],
           pairs)
    _write(ROOT / "tests" / "data" / "gradeable_markets.tsv",
           ["# market<TAB>selection -- GATE-ELIGIBLE pairs (is_settleable is True) from the full",
            "# odds matrices. Guard: none of these may classify into the 'other' family.",
            "# Regenerate: py tests/_gen_gradeable_fixture.py. Do not hand-edit."],
           eligible)
    print(f"{len(pairs)} distinct pairs; {len(eligible)} gate-eligible -> tests/data/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
