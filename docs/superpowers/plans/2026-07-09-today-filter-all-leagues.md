# DATE_FILTER "Only Today (23 h)" + All-Leagues Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the pipeline's default scan/betslip scope from "Top Leagues, all upcoming dates" to "**every football league, only matches kicking off within the next 23 hours**" (the site's TODAY → Football → check-all-boxes view), keeping the old behavior available via flags.

**Architecture:** Add a pure date-window filter and an all-leagues event source to `eljam3ia_odds_scanner.py` (the shared library of this project); wire both into the scanner, the betslip builder, and the `run_all.py` pipeline as `--hours` (default 23) and `--scope all|top` (default `all`). No browser automation — the menu's "Today" tab maps to a kickoff-time window on the API's complete event list, and "check all the boxes" maps to iterating every championship instead of the hardcoded `TOP_LEAGUES`.

**Tech Stack:** Python 3.11, `httpx` (runtime), `pytest` (dev/tests). Windows, `py` launcher.

## Global Constraints

- `DATE_FILTER = Only Today (23 h)` → constant `DATE_FILTER_HOURS = 23`; window is `[now, now + hours]` UTC; already-started (live) matches are EXCLUDED; `--hours 0` disables the filter.
- Default scope = ALL football leagues (`--scope all`); `--scope top` or `--league "<name>"` restores the previous behaviors.
- Politeness invariants (do not weaken): single-threaded, `DELAY_S = 0.7` s + jitter between event-detail calls, 3 retries with backoff, partial save on 403/429/Ctrl-C.
- Betslip selections must keep the FULL widget shape (market with `sportMarketId`, sport/category/championship/competitors, odd enriched via `GetOddsStates`) — regression here crashes the site UI.
- All names (league/match/market/selection) pass through `clean()` (whitespace-collapse); CSVs stay `utf-8-sig`.
- No new runtime dependencies. `pytest` is dev-only.
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora` (all paths below relative to it). Run commands from this directory.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `eljam3ia_odds_scanner.py` | Shared library + scanner CLI | Add `DATE_FILTER_HOURS`, `parse_utc()`, `filter_events_by_window()`, `get_all_football_events()`; new `--hours`/`--scope` flags; scope-aware main |
| `make_betslips.py` | Betslip builder CLI | Same flags; scope-aware event sourcing |
| `run_all.py` | Pipeline | Forward `--hours`/`--scope` |
| `tests/test_date_filter.py` | New: unit tests for the window filter | Create |
| `tests/test_all_leagues.py` | New: unit test for league tagging (offline, monkeypatched) | Create |
| `README.md`, `~/.claude/plans/prompt-eljam3ia-odds-cheerful-owl.md` | Docs / as-built spec | Parameter updates |

---

### Task 1: Date-window filter (`filter_events_by_window`)

**Files:**
- Create: `.gitignore`, `tests/test_date_filter.py`
- Modify: `eljam3ia_odds_scanner.py` (imports block + parameters block + new functions after `get_events`)

**Interfaces:**
- Produces: `DATE_FILTER_HOURS: float = 23` (module constant);
  `parse_utc(iso_str: str) -> datetime` (raises `ValueError` on bad input);
  `filter_events_by_window(events: list[dict], hours: float, now: datetime | None = None) -> list[dict]` — keeps events whose `startDate` (format `2026-07-05T20:00:00Z`) is within `[now, now+hours]`; `hours` falsy ⇒ returns `list(events)` unchanged. Tasks 2–4 import these.

- [ ] **Step 1: Initialize git repo and test scaffold** (this project has never been a repo)

```bash
git init
py -m pip install pytest
mkdir tests
```

Create `.gitignore` with exactly:

```
output/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_date_filter.py`:

```python
from datetime import datetime, timezone

from eljam3ia_odds_scanner import filter_events_by_window

NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def ev(start):
    return {"id": 1, "startDate": start}


def test_keeps_event_inside_window():
    assert filter_events_by_window([ev("2026-07-09T20:00:00Z")], 23, now=NOW)


def test_drops_event_beyond_window():
    assert filter_events_by_window([ev("2026-07-10T12:00:00Z")], 23, now=NOW) == []


def test_keeps_event_exactly_at_window_end():
    assert filter_events_by_window([ev("2026-07-10T11:00:00Z")], 23, now=NOW)


def test_drops_already_started_event():
    assert filter_events_by_window([ev("2026-07-09T11:59:00Z")], 23, now=NOW) == []


def test_hours_zero_keeps_everything():
    events = [ev("2027-01-01T00:00:00Z"), ev("2020-01-01T00:00:00Z")]
    assert filter_events_by_window(events, 0, now=NOW) == events


def test_drops_unparseable_startdate():
    assert filter_events_by_window([{"id": 2, "startDate": ""}], 23, now=NOW) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -m pytest tests/test_date_filter.py -v`
Expected: 6 errors — `ImportError: cannot import name 'filter_events_by_window'`

- [ ] **Step 4: Implement** — three edits to `eljam3ia_odds_scanner.py`:

(a) imports: change `from datetime import datetime, timezone` to:

```python
from datetime import datetime, timedelta, timezone
```

(b) parameters block: directly under `OUTPUT_DIR = "output"` add:

```python
DATE_FILTER_HOURS = 23  # only events kicking off within the next N hours; 0 = all upcoming
```

(c) after the `get_events` function add:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -m pytest tests/test_date_filter.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add .gitignore tests/test_date_filter.py eljam3ia_odds_scanner.py
git commit -m "feat: add 23h date-window filter for events"
```

---

### Task 2: All-leagues event source (`get_all_football_events`)

**Files:**
- Modify: `eljam3ia_odds_scanner.py` (add function directly below `filter_events_by_window`)
- Test: `tests/test_all_leagues.py`

**Interfaces:**
- Consumes: `fetch(client, endpoint, **params)`, `clean(text)`, `SPORT_ID` (existing).
- Produces: `get_all_football_events(client: httpx.Client) -> list[dict]` — every upcoming football match event site-wide, each dict gaining `"_league": str` (cleaned league name, or `"League {champId}"` if unknown). Tasks 3–4 rely on `_league`.

- [ ] **Step 1: Write the failing test** — create `tests/test_all_leagues.py`:

```python
import eljam3ia_odds_scanner as sc


def test_get_all_football_events_tags_league(monkeypatch):
    def fake_fetch(client, endpoint, **params):
        if endpoint == "GetSportMenu":
            return {"champs": [{"id": 10, "name": "\tLiga X  "}]}
        assert endpoint == "GetEvents"
        return {"events": [{"id": 1, "champId": 10}, {"id": 2, "champId": 99}]}

    monkeypatch.setattr(sc, "fetch", fake_fetch)
    events = sc.get_all_football_events(None)
    assert events[0]["_league"] == "Liga X"
    assert events[1]["_league"] == "League 99"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_all_leagues.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'get_all_football_events'`

- [ ] **Step 3: Implement** — add below `filter_events_by_window` in `eljam3ia_odds_scanner.py`:

```python
def get_all_football_events(client: httpx.Client) -> list[dict]:
    """Every upcoming football match event site-wide, tagged with event["_league"]."""
    menu = fetch(client, "GetSportMenu", sportId=SPORT_ID, period=0)
    champ_names = {c["id"]: clean(c["name"]) for c in menu.get("champs", [])}
    data = fetch(client, "GetEvents", sportId=SPORT_ID)
    events = data.get("events", [])
    for event in events:
        event["_league"] = champ_names.get(event.get("champId")) or f"League {event.get('champId')}"
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m pytest tests/ -v`
Expected: 7 passed

- [ ] **Step 5: Live completeness check** (the sport-wide `GetEvents` must not be a capped subset):

```bash
py -c "import httpx, eljam3ia_odds_scanner as sc; c = httpx.Client(headers=sc.HEADERS, timeout=30); evs = sc.get_all_football_events(c); print('site-wide events:', len(evs)); champ = evs[0]['champId']; direct = sc.get_events(c, champ); mine = [e for e in evs if e.get('champId') == champ]; print(f'champ {champ}: direct={len(direct)} site-wide={len(mine)}')"
```

Expected: `site-wide events:` in the hundreds; the two per-champ counts EQUAL.
**Contingency (only if counts differ):** replace the body of `get_all_football_events` with a per-champ loop — keep the same signature and `_league` contract:

```python
def get_all_football_events(client: httpx.Client) -> list[dict]:
    """Every upcoming football match event site-wide, tagged with event["_league"]."""
    menu = fetch(client, "GetSportMenu", sportId=SPORT_ID, period=0)
    events: list[dict] = []
    for champ in menu.get("champs", []):
        if champ.get("eventsCount", 0) == 0:
            continue
        champ_events = get_events(client, champ["id"])
        for event in champ_events:
            event["_league"] = clean(champ["name"])
        events += champ_events
        time.sleep(0.3)
    return events
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_all_leagues.py eljam3ia_odds_scanner.py
git commit -m "feat: site-wide all-leagues event source with league tagging"
```

---

### Task 3: Scanner CLI wiring (`--hours`, `--scope`)

**Files:**
- Modify: `eljam3ia_odds_scanner.py` — `main()` only (argparse block, league/event collection block, `tag` logic, meta dict)

**Interfaces:**
- Consumes: Task 1 `DATE_FILTER_HOURS`/`filter_events_by_window`, Task 2 `get_all_football_events`.
- Produces: CLI flags `--hours <float>` (default `DATE_FILTER_HOURS`) and `--scope all|top` (default `all`) — Task 5 forwards these names verbatim. Meta gains keys `date_filter` and `scope`.

- [ ] **Step 1: Add the flags** — in `main()`'s argparse block, after the `--out` line add:

```python
    parser.add_argument("--hours", type=float, default=DATE_FILTER_HOURS,
                        help="only events kicking off within N hours (0 = all upcoming)")
    parser.add_argument("--scope", choices=["all", "top"], default="all",
                        help="'all' = every football league, 'top' = Top Leagues menu section")
```

- [ ] **Step 2: Replace the setup lines.** Replace:

```python
    leagues_wanted = args.league or TOP_LEAGUES
```

with:

```python
    if args.league:
        leagues_requested = "; ".join(args.league)
    elif args.scope == "top":
        leagues_requested = "; ".join(TOP_LEAGUES)
    else:
        leagues_requested = "all football leagues"
```

and replace the `tag = ...` line with:

```python
    if args.league:
        tag = "custom"
    elif args.scope == "all":
        tag = "today" if args.hours else "all_football"
    else:
        tag = "top_leagues"
```

- [ ] **Step 3: Replace the league/event collection block.** Replace everything from `found, missing = resolve_leagues(client, leagues_wanted)` through the `print(f"{league['name']}: {len(events)} events")` loop with:

```python
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
```

- [ ] **Step 4: Update the meta dict.** In the `write_meta(...)` call, replace the `"leagues_requested"` line with `"leagues_requested": leagues_requested,` and insert after the `"accept_window"` line:

```python
        "date_filter": f"next {args.hours:g} hours" if args.hours else "all upcoming",
        "scope": "custom leagues" if args.league else args.scope,
```

- [ ] **Step 5: Regression-check the unit tests, then live smoke run**

Run: `py -m pytest tests/ -v` → Expected: 7 passed.
Run: `py eljam3ia_odds_scanner.py`
Expected: first line like `All football (next 23h): NN events in MM leagues`, then per-event progress, then `Wrote output\odds_matrix_today_<stamp>.csv (...)`. Verify the CSV's `Kickoff (UTC)` values are all within the next 23 h and the meta file shows `date_filter,next 23 hours` and `scope,all`.
Also verify the old mode still works: `py eljam3ia_odds_scanner.py --scope top --hours 0` → prints the ten Top-Leagues lines like before.

- [ ] **Step 6: Commit**

```bash
git add eljam3ia_odds_scanner.py
git commit -m "feat: scanner defaults to all leagues within 23h window (--hours/--scope)"
```

---

### Task 4: Betslip builder wiring

**Files:**
- Modify: `make_betslips.py` — import list, argparse block, event-collection loop in `main()`

**Interfaces:**
- Consumes: `DATE_FILTER_HOURS`, `filter_events_by_window`, `get_all_football_events` (Tasks 1–2); existing `pick_selection`, `enrich_odds`, `reserve`.
- Produces: same `--hours`/`--scope` flags as the scanner (Task 5 forwards them). Picks keep keys `league/event/match/kickoff/sport/category/championship/competitors` unchanged.

- [ ] **Step 1: Extend the import** from `eljam3ia_odds_scanner` to:

```python
from eljam3ia_odds_scanner import (
    API_BASE, DATE_FILTER_HOURS, DELAY_S, EPS, HEADERS, SPORT_ID, TARGET_ODD, TOLERANCE,
    TOP_LEAGUES, clean, fetch, filter_events_by_window, get_all_football_events,
    get_events, now_utc, resolve_leagues,
)
```

- [ ] **Step 2: Add the flags** — in `main()`'s argparse block, after `--out` add (identical to Task 3):

```python
    parser.add_argument("--hours", type=float, default=DATE_FILTER_HOURS,
                        help="only events kicking off within N hours (0 = all upcoming)")
    parser.add_argument("--scope", choices=["all", "top"], default="all",
                        help="'all' = every football league, 'top' = Top Leagues menu section")
```

Also delete the now-unused line `wanted = args.league or TOP_LEAGUES`.

- [ ] **Step 3: Replace the event-collection block.** Replace everything from `found, missing = resolve_leagues(client, wanted)` through the end of the `for league in found:` loop (up to but not including the `# partition into betslips` comment) with:

```python
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

        for league_name, events in league_events:
            usable = 0
            for event in sorted(events, key=lambda e: e.get("startDate", "")):
                try:
                    details = fetch(client, "GetEventDetails", eventId=event["id"])
                except RuntimeError:
                    continue
                sel = pick_selection(details, lo, hi, args.target)
                if sel:
                    sel.update({"league": league_name, "event": event,
                                "match": clean(event.get("name")) or "?",
                                "kickoff": event.get("startDate", ""),
                                "sport": details.get("sport"), "category": details.get("category"),
                                "championship": details.get("champ"),
                                "competitors": details.get("competitors", [])})
                    picks.append(sel)
                    usable += 1
                time.sleep(DELAY_S + random.uniform(0, 0.3))
            print(f"{league_name}: {usable} events with a ~{args.target:g} selection")
```

- [ ] **Step 4: Live smoke run**

Run: `py make_betslips.py`
Expected: per-league lines for today's slate only, then `BETSLIP n` blocks each ending `>> BOOKING CODE: <code>`, saved to `output\betslips_<stamp>.txt`. Every listed kickoff must be within 23 h.
Verify one code round-trips: `py -c "import httpx; print(httpx.get('https://sb2betslip-altenar2.biahosted.com/api/Betslip/FindReservedBet?culture=en-GB&timezoneOffset=-60&integration=eljam3ia&deviceType=1&numFormat=en-GB&countryCode=TN&key=<CODE>').json()['Result'] is not None)"` → `True`. (Full UI load-check happens in Task 5.)

- [ ] **Step 5: Commit**

```bash
git add make_betslips.py
git commit -m "feat: betslips follow today-window and all-leagues scope"
```

---

### Task 5: Pipeline forwarding, docs, end-to-end verification

**Files:**
- Modify: `run_all.py` (argparse + forward loop), `README.md` (params/usage), `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md` (parameters section)

**Interfaces:**
- Consumes: `--hours`/`--scope` flags from Tasks 3–4 (names must match exactly).

- [ ] **Step 1: Forward the flags in `run_all.py`.** In the argparse block add:

```python
    parser.add_argument("--hours", type=float, default=None, help="kickoff window in hours (forwarded)")
    parser.add_argument("--scope", choices=["all", "top"], default=None, help="league scope (forwarded)")
```

and change the forwarding loop to:

```python
    for flag in ("target", "tolerance", "hours", "scope"):
        if getattr(args, flag) is not None:
            forward += [f"--{flag}", str(getattr(args, flag))]
```

- [ ] **Step 2: Update `README.md`.** In the "Automatic mode" section, after the code block of `run_all.py` examples, add:

```
py run_all.py --hours 0 --scope top   # old behavior: Top Leagues, all upcoming dates
```

and add this sentence to the section text: "By default every run covers **all football leagues with matches in the next 23 hours** (`DATE_FILTER = Only Today (23 h)`); use `--hours`/`--scope` to widen."

- [ ] **Step 3: Update the as-built spec** `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`: in the "Context" section, change capability 1's first line to read "for every football league with a match in the next 23 hours (DATE_FILTER = Only Today (23 h); site menu: TODAY → Football → all boxes)…" and add to the parameters mention: `DATE_FILTER_HOURS = 23`, `scope default = all`.

- [ ] **Step 4: Full pipeline test**

Run: `py run_all.py`
Expected: Step 1/2 prints `All football (next 23h): ...`; Step 2/2 reserves codes; `summary.txt` in the new `output/run_*/` folder lists matrix stats + booking codes.

- [ ] **Step 5: Scheduled-task end-to-end** (the daily 09:00 task must inherit the new defaults)

Run: `schtasks /Run /TN "Eljam3ia Odds Pipeline"` then poll until the new `output/run_*/summary.txt` exists.
Expected: summary shows today-window scope; task ends `Ready`, `LastTaskResult 0`.
Then load ONE fresh booking code on the live site (BETSLIP panel → Enter Booking Code) and confirm the legs render without the "Oops" crash.

- [ ] **Step 6: Commit**

```bash
git add run_all.py README.md
git commit -m "feat: pipeline forwards --hours/--scope; docs for today-window default"
```
