"""Drift guard between the grader (grade_leg) and the reporting classifier (_market_family).

The fixture tests/data/gradeable_markets.tsv is a snapshot of every (market, selection) pair that
grade_leg settles (verdict != "unsettleable") across the real betslip corpus, evaluated with the
PROBE outcome below -- which carries a half-time score so half / HT-FT / both-halves markets are
gradeable. Regenerate it (only when a genuinely new gradeable market form appears) with:

    py tests/_gen_gradeable_fixture.py

Two invariants are locked:
  1. lockstep -- a gradeable market must NEVER classify into the catch-all "other" bucket. `other`
     exists to make UNanticipated markets visible; a gradeable market landing there silently biases
     the per-family hit-rate report (invariant #7: extend grader and classifier in lockstep).
  2. coverage regression -- each snapshot pair must stay gradeable; a refactor that silently drops
     grading for a whole market form is caught here rather than in a later real settlement.
"""
from pathlib import Path

import pytest

from settle import MatchOutcome, grade_leg, _market_family

PROBE = MatchOutcome("probe", home=2, away=1, ht_home=1, ht_away=1)
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
    # a corpus/parse regression that empties the fixture must not silently pass the guards below
    assert len(PAIRS) > 150


@pytest.mark.parametrize("market,selection", PAIRS, ids=[f"{m}::{s}" for m, s in PAIRS])
def test_gradeable_market_is_not_in_other_family(market, selection):
    # coverage-regression lock: the snapshot pair must still be gradeable...
    assert grade_leg(market, selection, PROBE) != "unsettleable"
    # ...and the drift guard: a gradeable market must classify into a real family, never "other"
    assert _market_family(market) != "other"
