"""Build multiplier (accumulator) betslips from eljam3ia and reserve a booking code for each.

For the same Top Leagues the scanner covers, this picks ONE qualifying selection per match
(the odd closest to TARGET_ODD, within tolerance), then partitions the matches into betslips of
GROUP_SIZE (default 10). No match is reused within a betslip or across betslips. Each betslip is
sent to Altenar's reserveBet endpoint, which returns a shareable Booking Code that anyone can load
on the site via the betslip's "Enter Booking Code" field.

A booking code only saves the selections (like sharing a filled-in slip) - it places no bet and
moves no money.

IMPORTANT (why the payload is so detailed): the Altenar betslip widget needs each stored selection
to carry the FULL context - the `market` object (with sportMarketId), plus sport/category/
championship/competitors, and an `odd` enriched with intSelectionId/intEventId (fetched from
GetOddsStates). A minimal {odd, event} reserve still returns a code, but the widget crashes when it
tries to render it ("Oops! This section of the sportsbook didn't load"). This builder reproduces the
exact shape the site itself stores when you click odds, so the codes load cleanly.

Usage:
    py make_betslips.py                     # all Top Leagues, 10 legs per slip
    py make_betslips.py --size 10
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
    API_BASE, DELAY_S, EPS, HEADERS, SPORT_ID, TARGET_ODD, TOLERANCE, TOP_LEAGUES,
    clean, fetch, get_events, now_utc, resolve_leagues,
)

BETSLIP_BASE = "https://sb2betslip-altenar2.biahosted.com/api/Betslip"
COUNTRY_CODE = "TN"
GROUP_SIZE = 10
OUTPUT_DIR = "output"

# body sent with every POST (reserveBet / GetOddsStates)
COMMON_BODY = {
    "culture": "en-GB", "timezoneOffset": -60, "integration": "eljam3ia",
    "deviceType": 1, "numFormat": "en-GB", "countryCode": COUNTRY_CODE,
}
POST_HEADERS = {**HEADERS, "Content-Type": "application/json", "Origin": "https://www.eljam3ia.com"}


def pick_selection(details: dict, lo: float, hi: float, target: float) -> dict | None:
    """Return {odd, market} for the qualifying odd closest to `target`, or None."""
    odds_by_id = {o["id"]: o for o in details.get("odds", [])}
    best, best_market, best_dist = None, None, None
    for market in details.get("markets", []) + details.get("childMarkets", []):
        if not clean(market.get("name")):
            continue
        odd_ids = market.get("desktopOddIds") or market.get("mobileOddIds") or []
        for group in odd_ids:
            for odd_id in group if isinstance(group, list) else [group]:
                odd = odds_by_id.get(odd_id)
                if odd is None or odd.get("oddStatus", 0) != 0:
                    continue
                try:
                    price = float(odd.get("price"))
                except (TypeError, ValueError):
                    continue
                if lo - EPS <= price <= hi + EPS:
                    dist = abs(price - target)
                    if best_dist is None or dist < best_dist:
                        best_dist, best, best_market = dist, odd, market
    if best is None:
        return None
    return {"odd": best, "market": best_market, "price": float(best["price"]),
            "label": clean(best.get("name")) or "?", "market_name": clean(best_market.get("name"))}


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
    parser.add_argument("--size", type=int, default=GROUP_SIZE, help="events per betslip (default 10)")
    parser.add_argument("--target", type=float, default=TARGET_ODD)
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--out", default=OUTPUT_DIR)
    args = parser.parse_args()

    wanted = args.league or TOP_LEAGUES
    lo, hi = args.target - args.tolerance, args.target + args.tolerance

    picks: list[dict] = []
    with httpx.Client(headers=POST_HEADERS, timeout=30) as client:
        found, missing = resolve_leagues(client, wanted)
        for name in missing:
            print(f"  ! league not on the menu right now (skipped): {name}")

        order = {name.strip().casefold(): i for i, name in enumerate(wanted)}
        found.sort(key=lambda lg: order.get(lg["name"].strip().casefold(), 999))

        for league in found:
            events = sorted(get_events(client, league["id"]), key=lambda e: e.get("startDate", ""))
            usable = 0
            for event in events:
                try:
                    details = fetch(client, "GetEventDetails", eventId=event["id"])
                except RuntimeError:
                    continue
                sel = pick_selection(details, lo, hi, args.target)
                if sel:
                    sel.update({
                        "league": clean(league["name"]), "event": event,
                        "match": clean(event.get("name")) or "?", "kickoff": event.get("startDate", ""),
                        "sport": details.get("sport"), "category": details.get("category"),
                        "championship": details.get("champ"), "competitors": details.get("competitors", []),
                    })
                    picks.append(sel)
                    usable += 1
                time.sleep(DELAY_S + random.uniform(0, 0.3))
            print(f"{clean(league['name'])}: {usable} events with a ~{args.target:g} selection")

        if not picks:
            print("No qualifying selections found.")
            return 1

        enrich_odds(client, picks)  # add intSelectionId/intEventId

        groups = [picks[i:i + args.size] for i in range(0, len(picks), args.size)]
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        txt_path = out_dir / f"betslips_{stamp}.txt"
        lines = [f"Eljam3ia multiplier betslips - built {now_utc()}",
                 f"target {args.target:g} (window {lo:g}..{hi:g}), {args.size} legs per slip, "
                 f"{len(picks)} events over {len(groups)} betslips",
                 "Load a code on eljam3ia.com: betslip panel -> Enter Booking Code. Do it before kickoff.", ""]

        for gi, group in enumerate(groups, 1):
            combined = 1.0
            for s in group:
                combined *= s["price"]
            header = (f"BETSLIP {gi}  ({len(group)} legs, combined odds x{combined:.2f})"
                      + ("  [partial - fewer than requested]" if len(group) < args.size else ""))
            print(f"\n{header}")
            lines.append(header)
            for li, s in enumerate(group, 1):
                leg = f"  {li:2}. {s['league']} - {s['match']} - {s['market_name']}: {s['label']} @ {s['price']:g}"
                print(leg)
                lines.append(leg)
            try:
                code = reserve(client, group)
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
