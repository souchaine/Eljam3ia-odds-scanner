"""Build multiplier (accumulator) betslips from eljam3ia and reserve a booking code for each.

For the leagues in scope, this collects EVERY qualifying selection per match (price within the
target range/tolerance) into a pool, keeps only the SETTLEABLE ones (`settle.is_settleable` -- see
below), then builds up to `--slips` (default 25) slips of `--legs` legs each (default 4), drawn at
random without replacement. Each leg sits on a DISTINCT match and a DISTINCT market family, and
only COMPLETE slips are emitted. Each betslip is sent to Altenar's reserveBet endpoint, which
returns a shareable Booking Code that anyone can load on the site via "Enter Booking Code".

Why 4 legs and why settleable-only: at the pool's ~1.38 average odd a 20-leg accumulator wins about
0.16% of the time (1 in 620) and -- because a slip is gradeable only if EVERY leg is -- a single
corners or player-prop leg made the whole slip ungradeable. A 4-leg slip wins ~27% of the time and,
because every leg passes the build-time gate, settles from a scores CSV the moment its matches
finish. That is what makes the per-family calibration in calibrate.py possible without a paid stats
provider.

A booking code only saves the selections (like sharing a filled-in slip) - it places no bet and
moves no money.

IMPORTANT (why the payload is so detailed): the Altenar betslip widget needs each stored selection
to carry the FULL context - the `market` object (with sportMarketId), plus sport/category/
championship/competitors, and an `odd` enriched with intSelectionId/intEventId (fetched from
GetOddsStates). A minimal {odd, event} reserve still returns a code, but the widget crashes when it
tries to render it ("Oops! This section of the sportsbook didn't load"). This builder reproduces the
exact shape the site itself stores when you click odds, so the codes load cleanly.

Usage:
    py make_betslips.py                     # all leagues, <=25 settleable slips, 4 legs each
    py make_betslips.py --legs 6            # prints the resulting per-slip win% (~14% at 6 legs)
    py make_betslips.py --seed 1234         # reproduce a previous run (seed is in its file header)
    py make_betslips.py --league "World Cup 2026" --league "Serie A"

Odds are live: load a code before its matches kick off, or that leg shows as unavailable.
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

from eljam3ia_odds_scanner import (
    API_BASE, DATE_FILTER_HOURS, DELAY_S, EPS, HEADERS, SPORT_ID, TARGET_MAX, TARGET_MIN,
    TOLERANCE, TOP_LEAGUES, clean, fetch, filter_events_by_window, get_all_football_events,
    get_events, now_utc, parse_target, resolve_leagues,
)
# The build-time settleability gate lives with the grader so eligibility and grading cannot drift.
# settle.py imports nothing project-local, so this does not create a cycle.
from settle import _market_family, is_settleable, is_void_capable

BETSLIP_BASE = "https://sb2betslip-altenar2.biahosted.com/api/Betslip"
COUNTRY_CODE = "TN"
GROUP_SIZE = 4    # legs per betslip: ~27% win at the pool's ~1.38 average odd (20 legs was ~0.16%)
SLIPS_B = 25      # max slips per run
OUTPUT_DIR = "output"

# Human-readable section title. The literal "SET B" token is load-bearing: settle.parse_betslips
# keys slips off `===== SET [AB]`, and existing backtest*.csv history joins on that letter, so it
# survives SET A's removal.
SECTION_TITLE = "SET B: settleable"

CATEGORY_ORDER = ["main", "combo DC", "1st half", "2nd half", "corners", "carte", "multigoals"]

# body sent with every POST (reserveBet / GetOddsStates)
COMMON_BODY = {
    "culture": "en-GB", "timezoneOffset": -60, "integration": "eljam3ia",
    "deviceType": 1, "numFormat": "en-GB", "countryCode": COUNTRY_CODE,
}
POST_HEADERS = {**HEADERS, "Content-Type": "application/json", "Origin": "https://www.eljam3ia.com"}


def collect_selections(details: dict, lo: float, hi: float) -> list[dict]:
    """Every qualifying odd for one event (price in [lo, hi], active), deduped by odd id."""
    odds_by_id = {o["id"]: o for o in details.get("odds", [])}
    out: list[dict] = []
    seen: set[int] = set()
    for market in details.get("markets", []) + details.get("childMarkets", []):
        name = clean(market.get("name"))
        if not name:
            continue
        odd_ids = market.get("desktopOddIds") or market.get("mobileOddIds") or []
        for group in odd_ids:
            for odd_id in group if isinstance(group, list) else [group]:
                odd = odds_by_id.get(odd_id)
                if odd is None or odd.get("oddStatus", 0) != 0 or odd_id in seen:
                    continue
                try:
                    price = float(odd.get("price"))
                except (TypeError, ValueError):
                    continue
                if lo - EPS <= price <= hi + EPS:
                    seen.add(odd_id)
                    out.append({"odd": odd, "market": market, "price": price,
                                "label": clean(odd.get("name")) or "?", "market_name": name})
    return out


def market_category(name: str) -> str:
    """Classify a market name into one of the 7 families (specific stat types win)."""
    n = (name or "").lower()
    if "corner" in n:
        return "corners"
    if "booking" in n or "card" in n:
        return "carte"
    if "multigoal" in n:
        return "multigoals"
    if "1st half" in n or "first half" in n:
        return "1st half"
    if "2nd half" in n or "second half" in n:
        return "2nd half"
    if "double chance" in n or "dc " in n or "/dc" in n or "dc/" in n:
        return "combo DC"
    return "main"


def implied_prob(price: float) -> float:
    """Implied probability of one outcome from its decimal odds (bookmaker margin included).

    We deliberately do NOT de-vig by normalizing over a market's listed outcomes. Altenar bundles
    many LINES into a single market - a "Total" market carries Over 0.5 / Over 1 / ... / Over 3 and
    every Under alongside them - which are not mutually exclusive outcomes. Summing 1/p across them
    gives ~10 instead of a real market's ~1.05, crushing each leg ~10x and (because the bundle size
    differs per market) destroying any monotonic relationship between a slip's win% and its odds.
    Raw implied probability is transparent and keeps win% == 100 / combined_odds.
    """
    try:
        p = float(price)
    except (TypeError, ValueError):
        return 0.0
    return 1.0 / p if p > 0 else 0.0


def slip_win_pct(slip: list[dict]) -> float:
    """Slip win probability as a percent: 100 * product of legs' implied probs.

    Equals 100 / combined_odds, so it is strictly monotonic with the slip's payout odds.
    """
    if not slip:
        return 0.0
    prob = 1.0
    for s in slip:
        p = implied_prob(s.get("price"))
        if p <= 0:
            return 0.0
        prob *= p
    return 100.0 * prob


def build_slips(pools: dict[str, list[dict]], size: int, max_slips: int) -> list[list[dict]]:
    """Greedily form slips of distinct matches, consuming one selection per match per slip.

    A match repeats across slips only by spending a not-yet-used selection (odd). Most-remaining
    match first spreads usage so more full slips are possible.
    """
    if size <= 0:
        return []
    remaining = {k: list(v) for k, v in pools.items() if v}
    slips: list[list[dict]] = []
    while len(slips) < max_slips:
        avail = sorted((kv for kv in remaining.items() if kv[1]),
                       key=lambda kv: len(kv[1]), reverse=True)
        if len(avail) < 2:
            break
        take = avail[:size]
        slip = [items.pop() for _key, items in take]
        slips.append(slip)
        if len(slip) < size:  # could not fill a full slip -> this is the trailing partial
            break
    return slips


def max_complete_slips(family_depths, legs: int) -> int:
    """Ceiling on complete slips given per-family selection depths.

    Every slip takes one selection from each of `legs` DISTINCT families, so a family contributes at
    most once per slip -- at most R times across R slips. R slips are therefore feasible iff
    `sum(min(depth, R)) >= R * legs`.

    The binding constraint is the SHALLOW families, not the pool total: with depths [100, 1, 1, 1]
    and legs=4 the ceiling is 1, not 103//4 = 25. When exactly `legs` families exist this reduces to
    "the depth of the legs-th deepest family"; with more families than legs a family can sit out
    some slips, so the ceiling rises above that (e.g. five families of 10 support 12 four-leg slips).
    """
    depths = [d for d in family_depths if d > 0]
    if legs <= 0 or len(depths) < legs:
        return 0
    r = 0
    while sum(min(d, r + 1) for d in depths) >= (r + 1) * legs:
        r += 1
    return r


def build_settleable_slips(pools: dict[str, list[dict]], legs: int, max_slips: int,
                           rng: random.Random,
                           allow_family_repeat: bool = False) -> list[list[dict]]:
    """Random, without-replacement builder for settleable slips.

    Each slip has exactly `legs` legs, each on a DISTINCT match and a DISTINCT settle family.
    Only selections that pass the build-time gate (`settle.is_settleable`) are eligible, so every
    emitted slip is gradeable from a scores CSV the moment its matches finish.

    Only COMPLETE slips are emitted -- when one can no longer be filled the builder stops rather
    than emitting a partial or reusing a selection. Because distinct-family-per-leg makes shallow
    families the binding constraint (see `max_complete_slips`), this degradation is normal on thin
    slates and is not an error.
    """
    if legs <= 0 or max_slips <= 0:
        return []
    remaining = [s for sels in pools.values() for s in sels
                 if is_settleable(s.get("market_name"), s.get("label"))]
    slips: list[list[dict]] = []
    while len(slips) < max_slips:
        rng.shuffle(remaining)                    # reshuffle per slip: no fixed structural pattern
        slip: list[dict] = []
        used_matches: set = set()
        used_families: set = set()
        # Pass 1 keeps one family per leg -- the DEFAULT, and the approved contract for the live
        # 4-leg slips. Pass 2 runs only when `allow_family_repeat` is set, because a typical slate
        # carries ~7 families and a 12-leg slip cannot be built any other way. It is opt-in rather
        # than automatic: making it the default silently turned a 2-slip starved slate into 6.
        #
        # DISTINCT MATCH is never relaxed in either pass. Two legs on one fixture resolve off the
        # same scoreline, so their outcomes are correlated and the combined odds would overstate the
        # true win probability -- the printed win% would be a lie, not merely less diversified.
        for require_new_family in ((True,) if not allow_family_repeat else (True, False)):
            for s in remaining:
                if len(slip) == legs:
                    break
                fam = _market_family(s.get("market_name"))
                if s.get("match") in used_matches:
                    continue
                if require_new_family and fam in used_families:
                    continue
                slip.append(s)
                used_matches.add(s.get("match"))
                used_families.add(fam)
            if len(slip) == legs:
                break
        if len(slip) < legs:
            break                                 # cannot complete -> stop; never emit a partial
        chosen = {id(s) for s in slip}
        remaining = [s for s in remaining if id(s) not in chosen]
        slips.append(slip)
    return slips


def resolve_seed(seed: int | None) -> int:
    """The seed actually used for this run.

    When --seed is unset we draw one from system entropy and RETURN it, so the value written into
    the file header is the real one: feeding it back via --seed reproduces that exact file. A
    placeholder default here would silently break that guarantee.
    """
    return random.SystemRandom().randrange(2 ** 32) if seed is None else int(seed)


def expected_win_pct(pool: list[dict], legs: int) -> float:
    """Per-slip win% implied by the gated pool's average odd.

    Printed at build time so raising --legs shows its geometric cost immediately (at ~1.38 average:
    4 legs ~27%, 6 legs ~14%) instead of the decay being invisible until settlement.
    """
    prices = [s["price"] for s in pool if s.get("price")]
    if not prices or legs <= 0:
        return 0.0
    avg = sum(prices) / len(prices)
    return 100.0 / (avg ** legs) if avg > 0 else 0.0


def section_line() -> str:
    """The section header. Keeps the literal "SET B" token: settle.parse_betslips matches
    `===== SET [AB]` to key each slip, and output/backtest*.csv history joins on that letter.
    Only the human-readable remainder changed when SET A was removed."""
    return f"===== {SECTION_TITLE} ====="


def preamble_lines(*, legs: int, seed: int, lo: float, hi: float, matches: int,
                   max_slips: int, win_pct: float) -> list[str]:
    """File header: what was built, from what, and how to reproduce it."""
    return [
        f"Eljam3ia settleable betslips - built {now_utc()}",
        f"window {lo:g}..{hi:g}, {legs} legs/slip, seed {seed}; "
        f"{SECTION_TITLE} (<= {max_slips}), {matches} matches",
        f"per-slip win% {win_pct:.3g} at {legs} legs -- probability ALL legs win. A pushed (void) "
        "leg is DROPPED at settlement, shortening the slip, so this is a floor, not an exact rate.",
        "Every leg is settleable from a scores CSV: match,home,away,ht_home,ht_away "
        "(half-time scores required).",
        "Load a code on eljam3ia.com: BETSLIP panel -> Enter Booking Code.",
        "EXPIRY: a code dies at its FIRST kickoff, shown per slip below. Past that the widget drops "
        "the started legs and loads a short slip or nothing AT ALL, with no error -- the "
        "reservation still resolves, the football is simply over. Slips are ordered "
        "longest-lived first.",
        "",
    ]


def slip_expiry(slip: list[dict]) -> str | None:
    """When this booking code dies: the EARLIEST kickoff among its legs.

    A reservation stays resolvable long after it is useless -- `FindReservedBet` happily returns a
    12-leg slip whose every fixture finished yesterday, and the widget then loads nothing. The code
    does not expire as a whole; it rots from the first kickoff onward. Legs with no recorded start
    are ignored rather than treated as immediate, so a missing field cannot fake an expiry.
    """
    starts = [s.get("event", {}).get("startDate") for s in slip]
    starts = [t for t in starts if t]
    return min(starts) if starts else None


def sort_slips_by_expiry(slips: list[list[dict]]) -> list[list[dict]]:
    """Longest-lived first, so the top of the file is the part still usable.

    Slips with no kickoff data sort last: their usability cannot be established, so they should not
    displace one that is provably still open. Stable, so equal expiries keep build order.
    """
    dated = sorted((s for s in slips if slip_expiry(s)), key=slip_expiry, reverse=True)
    return dated + [s for s in slips if not slip_expiry(s)]


def slip_header_line(label: str, slip: list[dict]) -> str:
    """One slip's header. Combined odds and win% use FULL-precision prices; only the per-leg odds
    are displayed rounded (see leg_line)."""
    combined = 1.0
    for s in slip:
        combined *= s["price"]
    fams = ", ".join(sorted({_market_family(s["market_name"]) for s in slip}))
    pushable = sum(1 for s in slip if is_void_capable(s["market_name"], s["label"]))
    extra = f", {pushable} push-capable leg{'s' if pushable != 1 else ''}" if pushable else ""
    exp = slip_expiry(slip)
    # The code is dead from this moment on -- the widget silently drops started legs, so a slip
    # loaded after its first kickoff comes back short or empty with no error.
    when = f", expires {exp[:10]} {exp[11:16]}Z" if exp else ""
    return (f"BETSLIP {label}  ({len(slip)} legs, combined odds x{combined:.2f}, "
            f"win% {slip_win_pct(slip):.3g}{when}, families: {fams}{extra})")


def leg_line(i: int, s: dict) -> str:
    """One leg. The odd is DISPLAYED at 2 decimals (bookmaker style); s['price'] keeps full
    precision and that is what reserveBet receives."""
    return (f"  {i:2}. {s['league']} - {s['match']} - {s['market_name']}: "
            f"{s['label']} @ {s['price']:.2f}")


def enrich_odds(client: httpx.Client, picks: list[dict]) -> None:
    """Batch-call GetOddsStates to add intSelectionId/intEventId/isDBB to each pick's odd."""
    payload = [{"oddId": p["odd"]["id"], "price": p["price"],
                "eventId": p["event"]["id"], "marketTypeId": p["market"].get("typeId")}
               for p in picks]
    states: dict[int, dict] = {}
    for i in range(0, len(payload), 50):
        chunk = payload[i:i + 50]
        resp = client.post(f"{API_BASE}/GetOddsStates", json={**COMMON_BODY, "odds": chunk})
        resp.raise_for_status()
        for st in resp.json().get("oddStates", []):
            states[st["id"]] = st
    for p in picks:
        st = states.get(p["odd"]["id"], {})
        p["odd"] = {
            **p["odd"],
            "intSelectionId": st.get("intSelectionId"),
            "intEventId": st.get("intEventId", p["event"]["id"]),
            "isDBB": st.get("isDirectBB", True),
            "lineDir": 1, "priceDir": 1, "shouldUpdate": False,
        }


def build_selection(p: dict) -> dict:
    """Assemble one full-shape betslip selection (the exact structure the widget stores)."""
    m = p["market"]
    market = {
        "oddIds": [i for g in (m.get("desktopOddIds") or []) for i in (g if isinstance(g, list) else [g])],
        "headerName": clean(m.get("name")), "typeId": m.get("typeId"),
        "sportMarketId": m.get("sportMarketId"), "id": m.get("id"), "name": clean(m.get("name")),
    }
    return {
        "odd": p["odd"], "event": p["event"], "market": market,
        "sport": p["sport"], "category": p["category"], "championship": p["championship"],
        "competitors": p["competitors"],
        "status": 0, "isBanker": False, "isEnabled": True, "incompatibleOddIds": [],
        "widgetInfo": {"widget": 7, "page": 1, "tabIndex": None, "tipsterId": None, "suggestionType": None},
    }


def reserve(client: httpx.Client, picks: list[dict]) -> str:
    """Reserve a betslip from full-shape selections; return the Booking Code."""
    betslip = {
        "stakes": [{"value": 1, "type": 3, "isEnabled": True, "preciseValue": 1, "isHighlighted": False}],
        "selections": [build_selection(p) for p in picks],
    }
    resp = client.post(f"{BETSLIP_BASE}/reserveBet", json={**COMMON_BODY, "betslip": json.dumps(betslip)})
    resp.raise_for_status()
    data = resp.json()
    if data.get("Error"):
        raise RuntimeError(f"reserveBet error: {data['Error']}")
    return data["Result"]["ReservationKey"]


def _utf8_console() -> None:
    """Make stdout/stderr tolerate non-cp1252 names (e.g. 'ă') on Windows, instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="Build multiplier betslips and reserve booking codes.")
    parser.add_argument("--league", action="append", help="league name (repeatable); default: Top Leagues")
    parser.add_argument("--legs", "--size", dest="legs", type=int, default=GROUP_SIZE,
                        help="legs per betslip (default 4); the resulting per-slip win%% is printed")
    parser.add_argument("--slips", "--slips-b", dest="slips", type=int, default=SLIPS_B,
                        help="max slips to build (default 25)")
    parser.add_argument("--seed", type=int, default=None,
                        help="RNG seed for reproducible slips; the seed used is written to the "
                             "file header, so pass it back to regenerate that exact file")
    parser.add_argument("--per-category", action="store_true",
                        help="(legacy) build category-pure slips instead of the two sets")
    parser.add_argument("--target", default=f"{TARGET_MIN}..{TARGET_MAX}",
                        help="odd range 'min..max' (or a single value)")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--out", default=OUTPUT_DIR)
    parser.add_argument("--hours", type=float, default=DATE_FILTER_HOURS,
                        help="only events kicking off within N hours (0 = all upcoming)")
    parser.add_argument("--scope", choices=["all", "top"], default="all",
                        help="'all' = every football league, 'top' = Top Leagues menu section")
    args = parser.parse_args()

    tmin, tmax = parse_target(args.target)
    lo, hi = tmin - args.tolerance, tmax + args.tolerance
    slips_b = args.slips
    seed = resolve_seed(args.seed)
    rng = random.Random(seed)

    with httpx.Client(headers=POST_HEADERS, timeout=30) as client:
        if args.league or args.scope == "top":
            wanted = args.league or TOP_LEAGUES
            found, missing = resolve_leagues(client, wanted)
            for name in missing:
                print(f"  ! league not on the menu right now (skipped): {name}")
            order = {name.strip().casefold(): i for i, name in enumerate(wanted)}
            found.sort(key=lambda lg: order.get(lg["name"].strip().casefold(), 999))
            league_events = [(clean(lg["name"]),
                              filter_events_by_window(get_events(client, lg["id"]), args.hours))
                             for lg in found]
        else:
            all_events = filter_events_by_window(get_all_football_events(client), args.hours)
            by_league: dict[str, list] = {}
            for event in all_events:
                by_league.setdefault(event["_league"], []).append(event)
            league_events = sorted(by_league.items())

        pools: dict[str, list[dict]] = {}
        for league_name, events in league_events:
            usable = 0
            for event in sorted(events, key=lambda e: e.get("startDate", "")):
                try:
                    details = fetch(client, "GetEventDetails", eventId=event["id"])
                except RuntimeError:
                    continue
                sels = collect_selections(details, lo, hi)
                if sels:
                    key = f"{event['id']}"
                    for s in sels:
                        s.update({"event": event, "sport": details.get("sport"),
                                  "category": details.get("category"),
                                  "championship": details.get("champ"),
                                  "competitors": details.get("competitors", []),
                                  "match": clean(event.get("name")) or "?", "league": league_name})
                    pools[key] = sels
                    usable += 1
                time.sleep(DELAY_S + random.uniform(0, 0.3))
            print(f"{league_name}: {usable} events with qualifying selections")

        groups: list[tuple[str, list[dict]]] = []
        if args.per_category:
            for cat in CATEGORY_ORDER:
                cat_pools = {k: [s for s in v if market_category(s["market_name"]) == cat]
                             for k, v in pools.items()}
                cat_pools = {k: v for k, v in cat_pools.items() if v}
                for i, slip in enumerate(build_slips(cat_pools, args.legs, slips_b), 1):
                    groups.append((f"{cat} #{i}", slip))
        else:
            # A slate carries ~8 SETTLEABLE families, so one-family-per-leg caps a slip at ~8.
            # Beyond that the only way to build is to let families repeat; below it the flag
            # changes nothing, since pass 2 never runs while pass 1 can still fill the slip.
            #
            # Count families among SETTLEABLE selections only. `pools` also holds corners, cards and
            # player markets, which push the raw family count to ~14 — enough to make `12 > count`
            # false and silently disable the fallback, producing zero slips from a 4,058-selection
            # pool.
            family_count = len({_market_family(s["market_name"])
                                for sels in pools.values() for s in sels
                                if is_settleable(s.get("market_name"), s.get("label"))})
            built = build_settleable_slips(pools, args.legs, slips_b, rng,
                                           allow_family_repeat=args.legs > family_count)
            # Longest-lived first, so B1 is the slip with the most time left to load it.
            for i, slip in enumerate(sort_slips_by_expiry(built), 1):
                groups.append((f"B{i}", slip))

        gated = [s for sels in pools.values() for s in sels
                 if is_settleable(s.get("market_name"), s.get("label"))]
        win_pct = expected_win_pct(gated, args.legs)
        if not args.per_category:
            depths = Counter(_market_family(s["market_name"]) for s in gated)
            # max_complete_slips assumes one family per leg. Once families may repeat that formula
            # returns 0 for any slip longer than the family count, which would contradict the slips
            # actually built -- the binding constraint becomes DISTINCT MATCHES per slip instead.
            if args.legs > len(depths):
                matches_available = len({s["match"] for sels in pools.values() for s in sels
                                         if is_settleable(s.get("market_name"), s.get("label"))})
                ceiling = min(sum(depths.values()) // args.legs,
                              matches_available // 1 if args.legs <= matches_available else 0)
            else:
                ceiling = max_complete_slips(depths.values(), args.legs)
            total = sum(depths.values())
            print(f"\nGated pool: {total}/{sum(len(v) for v in pools.values())} selections settleable"
                  f" across {len(depths)} families; avg odd "
                  f"{(sum(s['price'] for s in gated) / total if total else 0):.4f}")
            print(f"Per-slip win% at {args.legs} legs: {win_pct:.3g}%")
            # distinct-family-per-leg means SHALLOW families bind, not the pool total
            print(f"Family-depth ceiling: {ceiling} complete slips "
                  f"(pool/legs would suggest {total // args.legs if args.legs else 0}); "
                  f"depths {dict(depths.most_common())}")

        if not groups:
            print("No betslips could be built (no settleable selections in range).")
            return 1

        used = [s for _label, slip in groups for s in slip]
        enrich_odds(client, used)

        def section_of(label: str) -> str:
            if label.startswith("B"):
                return SECTION_TITLE
            return label.rsplit(" #", 1)[0]  # legacy per-category

        lines = preamble_lines(legs=args.legs, seed=seed, lo=lo, hi=hi, matches=len(pools),
                               max_slips=slips_b, win_pct=win_pct)
        current = None
        for label, slip in groups:
            sec = section_of(label)
            if sec != current:
                current = sec
                hdr = f"\n===== {sec} ====="
                print(hdr)
                lines.append(hdr)
            header = slip_header_line(label, slip)
            print(f"\n{header}")
            lines.append(header)
            for li, s in enumerate(slip, 1):
                leg = leg_line(li, s)
                print(leg)
                lines.append(leg)
            try:
                code = reserve(client, slip)
                msg = f"  >> BOOKING CODE: {code}"
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                msg = f"  >> reserve failed: {exc}"
            print(msg)
            lines.append(msg)
            lines.append("")
            time.sleep(0.5)

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        txt_path = out_dir / f"betslips_{stamp}.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nSaved {txt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
