"""Eljam3ia odds scanner.

Scans every match in all football leagues (default --scope all) on https://www.eljam3ia.com/betting
(an Altenar sportsbook widget), within the today window (kickoff in the next N hours), and
collects every selection whose decimal odd falls within the target RANGE TARGET_MIN..TARGET_MAX
(1.30..1.45 by default), widened by +/- TOLERANCE to the accept window [1.25, 1.50].
Talks directly to the Altenar JSON API - no browser.

Output: a matrix CSV (rows = matches, columns = market names, cells = "selection @ odd"
entries joined by "; ") plus a _meta.csv sidecar describing the run.

Usage:
    py eljam3ia_odds_scanner.py                          # all leagues (today window), range 1.30..1.45
    py eljam3ia_odds_scanner.py --league "World Cup 2026"
    py eljam3ia_odds_scanner.py --target 2.0 --tolerance 0.1 --out output
"""

import argparse
import csv
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------- parameters
TARGET_ODD = 1.40  # legacy single-value default (kept for back-compat imports)
TARGET_MIN = 1.30  # target range low end
TARGET_MAX = 1.45  # target range high end; window = [TARGET_MIN - TOLERANCE, TARGET_MAX + TOLERANCE]
TOLERANCE = 0.05  # window = [TARGET_MIN - TOLERANCE, TARGET_MAX + TOLERANCE] = [1.25, 1.50]
SPORT_ID = 66  # Football
TOP_LEAGUES = [
    "World Cup 2026",
    "Euro 2028",
    "UEFA Champions League",
    "UEFA Europa League",
    "Premier League",
    "LaLiga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Liga Profesional",
]
DELAY_S = 0.7  # polite delay between event requests (plus jitter)
OUTPUT_DIR = "output"
DATE_FILTER_HOURS = 23  # only events kicking off within the next N hours; 0 = all upcoming
INCLUDE_EMPTY_MARKET_COLUMNS = False  # True = one column per market seen, even if all blank

API_BASE = "https://sb2frontend-1-altenar2.biahosted.com/api/Widget"
COMMON_PARAMS = {
    "culture": "en-GB",  # keeps market names in English
    "timezoneOffset": "-60",
    "integration": "eljam3ia",
    "deviceType": "1",
    "numFormat": "en-GB",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.eljam3ia.com/",
    "Accept": "application/json",
}
EPS = 1e-9


class BlockedError(Exception):
    """Raised when the API keeps rejecting us (403/429) - triggers a partial save."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_target(text) -> tuple[float, float]:
    """'1.3..1.45' -> (1.3, 1.45); a single value -> (v, v). Raises ValueError on bad input."""
    if isinstance(text, (int, float)):
        return float(text), float(text)
    parts = [p for p in str(text).split("..") if p != ""]
    nums = [float(p) for p in parts]  # ValueError propagates on non-numeric
    if not nums:
        raise ValueError(f"empty target: {text!r}")
    lo, hi = min(nums), max(nums)
    return lo, hi


def clean(text: str) -> str:
    """Collapse any run of whitespace (incl. feed tabs) to a single space and trim."""
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(client: httpx.Client, endpoint: str, **params) -> dict:
    """GET an API endpoint with the common query string, retries and backoff."""
    url = f"{API_BASE}/{endpoint}"
    last_error = None
    for attempt in range(3):
        try:
            resp = client.get(url, params={**COMMON_PARAMS, **params})
            if resp.status_code in (403, 429):
                raise BlockedError(f"{endpoint} -> HTTP {resp.status_code} (rate limited or blocked)")
            resp.raise_for_status()
            return resp.json()
        except BlockedError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"{endpoint} failed after 3 attempts: {last_error}")


def resolve_leagues(client: httpx.Client, wanted: list[str]) -> tuple[list[dict], list[str]]:
    """Match requested league names against the sport menu. Returns (found, missing)."""
    menu = fetch(client, "GetSportMenu", sportId=SPORT_ID, period=0)
    champs = {c["name"].strip().casefold(): c for c in menu.get("champs", [])}
    found, missing = [], []
    for name in wanted:
        champ = champs.get(name.strip().casefold())
        if champ:
            found.append({"id": champ["id"], "name": champ["name"].strip(),
                          "eventsCount": champ.get("eventsCount", 0)})
        else:
            missing.append(name)
    return found, missing


def get_events(client: httpx.Client, champ_id: int) -> list[dict]:
    data = fetch(client, "GetEvents", champIds=champ_id, sportId=SPORT_ID)
    return data.get("events", [])


def parse_utc(iso_str: str) -> datetime:
    return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def filter_events_by_window(events: list[dict], hours: float,
                            now: datetime | None = None) -> list[dict]:
    """Keep events kicking off within [now, now + hours]. Falsy hours keeps everything."""
    if not hours:
        return list(events)
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    kept = []
    for event in events:
        try:
            start = parse_utc(event.get("startDate") or "")
        except ValueError:
            continue
        if now <= start <= end:
            kept.append(event)
    return kept


def get_all_football_events(client: httpx.Client) -> list[dict]:
    """Every upcoming football match event site-wide, tagged with event["_league"]."""
    menu = fetch(client, "GetSportMenu", sportId=SPORT_ID, period=0)
    champ_names = {c["id"]: clean(c["name"]) for c in menu.get("champs", [])}
    data = fetch(client, "GetEvents", sportId=SPORT_ID)
    events = data.get("events", [])
    for event in events:
        event["_league"] = champ_names.get(event.get("champId")) or f"League {event.get('champId')}"
    return events


def qualifying_selections(details: dict, lo: float, hi: float) -> dict[str, list[str]]:
    """market name -> ["selection @ odd", ...] for odds inside [lo, hi]."""
    odds_by_id = {o["id"]: o for o in details.get("odds", [])}
    hits: dict[str, list[str]] = {}
    seen: set[tuple[str, int]] = set()
    for market in details.get("markets", []) + details.get("childMarkets", []):
        name = clean(market.get("name"))
        if not name:
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
                if lo - EPS <= price <= hi + EPS and (name, odd_id) not in seen:
                    seen.add((name, odd_id))
                    hits.setdefault(name, []).append(f"{clean(odd.get('name')) or '?'} @ {price:g}")
    return hits


def write_matrix(rows: list[dict], path: Path) -> tuple[list[str], int]:
    """Write the matrix CSV. Returns (market columns, qualifying cell count)."""
    counts: dict[str, int] = {}
    for row in rows:
        for market in row["hits"]:
            counts[market] = counts.get(market, 0) + 1
        if INCLUDE_EMPTY_MARKET_COLUMNS:
            for market in row["all_markets"]:
                counts.setdefault(market, 0)
    columns = sorted(counts, key=lambda m: (-counts[m], m.casefold()))
    lead = ["League", "Match", "Kickoff (UTC)", "Event ID", "Scraped At (UTC)"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(lead + columns)
        for row in rows:
            writer.writerow(
                [row["league"], row["match"], row["kickoff"], row["event_id"], row["scraped_at"]]
                + ["; ".join(row["hits"].get(m, [])) for m in columns]
            )
    return columns, sum(counts.values())


def write_meta(path: Path, info: dict) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "value"])
        for key, value in info.items():
            writer.writerow([key, value])


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan eljam3ia.com odds for selections near a target.")
    parser.add_argument("--league", action="append",
                        help="league name (repeatable); default: the site's Top Leagues section")
    parser.add_argument("--target", default=f"{TARGET_MIN}..{TARGET_MAX}",
                        help="odd range 'min..max' (or a single value)")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--out", default=OUTPUT_DIR)
    parser.add_argument("--hours", type=float, default=DATE_FILTER_HOURS,
                        help="only events kicking off within N hours (0 = all upcoming)")
    parser.add_argument("--scope", choices=["all", "top"], default="all",
                        help="'all' = every football league, 'top' = Top Leagues menu section")
    args = parser.parse_args()

    if args.league:
        leagues_requested = "; ".join(args.league)
    elif args.scope == "top":
        leagues_requested = "; ".join(TOP_LEAGUES)
    else:
        leagues_requested = "all football leagues"
    tmin, tmax = parse_target(args.target)
    lo, hi = tmin - args.tolerance, tmax + args.tolerance
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.league:
        tag = "custom"
    elif args.scope == "all":
        tag = "today" if args.hours else "all_football"
    else:
        tag = "top_leagues"
    matrix_path = out_dir / f"odds_matrix_{tag}_{stamp}.csv"
    meta_path = out_dir / f"odds_matrix_{tag}_{stamp}_meta.csv"

    started = now_utc()
    rows: list[dict] = []
    failed: list[str] = []
    partial_reason = ""

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        missing: list[str] = []
        events_by_league: list[tuple[dict, list]] = []
        if args.league or args.scope == "top":
            found, missing = resolve_leagues(client, args.league or TOP_LEAGUES)
            for name in missing:
                print(f"  ! league not on the menu right now (skipped): {name}")
            for league in found:
                events = filter_events_by_window(get_events(client, league["id"]), args.hours)
                events_by_league.append((league, events))
                print(f"{league['name']}: {len(events)} events")
        else:
            all_events = filter_events_by_window(get_all_football_events(client), args.hours)
            by_league: dict[str, list] = {}
            for event in all_events:
                by_league.setdefault(event["_league"], []).append(event)
            events_by_league = [({"name": name}, evs) for name, evs in sorted(by_league.items())]
            window = f"next {args.hours:g}h" if args.hours else "all upcoming"
            print(f"All football ({window}): {len(all_events)} events in {len(by_league)} leagues")
        total = sum(len(ev) for _, ev in events_by_league)

        done = 0
        try:
            for league, events in events_by_league:
                for event in sorted(events, key=lambda e: e.get("startDate", "")):
                    done += 1
                    try:
                        details = fetch(client, "GetEventDetails", eventId=event["id"])
                        hits = qualifying_selections(details, lo, hi)
                        match_name = clean(event.get("name")) or "?"
                        rows.append({
                            "league": clean(league["name"]),
                            "match": match_name,
                            "kickoff": event.get("startDate", ""),
                            "event_id": event["id"],
                            "scraped_at": now_utc(),
                            "hits": hits,
                            "all_markets": {clean(m.get("name"))
                                            for m in details.get("markets", [])
                                            + details.get("childMarkets", [])},
                        })
                        n = sum(len(v) for v in hits.values())
                        print(f"  [{done}/{total}] {match_name} - {n} qualifying")
                    except RuntimeError as exc:
                        failed.append(f"{event.get('name', '?')} (id {event['id']}): {exc}")
                        print(f"  [{done}/{total}] {event.get('name', '?')} - FAILED, continuing")
                    time.sleep(DELAY_S + random.uniform(0, 0.3))
        except KeyboardInterrupt:
            partial_reason = "interrupted by user (Ctrl-C)"
        except BlockedError as exc:
            partial_reason = f"stopped: {exc}"

    if partial_reason:
        print(f"\n! Partial run - {partial_reason}. Saving what was collected.")

    columns, cell_count = write_matrix(rows, matrix_path)
    write_meta(meta_path, {
        "site": "https://www.eljam3ia.com/betting (Altenar API)",
        "leagues_requested": leagues_requested,
        "leagues_scanned": "; ".join(f"{lg['name']} ({len(ev)} events)" for lg, ev in events_by_league),
        "leagues_not_found": "; ".join(missing) or "none",
        "target_range": f"{tmin:g}..{tmax:g}",
        "tolerance": args.tolerance,
        "accept_window": f"{lo:g} .. {hi:g}",
        "date_filter": f"next {args.hours:g} hours" if args.hours else "all upcoming",
        "scope": "custom leagues" if args.league else args.scope,
        "run_started_utc": started,
        "run_finished_utc": now_utc(),
        "events_scanned": len(rows),
        "events_failed": len(failed),
        "failed_events": "; ".join(failed) or "none",
        "market_columns": len(columns),
        "qualifying_cells": cell_count,
        "partial_run": partial_reason or "no",
    })
    print(f"\nWrote {matrix_path} ({len(rows)} rows x {len(columns)} market columns, "
          f"{cell_count} qualifying cells)")
    print(f"Wrote {meta_path}")
    return 1 if partial_reason else 0


if __name__ == "__main__":
    sys.exit(main())
