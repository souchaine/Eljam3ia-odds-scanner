"""Regenerate tests/data/gradeable_markets.tsv from the real betslip corpus.

Dev-only tool (the corpus under output/ is git-ignored, so this runs in the main working copy, not
in CI). It writes every distinct (market, selection) pair that grade_leg can SETTLE -- verdict is
not "unsettleable" -- under the PROBE outcome, which carries a half-time score so half / HT-FT /
both-halves markets are gradeable. test_market_family_property.py locks that snapshot.

Run from the repo root:  py tests/_gen_gradeable_fixture.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import settle

# same probe as the property test; a half-time score makes half-dependent markets gradeable
PROBE = settle.MatchOutcome("probe", home=2, away=1, ht_home=1, ht_away=1)


def main() -> int:
    files = sorted(ROOT.glob("output/run_*/betslips_*.txt"))
    if not files:
        print("no betslip corpus under output/run_*/ -- run this from the main working copy")
        return 1
    pairs = set()
    for f in files:
        for slip in settle.parse_betslips(f.read_text(encoding="utf-8")):
            for leg in slip["legs"]:
                m, s = leg["market"], leg["selection"]
                if settle.grade_leg(m, s, PROBE) != "unsettleable":
                    pairs.add((m, s))
    out = ROOT / "tests" / "data" / "gradeable_markets.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# market<TAB>selection -- gradeable pairs from the real corpus; see",
             "# test_market_family_property.py and _gen_gradeable_fixture.py. Do not hand-edit."]
    lines += [f"{m}\t{s}" for m, s in sorted(pairs)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(pairs)} gradeable pairs from {len(files)} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
