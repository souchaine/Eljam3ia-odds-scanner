"""Drift guard between the build-time gate (is_settleable) and the reporting classifier
(_market_family).

The fixture tests/data/gradeable_markets.tsv is the set of GATE-ELIGIBLE (market, selection) pairs
across the FULL odds matrices -- every selection the scanner saw, not just ones a builder happened
to put on a slip. Regenerate it (only when genuinely new eligible market forms appear) with:

    py tests/_gen_gradeable_fixture.py

The predicate MUST be the gate, not "gradeable under one probe outcome":

  * A market the gate EXCLUDES may classify as "other" -- that is correct, not a bug. "Both halves
    over 2" grades on most scorelines but pushes on some, so it is never selectable and never
    reaches a per-family report.
  * A market the gate INCLUDES landing in "other" IS the bug: the builder will put it on a slip, it
    will settle, and it will then pollute the catch-all bucket in calibrate.py's per-family table --
    the very measurement this project exists to produce.

Two invariants are locked:
  1. lockstep -- a gate-eligible market never classifies into "other" (invariant #7: grader and
     classifier are extended together).
  2. coverage regression -- each fixture pair stays gate-eligible, so a refactor that silently
     narrows grading is caught here rather than in a later real settlement.
"""
from pathlib import Path

from settle import _market_family, is_settleable

FIXTURE = Path(__file__).parent / "data" / "gradeable_markets.tsv"


def _pairs():
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        market, _, selection = line.partition("\t")
        rows.append((market, selection))
    return rows


PAIRS = _pairs()


def test_fixture_is_non_empty():
    # A corpus/parse regression that empties the fixture must not silently pass the guards below.
    # 335 eligible pairs across 48 runs at time of writing -- the gate is strict (every selection
    # must settle across all 225 outcomes), so this is far smaller than the 6547-pair vocabulary.
    assert len(PAIRS) > 250


def test_gate_eligible_markets_never_classify_as_other():
    """Lockstep + coverage-regression guard over the whole gate-eligible fixture.

    One test rather than a parametrized case per pair: the fixture is thousands of pairs and each
    is_settleable call sweeps 225 outcomes, so per-pair IDs cost far more in reporting overhead
    than the assertions do in compute.
    """
    not_eligible, in_other = [], []
    for market, selection in PAIRS:
        if not is_settleable(market, selection):
            not_eligible.append((market, selection))
        if _market_family(market) == "other":
            in_other.append((market, selection))
    assert not not_eligible, f"fixture pairs no longer gate-eligible: {not_eligible[:10]}"
    assert not in_other, f"gate-eligible markets classified 'other': {in_other[:10]}"


def test_gate_excluded_market_in_other_is_tolerated():
    # the predicate must be the GATE, not "gradeable under some probe" -- otherwise a market that
    # is correctly excluded (pushes on some scorelines) would be reported as a false positive.
    assert is_settleable("Both halves over 2", "Yes") is False
    assert _market_family("Both halves over 2") == "both halves"   # classified, but never selected
