"""Build multiplier (accumulator) betslips from eljam3ia and reserve a booking code for each.

For the leagues in scope, this collects EVERY qualifying selection per match (price within the
target range/tolerance) into a pool, then greedily builds two sets per run: SET A (up to
`--slips-a`, default 50, all-odds) and SET B (up to `--slips-b`, default 25, diversified across
7 market families) of `--size` legs each (default 20). A match is unique WITHIN a slip, but may
repeat ACROSS slips -
each repeat spends a different, not-yet-used qualifying odd for that match, which multiplies the
number of distinct betslips (and booking codes) that can be produced from the same pool of matches.
Each betslip is sent to Altenar's reserveBet endpoint, which returns a shareable Booking Code that
anyone can load on the site via the betslip's "Enter Booking Code" field.

A booking code only saves the selections (like sharing a filled-in slip) - it places no bet and
moves no money.

IMPORTANT (why the payload is so detailed): the Altenar betslip widget needs each stored selection
to carry the FULL context - the `market` object (with sportMarketId), plus sport/category/
championship/competitors, and an `odd` enriched with intSelectionId/intEventId (fetched from
GetOddsStates). A minimal {odd, event} reserve still returns a code, but the widget crashes when it
tries to render it ("Oops! This section of the sportsbook didn't load"). This builder reproduces the
exact shape the site itself stores when you click odds, so the codes load cleanly.

Usage:
    py make_betslips.py                     # all leagues, SET A (<=50) + SET B (<=25), 20 legs/slip
    py make_betslips.py --size 10
    py make_betslips.py --set a --slips-a 20
    py make_betslips.py --league "World Cup 2026" --league "Serie A"

Odds are live: load a code before its matches kick off, or that leg shows as unavailable.
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from eljam3ia_odds_scanner import (
    API_BASE, DATE_FILTER_HOURS, DELAY_S, EPS, HEADERS, SPORT_ID, TARGET_MAX, TARGET_MIN,
    TOLERANCE, TOP_LEAGUES, clean, fetch, filter_events_by_window, get_all_football_events,
    get_events, now_utc, parse_target, resolve_leagues,
)

BETSLIP_BASE = "https://sb2betslip-altenar2.biahosted.com/api/Betslip"
COUNTRY_CODE = "TN"
GROUP_SIZE = 20   # legs per betslip
MAX_SLIPS = 50    # max betslips per run
SLIPS_B = 25      # max slips for the diversified (soft round-robin) builder
OUTPUT_DIR = "output"

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
                    market_prices = [
                        odds_by_id[i].get("price")
                        for grp in (market.get("desktopOddIds") or market.get("mobileOddIds") or [])
                        for i in (grp if isinstance(grp, list) else [grp])
                        if i in odds_by_id and odds_by_id[i].get("oddStatus", 0) == 0
                    ]
                    out.append({"odd": odd, "market": market, "price": price,
                                "label": clean(odd.get("name")) or "?", "market_name": name,
                                "novig_prob": novig_prob(price, market_prices)})
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


def novig_prob(price: float, market_prices: list[float]) -> float:
    """No-vig implied probability of one outcome, normalized over its market's active outcomes.

    A market with fewer than 2 valid outcomes cannot be de-vigged (no counterpart to strip the
    margin against), so fall back to the raw implied probability 1/price rather than a misleading 1.0.
    """
    try:
        raw = 1.0 / float(price)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    inv = []
    for p in market_prices:
        try:
            fp = float(p)
        except (TypeError, ValueError):
            continue
        if fp:
            inv.append(1.0 / fp)
    return raw / sum(inv) if len(inv) >= 2 else raw


def slip_win_pct(slip: list[dict]) -> float:
    """Model win probability of a slip as a percent: 100 * product of legs' no-vig probs."""
    if not slip:
        return 0.0
    prob = 1.0
    for s in slip:
        prob *= s.get("novig_prob", 0.0)
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


def build_diversified_slips(pools: dict[str, list[dict]], size: int,
                            max_slips: int) -> list[list[dict]]:
    """Greedy family round-robin: each slip spreads legs across CATEGORY_ORDER, best-effort.

    Distinct match per slip; each selection (odd) consumed once overall; at most one trailing
    partial. Thin families contribute what they have; remaining legs fill from any family.
    """
    if size <= 0:
        return []
    # per-category -> match_key -> list of selections (copies so we can pop without touching caller)
    by_cat: dict[str, dict[str, list[dict]]] = {c: {} for c in CATEGORY_ORDER}
    for key, sels in pools.items():
        for s in sels:
            cat = market_category(s["market_name"])
            by_cat.setdefault(cat, {}).setdefault(key, []).append(s)

    def remaining_matches() -> set:
        return {k for cat in by_cat.values() for k, v in cat.items() if v}

    slips: list[list[dict]] = []
    while len(slips) < max_slips:
        if len(remaining_matches()) < 2:
            break
        slip: list[dict] = []
        used_matches: set = set()
        progressed = True
        while len(slip) < size and progressed:
            progressed = False
            for cat in CATEGORY_ORDER:
                if len(slip) >= size:
                    break
                # eligible matches in this family: have stock and not already in this slip
                candidates = [(k, v) for k, v in by_cat.get(cat, {}).items() if v and k not in used_matches]
                if not candidates:
                    continue
                k, v = max(candidates, key=lambda kv: len(kv[1]))
                slip.append(v.pop())
                used_matches.add(k)
                progressed = True
        if not slip:
            break
        slips.append(slip)
        if len(slip) < size:  # could not fill -> trailing partial
            break
    return slips


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build multiplier betslips and reserve booking codes.")
    parser.add_argument("--league", action="append", help="league name (repeatable); default: Top Leagues")
    parser.add_argument("--size", type=int, default=GROUP_SIZE, help="legs per betslip (default 20)")
    parser.add_argument("--set", choices=["both", "a", "b"], default="both",
                        help="which set(s) to build: a=all-odds, b=7-category diversified")
    parser.add_argument("--slips-a", type=int, default=MAX_SLIPS, help="max SET A slips (default 50)")
    parser.add_argument("--slips-b", type=int, default=SLIPS_B, help="max SET B slips (default 25)")
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
                for i, slip in enumerate(build_slips(cat_pools, args.size, args.slips_b), 1):
                    groups.append((f"{cat} #{i}", slip))
        else:
            if args.set in ("both", "a"):
                for i, slip in enumerate(build_slips(pools, args.size, args.slips_a), 1):
                    groups.append((f"A{i}", slip))
            if args.set in ("both", "b"):
                for i, slip in enumerate(build_diversified_slips(pools, args.size, args.slips_b), 1):
                    groups.append((f"B{i}", slip))

        if not groups:
            print("No betslips could be built (no qualifying selections in range).")
            return 1

        used = [s for _label, slip in groups for s in slip]
        enrich_odds(client, used)

        def section_of(label: str) -> str:
            if label.startswith("A"):
                return "SET A: all-odds"
            if label.startswith("B"):
                return "SET B: 7-category diversified"
            return label.rsplit(" #", 1)[0]  # legacy per-category

        lines = [f"Eljam3ia dual-set betslips - built {now_utc()}",
                 f"window {lo:g}..{hi:g}, {args.size} legs/slip; "
                 f"SET A all-odds (<= {args.slips_a}), SET B 7-category diversified (<= {args.slips_b}), "
                 f"{len(pools)} matches",
                 "Load a code on eljam3ia.com: BETSLIP panel -> Enter Booking Code (before kickoff).", ""]
        current = None
        for label, slip in groups:
            sec = section_of(label)
            if sec != current:
                current = sec
                hdr = f"\n===== {sec} ====="
                print(hdr)
                lines.append(hdr)
            combined = 1.0
            for s in slip:
                combined *= s["price"]
            win = slip_win_pct(slip)
            header = (f"BETSLIP {label}  ({len(slip)} legs, combined odds x{combined:.2f}, win% {win:.3g})"
                      + ("  [partial]" if len(slip) < args.size else ""))
            print(f"\n{header}")
            lines.append(header)
            for li, s in enumerate(slip, 1):
                leg = f"  {li:2}. {s['league']} - {s['match']} - {s['market_name']}: {s['label']} @ {s['price']:g}"
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
