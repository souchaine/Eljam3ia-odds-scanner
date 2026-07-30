"""The settleable betslip builder: random, without replacement, complete slips only."""
import random

from make_betslips import build_settleable_slips, max_complete_slips
from settle import _market_family


def sel(match, market, label, price=1.40):
    return {"match": match, "market_name": market, "label": label, "price": price,
            "league": "L", "odd": {"id": f"{match}-{market}"}}


# markets chosen so each maps to a DIFFERENT settle family and all are gate-eligible
MAIN = ("1x2", "1")                                   # -> main
H1 = ("1st half - total", "Over 0.5")                 # -> 1st half
H2 = ("2nd half - multigoals", "1-3")                 # -> 2nd half
MULTI = ("Multigoals", "1-3")                         # -> multigoals
COMBO = ("Double chance & total 4.5", "1/2 & under 4.5")   # -> combo
STAT = ("Total corners", "Over 8.5")                  # -> corners, NOT gate-eligible


def pool_of(specs):
    """specs: list of (match, (market, label)) -> pools dict keyed by match."""
    pools = {}
    for match, (market, label) in specs:
        pools.setdefault(match, []).append(sel(match, market, label))
    return pools


def test_families_of_fixtures_are_distinct():
    fams = {_market_family(m) for m, _ in (MAIN, H1, H2, MULTI, COMBO)}
    assert len(fams) == 5, fams


def test_only_gate_eligible_selections_are_used():
    # a stat market must never reach a slip even though it is in the pool
    specs = [(f"m{i}", spec) for i, spec in enumerate([MAIN, H1, H2, MULTI])]
    specs += [(f"s{i}", STAT) for i in range(10)]
    slips = build_settleable_slips(pool_of(specs), legs=4, max_slips=5, rng=random.Random(1))
    assert slips
    for slip in slips:
        for s in slip:
            assert s["market_name"] != "Total corners"


def test_each_leg_has_distinct_match_and_distinct_family():
    specs = []
    for i in range(8):
        for spec in (MAIN, H1, H2, MULTI):
            specs.append((f"m{i}-{spec[0]}", spec))
    slips = build_settleable_slips(pool_of(specs), legs=4, max_slips=4, rng=random.Random(7))
    assert slips
    for slip in slips:
        assert len(slip) == 4
        assert len({s["match"] for s in slip}) == 4
        assert len({_market_family(s["market_name"]) for s in slip}) == 4


def test_no_selection_is_reused_across_slips():
    specs = []
    for i in range(6):
        for spec in (MAIN, H1, H2, MULTI):
            specs.append((f"m{i}-{spec[0]}", spec))
    slips = build_settleable_slips(pool_of(specs), legs=4, max_slips=6, rng=random.Random(3))
    seen = [id(s) for slip in slips for s in slip]
    assert len(seen) == len(set(seen))


def test_only_complete_slips_are_emitted():
    # 5 eligible selections, 4 legs -> exactly one complete slip, no trailing partial
    specs = [(f"m{i}", spec) for i, spec in enumerate([MAIN, H1, H2, MULTI])]
    specs.append(("m9", COMBO))
    slips = build_settleable_slips(pool_of(specs), legs=4, max_slips=10, rng=random.Random(5))
    assert all(len(slip) == 4 for slip in slips)


def test_family_starvation_degrades_cleanly_without_partial_or_hang():
    """Distinct-family-per-leg means SHALLOW families bind, not total pool size.

    One deep family (20) + three shallow (2 each), legs=4: only 2 complete slips are possible even
    though 26 selections remain in the pool. The builder must stop cleanly -- no hang, no partial
    slip -- while the deep family still has stock left over.
    """
    specs = [(f"deep{i}", MAIN) for i in range(20)]
    for spec in (H1, H2, MULTI):
        specs += [(f"{spec[0]}-{j}", spec) for j in range(2)]
    pools = pool_of(specs)
    slips = build_settleable_slips(pools, legs=4, max_slips=25, rng=random.Random(11))

    assert len(slips) == 2, f"expected 2 complete slips, got {len(slips)}"
    assert all(len(slip) == 4 for slip in slips)
    used = {id(s) for slip in slips for s in slip}
    leftover_main = [s for sels in pools.values() for s in sels
                     if id(s) not in used and _market_family(s["market_name"]) == "main"]
    assert len(leftover_main) == 18, "deep family should still have stock the builder cannot use"


def test_max_complete_slips_is_bounded_by_shallow_families_not_total_pool():
    # exactly `legs` families -> the ceiling is the Nth-deepest family's depth
    assert max_complete_slips([100, 1, 1, 1], legs=4) == 1
    assert max_complete_slips([20, 2, 2, 2], legs=4) == 2
    assert max_complete_slips([100, 100, 100, 100], legs=4) == 100
    # more families than legs -> a family may sit out some slips, so the ceiling exceeds the
    # Nth-deepest (5 families x10, 4 legs: 50 selections support 12 slips, not 10)
    assert max_complete_slips([10, 10, 10, 10, 10], legs=4) == 12
    # fewer families than legs -> no complete slip is possible at all
    assert max_complete_slips([100, 100, 100], legs=4) == 0
    assert max_complete_slips([], legs=4) == 0


def test_same_seed_reproduces_identical_slips():
    specs = []
    for i in range(6):
        for spec in (MAIN, H1, H2, MULTI, COMBO):
            specs.append((f"m{i}-{spec[0]}", spec))
    sig = lambda slips: [[(s["match"], s["market_name"], s["label"]) for s in sl] for sl in slips]
    a = build_settleable_slips(pool_of(specs), legs=4, max_slips=5, rng=random.Random(1234))
    b = build_settleable_slips(pool_of(specs), legs=4, max_slips=5, rng=random.Random(1234))
    c = build_settleable_slips(pool_of(specs), legs=4, max_slips=5, rng=random.Random(9999))
    assert sig(a) == sig(b)
    assert sig(a) != sig(c), "different seeds should produce different slips"


def test_max_slips_cap_is_respected():
    specs = []
    for i in range(20):
        for spec in (MAIN, H1, H2, MULTI):
            specs.append((f"m{i}-{spec[0]}", spec))
    slips = build_settleable_slips(pool_of(specs), legs=4, max_slips=3, rng=random.Random(2))
    assert len(slips) == 3
