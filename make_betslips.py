"""Build multiplier (accumulator) betslips from eljam3ia and reserve a booking code for each.

For the leagues in scope, this collects EVERY qualifying selection per match (price within the
target range/tolerance) into a pool, then greedily builds up to `--slips` accumulators (default 50)
of `--size` legs each (default 20). A match is unique WITHIN a slip, but may repeat ACROSS slips -
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
    py make_betslips.py                     # all leagues, 20 legs per slip, up to 50 slips
    py make_betslips.py --size 10
    py make_betslips.py --slips 20
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
OUTPUT_DIR = "output"

CATEGORY_ORDER = ["main", "combo DC", "1st half", "2nd half", "corners", "carte", "multigoals"]
PER_CATEGORY_SLIPS = 25  # default slips per category in --per-category mode

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
    parser.add_argument("--slips", type=int, default=MAX_SLIPS, help="max betslips per run (default 50)")
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

        slips = build_slips(pools, args.size, args.slips)
        if not slips:
            print("No betslips could be built (no qualifying selections in range).")
            return 1
        used = [s for slip in slips for s in slip]
        enrich_odds(client, used)  # enrich only the odds actually used

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        txt_path = out_dir / f"betslips_{stamp}.txt"
        lines = [f"Eljam3ia multiplier betslips - built {now_utc()}",
                 f"window {lo:g}..{hi:g}, {args.size} legs/slip, up to {args.slips} slips, "
                 f"{len(pools)} matches -> {len(slips)} betslips (matches may repeat across slips "
                 f"with different odds)",
                 "Load a code on eljam3ia.com: BETSLIP panel -> Enter Booking Code (before kickoff).", ""]

        for gi, slip in enumerate(slips, 1):
            combined = 1.0
            for s in slip:
                combined *= s["price"]
            header = (f"BETSLIP {gi}  ({len(slip)} legs, combined odds x{combined:.2f})"
                      + ("  [partial - fewer than requested]" if len(slip) < args.size else ""))
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

        txt_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nSaved {txt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
