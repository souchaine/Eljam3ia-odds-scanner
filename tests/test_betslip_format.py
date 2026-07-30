"""Rendered betslip file: round-trips into settle.py, and its displayed win% agrees with how
settlement actually treats a pushed (void) leg.
"""
import random

from calibrate import calibrate
from make_betslips import (SECTION_TITLE, build_settleable_slips, expected_win_pct, leg_line,
                           preamble_lines, resolve_seed, section_line, slip_header_line,
                           slip_win_pct)
from settle import MatchOutcome, grade_slip, parse_betslips


def sel(match, market, label, price=1.40):
    return {"match": match, "market_name": market, "label": label, "price": price,
            "league": "Liga", "odd": {"id": f"{match}-{market}"}}


SLIP = [sel("A vs. B", "1x2", "1", 1.4706),
        sel("C vs. D", "1st half - total", "Over 0.5", 1.2858),
        sel("E vs. F", "2nd half - multigoals", "1-3", 1.3637),
        sel("G vs. H", "Multigoals", "1-3", 1.50)]


def render(slips, *, legs=4, seed=1234, code="ABC12"):
    lines = preamble_lines(legs=legs, seed=seed, lo=1.25, hi=1.5, matches=140, max_slips=25,
                           win_pct=expected_win_pct([s for sl in slips for s in sl], legs))
    lines.append(section_line())
    for i, slip in enumerate(slips, 1):
        lines.append(slip_header_line(f"B{i}", slip))
        lines += [leg_line(j, s) for j, s in enumerate(slip, 1)]
        lines.append(f"  >> BOOKING CODE: {code}{i}")
        lines.append("")
    return "\n".join(lines)


def test_generated_file_parses_back_to_set_b():
    # guards against silently writing empty `set` values into backtest.csv: parse_betslips only
    # recognises "===== SET [AB]", so retitling the human-readable part must not break the key.
    parsed = parse_betslips(render([SLIP]))
    assert len(parsed) == 1
    slip = parsed[0]
    assert slip["set"] == "B"
    assert slip["code"] == "ABC121"
    assert len(slip["legs"]) == 4
    assert slip["legs"][0]["match"] == "A vs. B"
    assert slip["legs"][0]["market"] == "1x2"
    assert slip["legs"][0]["selection"] == "1"


def test_section_line_keeps_the_set_b_parse_key():
    assert section_line().startswith("===== SET B")
    assert "SET B" in SECTION_TITLE


def test_leg_line_displays_two_decimals_but_price_is_not_rounded():
    line = leg_line(1, SLIP[0])
    assert line.endswith("@ 1.47")          # displayed, bookmaker style
    assert SLIP[0]["price"] == 1.4706       # stored value untouched -> full precision downstream


def test_slip_header_uses_full_precision_for_combined_odds_and_win_pct():
    header = slip_header_line("B1", SLIP)
    combined = 1.0
    for s in SLIP:
        combined *= s["price"]              # 1.4706 * 1.2858 * 1.3637 * 1.50
    assert f"x{combined:.2f}" in header
    assert f"win% {slip_win_pct(SLIP):.3g}" in header
    # families are the settle taxonomy, one per leg
    assert "families: 1st half, 2nd half, main, multigoals" in header


def test_expected_win_pct_shows_geometric_decay_as_legs_rise():
    pool = [sel("m", "1x2", "1", 1.40) for _ in range(10)]
    assert round(expected_win_pct(pool, 4), 1) == 26.0     # 100 / 1.40**4
    assert round(expected_win_pct(pool, 6), 1) == 13.3     # 100 / 1.40**6
    assert expected_win_pct(pool, 6) < expected_win_pct(pool, 4)


def test_resolve_seed_returns_the_actual_seed_used():
    assert resolve_seed(4242) == 4242
    auto = resolve_seed(None)
    assert isinstance(auto, int) and auto >= 0        # a real value, not a placeholder default


def test_seed_recorded_in_preamble_reproduces_the_same_slips():
    """The reproducibility guarantee users rely on: take the seed printed in a file's header, feed
    it back via --seed, and get the same slips."""
    specs = []
    for i in range(6):
        for market, label in [("1x2", "1"), ("1st half - total", "Over 0.5"),
                              ("2nd half - multigoals", "1-3"), ("Multigoals", "1-3")]:
            specs.append(sel(f"m{i}-{market}", market, label))
    pools = {}
    for s in specs:
        pools.setdefault(s["match"], []).append(s)

    used = resolve_seed(None)
    first = build_settleable_slips(pools, legs=4, max_slips=4, rng=random.Random(used))
    text = render(first, seed=used)

    recorded = int(text.split("seed ")[1].split(";")[0].strip())
    assert recorded == used
    again = build_settleable_slips(pools, legs=4, max_slips=4, rng=random.Random(recorded))
    sig = lambda sl: [[(x["match"], x["market_name"], x["label"]) for x in s] for s in sl]
    assert sig(again) == sig(first)


# ---- void / push consistency: displayed win% vs how settlement actually treats a push ----------

PUSHABLE = [sel("A vs. B", "Total", "Over 2", 1.40),          # integer line -> can push (void)
            sel("C vs. D", "1st half - total", "Over 0.5", 1.40),
            sel("E vs. F", "2nd half - multigoals", "1-3", 1.40),
            sel("G vs. H", "Multigoals", "1-3", 1.40)]


def test_push_capable_leg_is_annotated_in_the_header():
    assert "1 push-capable leg" in slip_header_line("B1", PUSHABLE)
    assert "push-capable" not in slip_header_line("B1", SLIP)   # none of these can push


def test_pushed_leg_is_dropped_by_settlement_so_header_win_pct_is_a_floor():
    """Settlement DROPS a void leg (_verdict_from), so a 4-leg slip can settle as a 3-leg one.

    The header's win% is P(all legs win) and therefore a conservative FLOOR: when a leg pushes the
    slip needs fewer winners, so its realised chance is higher, never lower. The preamble says so
    explicitly rather than pretending the number is exact.
    """
    parsed = parse_betslips(render([PUSHABLE]))[0]
    outcomes = {
        "A vs. B": MatchOutcome("A vs. B", 1, 1, 0, 1),   # total 2 == line -> Over 2 pushes (void)
        "C vs. D": MatchOutcome("C vs. D", 1, 0, 1, 0),   # 1st half 1 goal -> Over 0.5 won
        "E vs. F": MatchOutcome("E vs. F", 2, 1, 1, 1),   # 2nd half 1 goal -> multigoals 1-3 won
        "G vs. H": MatchOutcome("G vs. H", 2, 1, 1, 0),   # 3 goals -> multigoals 1-3 won
    }
    assert grade_slip(parsed, outcomes) == "won"          # pushed leg dropped, other three won
    # and the floor claim: 3 legs at 1.40 is likelier than 4 at 1.40
    assert slip_win_pct(PUSHABLE) < slip_win_pct(PUSHABLE[1:])


def test_calibrate_excludes_the_pushed_leg_from_graded():
    # header/settlement/calibration must agree: a push is neither a win nor a loss.
    rows = [{"family": "main", "match": "m", "market": "Total", "selection": "Over 2",
             "odd": "1.4", "verdict": "void"},
            {"family": "main", "match": "m", "market": "1x2", "selection": "1",
             "odd": "1.4", "verdict": "won"}]
    c = calibrate(rows)
    assert c["main"]["n"] == 2
    assert c["main"]["graded"] == 1        # the void is not graded
    assert c["main"]["won"] == 1
    assert c["main"]["hit_pct"] == 100.0
