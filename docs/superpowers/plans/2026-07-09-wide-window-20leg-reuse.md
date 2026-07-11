# Wide Window + 20-Leg Reusable Betslips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the qualifying window to a **target range 1.30–1.45 (±0.05 → accept [1.25, 1.50])** and change the betslip builder to produce **up to 50 twenty-leg accumulators per run**, where a match may repeat across slips as long as each reuse consumes a **different odd ID** (matches stay unique *within* a slip).

**Architecture:** Two decoupled changes to the existing shared library. (1) `eljam3ia_odds_scanner.py` gains a target *range* (`TARGET_MIN`/`TARGET_MAX` + `parse_target`) so `--target` accepts `"1.3..1.45"`; the scan window widens accordingly. (2) `make_betslips.py` stops picking one selection per match and instead **collects every qualifying selection per match into a pool**, then a pure `build_slips()` greedily forms 20-leg slips by consuming selections (most-remaining match first), giving cross-slip match reuse with a fresh odd each time. Odds are enriched (GetOddsStates) only for the selections actually used, then each slip is reserved for a booking code.

**Tech Stack:** Python 3.11, `httpx` (runtime), `pytest` (dev). Windows, `py` launcher. Existing Altenar API (frontend `GetSportMenu`/`GetEvents`/`GetEventDetails`/`GetOddsStates`; betslip `reserveBet`/`FindReservedBet`).

## Global Constraints

- Window: `TARGET_MIN = 1.30`, `TARGET_MAX = 1.45`, `TOLERANCE = 0.05` → accept `[TARGET_MIN - TOLERANCE, TARGET_MAX + TOLERANCE]` = **[1.25, 1.50]**. `--target` accepts `"min..max"` or a single float (single ⇒ min=max).
- Betslip: `--size` legs per slip default **20**; `--slips` max slips default **50**; produce as many *full* 20-leg slips as the pool supports, then at most one trailing partial (≥2 legs); stop early if fewer than 2 matches still have an unused selection.
- Reuse rule: a match appears **at most once per slip**; across slips each of its qualifying odd IDs is used **at most once** (consume-from-pool guarantees both).
- Betslip selections MUST keep the FULL widget shape (`market` with `sportMarketId`; `sport`/`category`/`championship`/`competitors`; odd enriched with `intSelectionId`/`intEventId` from `GetOddsStates`) — regression crashes the site UI ("Oops! This section didn't load").
- Keep today-window + all-leagues defaults (`DATE_FILTER_HOURS = 23`, `--hours`/`--scope`) and politeness invariants (single-threaded, `DELAY_S = 0.7` s + jitter between event-detail calls, 3 retries + backoff, partial save on 403/429/Ctrl-C). Enrichment is batched (≤50 odds/POST) over only the used odds.
- Names pass through `clean()`; CSVs `utf-8-sig`. No new runtime deps.
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`. Run commands from there.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `eljam3ia_odds_scanner.py` | Shared lib + scanner | Add `TARGET_MIN`/`TARGET_MAX`/`parse_target`; keep `TARGET_ODD` as legacy alias; widen defaults; `--target` range; meta `target_range` |
| `make_betslips.py` | Betslip builder | Add `collect_selections`, `build_slips`; rewrite `main()` for pooled multi-slip reuse; `--size 20`, `--slips 50` |
| `run_all.py` | Pipeline | Forward `--slips`; pass `--target` as string |
| `tests/test_target_range.py` | New | `parse_target` cases |
| `tests/test_build_slips.py` | New | `build_slips` + `collect_selections` |
| `README.md`, `~/.claude/plans/prompt-eljam3ia-odds-cheerful-owl.md` | Docs / as-built spec + Browser flow | Parameter + browser-flow updates |

---

### Task 1: Target range in the scanner (`parse_target`, wide window)

**Files:**
- Modify: `eljam3ia_odds_scanner.py` (parameters block; `main()` argparse + window + meta)
- Test: `tests/test_target_range.py`

**Interfaces:**
- Produces: `TARGET_MIN: float = 1.30`, `TARGET_MAX: float = 1.45` (constants);
  `parse_target(text: str | float) -> tuple[float, float]` — `"1.3..1.45"` → `(1.3, 1.45)`; a bare number → `(n, n)`; min>max is swapped; bad input raises `ValueError`. Tasks 3 & 5 import `parse_target`, `TARGET_MIN`, `TARGET_MAX`.
- `TARGET_ODD = 1.40` stays defined (legacy import for make_betslips until Task 3).

- [ ] **Step 1: Write the failing test** — create `tests/test_target_range.py`:

```python
import pytest

from eljam3ia_odds_scanner import parse_target


def test_range_string():
    assert parse_target("1.3..1.45") == (1.3, 1.45)


def test_single_value_string():
    assert parse_target("1.4") == (1.4, 1.4)


def test_single_float():
    assert parse_target(1.4) == (1.4, 1.4)


def test_reversed_range_is_sorted():
    assert parse_target("1.45..1.3") == (1.3, 1.45)


def test_bad_input_raises():
    with pytest.raises(ValueError):
        parse_target("abc")
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_target_range.py -v`
Expected: ImportError — `cannot import name 'parse_target'`

- [ ] **Step 3: Implement** — (a) in the parameters block of `eljam3ia_odds_scanner.py` replace the line `TARGET_ODD = 1.40` with:

```python
TARGET_ODD = 1.40  # legacy single-value default (kept for back-compat imports)
TARGET_MIN = 1.30  # target range low end
TARGET_MAX = 1.45  # target range high end; window = [TARGET_MIN - TOLERANCE, TARGET_MAX + TOLERANCE]
```

(b) add `parse_target` immediately after the `now_utc` function:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_target_range.py -v`
Expected: 5 passed

- [ ] **Step 5: Wire the scanner CLI/window.** In `main()`: change the `--target` argument to

```python
    parser.add_argument("--target", default=f"{TARGET_MIN}..{TARGET_MAX}",
                        help="odd range 'min..max' (or a single value)")
```

Replace `lo, hi = args.target - args.tolerance, args.target + args.tolerance` with:

```python
    tmin, tmax = parse_target(args.target)
    lo, hi = tmin - args.tolerance, tmax + args.tolerance
```

In the `write_meta(...)` dict, replace the `"target_odd": args.target,` line with:

```python
        "target_range": f"{tmin:g}..{tmax:g}",
```

- [ ] **Step 6: Regression + live smoke**

Run: `py -m pytest tests/ -v` → Expected: all pass (previous 7 + new 5 = 12).
Run: `py eljam3ia_odds_scanner.py --scope top --hours 0 --league "Liga Profesional"`
Expected: runs; the meta file shows `target_range,1.3..1.45` and `accept_window,1.25 .. 1.5`; matrix cells include odds down to ~1.25 and up to ~1.50.

- [ ] **Step 7: Commit**

```bash
git add eljam3ia_odds_scanner.py tests/test_target_range.py
git commit -m "feat: scanner target becomes range 1.30-1.45 (window 1.25-1.50)"
```

---

### Task 2: Pooled selection collection + slip builder (pure functions)

**Files:**
- Modify: `make_betslips.py` (add two functions; leave `main()` for Task 3)
- Test: `tests/test_build_slips.py`

**Interfaces:**
- Consumes: `clean` (existing import).
- Produces:
  - `collect_selections(details: dict, lo: float, hi: float) -> list[dict]` — every qualifying odd (price in `[lo, hi]`, `oddStatus == 0`), deduped by odd id; each item `{"odd": <odd dict>, "market": <market dict>, "price": float, "label": str, "market_name": str}`.
  - `build_slips(pools: dict[str, list[dict]], size: int, max_slips: int) -> list[list[dict]]` — greedily forms slips; each slip has DISTINCT keys (matches); each pool item used at most once overall; ≤ `max_slips` slips; each slip ≤ `size` legs; stops when < 2 keys still have items; at most one trailing slip may have < `size` legs. Task 3 relies on both names/shapes.

- [ ] **Step 1: Write the failing tests** — create `tests/test_build_slips.py`:

```python
from make_betslips import build_slips, collect_selections


def sel(match, n):
    return {"match": match, "odd": {"id": n}}


def pools():
    return {
        "m1": [sel("m1", 1), sel("m1", 2), sel("m1", 3)],
        "m2": [sel("m2", 4), sel("m2", 5)],
        "m3": [sel("m3", 6)],
    }


def test_slips_have_distinct_matches_within_each():
    slips = build_slips(pools(), size=2, max_slips=10)
    for slip in slips:
        keys = [s["match"] for s in slip]
        assert len(keys) == len(set(keys))


def test_no_odd_id_reused_across_all_slips():
    slips = build_slips(pools(), size=2, max_slips=10)
    ids = [s["odd"]["id"] for slip in slips for s in slip]
    assert len(ids) == len(set(ids))


def test_respects_max_slips():
    assert len(build_slips(pools(), size=2, max_slips=1)) == 1


def test_leg_count_never_exceeds_size():
    for slip in build_slips(pools(), size=2, max_slips=10):
        assert len(slip) <= 2


def test_collect_selections_dedupes_and_filters():
    details = {
        "odds": [
            {"id": 1, "price": 1.40, "oddStatus": 0, "name": "A"},
            {"id": 2, "price": 1.90, "oddStatus": 0, "name": "B"},
            {"id": 3, "price": 1.30, "oddStatus": 1, "name": "C"},
        ],
        "markets": [
            {"name": "Total", "typeId": 18, "sportMarketId": 70, "id": 100,
             "desktopOddIds": [[1], [2], [3]]},
            {"name": "Total", "typeId": 18, "sportMarketId": 70, "id": 100,
             "desktopOddIds": [[1]]},  # duplicate ref of odd 1
        ],
        "childMarkets": [],
    }
    out = collect_selections(details, 1.25, 1.50)
    assert [s["odd"]["id"] for s in out] == [1]  # only 1.40 active, deduped; 1.90 out of band, 1.30 suspended
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/test_build_slips.py -v`
Expected: ImportError — `cannot import name 'build_slips'`

- [ ] **Step 3: Implement** — add to `make_betslips.py` directly below the existing `pick_selection` function:

```python
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


def build_slips(pools: dict[str, list[dict]], size: int, max_slips: int) -> list[list[dict]]:
    """Greedily form slips of distinct matches, consuming one selection per match per slip.

    A match repeats across slips only by spending a not-yet-used selection (odd). Most-remaining
    match first spreads usage so more full slips are possible.
    """
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
```

Add `from eljam3ia_odds_scanner import ... EPS ...` — confirm `EPS` is already imported (it is, in the existing import block). If not, add it.

- [ ] **Step 4: Run to verify they pass**

Run: `py -m pytest tests/ -v`
Expected: all pass (12 + 5 = 17).

- [ ] **Step 5: Commit**

```bash
git add make_betslips.py tests/test_build_slips.py
git commit -m "feat: pooled qualifying-selection collection and greedy slip builder"
```

---

### Task 3: Rewrite betslip `main()` for 20-leg reusable slips

**Files:**
- Modify: `make_betslips.py` (import line; module constants; `main()`)

**Interfaces:**
- Consumes: Task 1 `TARGET_MIN`/`TARGET_MAX`/`parse_target`; Task 2 `collect_selections`/`build_slips`; existing `enrich_odds`, `reserve`, `filter_events_by_window`, `get_all_football_events`, `get_events`, `resolve_leagues`, `fetch`, `clean`.
- Produces: CLI `--target` (range str), `--size` (default 20), `--slips` (default 50). Task 5 forwards `--slips`.

- [ ] **Step 1: Update imports + constants.** Replace the `from eljam3ia_odds_scanner import (...)` block with:

```python
from eljam3ia_odds_scanner import (
    API_BASE, DATE_FILTER_HOURS, DELAY_S, EPS, HEADERS, SPORT_ID, TARGET_MAX, TARGET_MIN,
    TOLERANCE, TOP_LEAGUES, clean, fetch, filter_events_by_window, get_all_football_events,
    get_events, now_utc, parse_target, resolve_leagues,
)
```

Replace `GROUP_SIZE = 10` with:

```python
GROUP_SIZE = 20   # legs per betslip
MAX_SLIPS = 50    # max betslips per run
```

- [ ] **Step 2: Replace the argparse block** in `main()` (the `--league`/`--size`/`--target`/`--tolerance`/`--out`/`--hours`/`--scope` set) with:

```python
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
```

- [ ] **Step 3: Replace the pick/collect loop.** Replace the whole event-collection block (from `if args.league or args.scope == "top":` down through the `print(f"{league_name}: {usable} events with a ~{args.target:g} selection")` line) with a version that builds POOLS of all qualifying selections keyed by a unique match label:

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

        pools: dict[str, list[dict]] = {}
        meta_by_key: dict[str, dict] = {}
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
                    meta_by_key[key] = {"league": league_name,
                                        "match": clean(event.get("name")) or "?"}
                    usable += 1
                time.sleep(DELAY_S + random.uniform(0, 0.3))
            print(f"{league_name}: {usable} events with qualifying selections")

        slips = build_slips(pools, args.size, args.slips)
        used = [s for slip in slips for s in slip]
        enrich_odds(client, used)  # enrich only the odds actually used
```

- [ ] **Step 4: Replace the slip-output loop.** Replace the `groups = [...]` line and the `for gi, group in enumerate(groups, 1):` loop with one that iterates `slips` (already built) and reserves each:

```python
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
```

Delete the now-dead `pick_selection` function (superseded by `collect_selections`).

- [ ] **Step 5: Run tests + short live smoke** (small scope so it's quick)

Run: `py -m pytest tests/ -q` → Expected: all pass.
Run: `py make_betslips.py --scope top --hours 0 --league "Liga Profesional" --size 10 --slips 5`
Expected: prints up to 5 slips; Liga Profesional (~15 matches, each many qualifying selections in the wide window) yields multiple 10-leg slips that **reuse matches with different selections**; each ends `>> BOOKING CODE: <code>`. Confirm across two slips the same match appears with a *different* `@ odd`.

- [ ] **Step 6: Commit**

```bash
git add make_betslips.py
git commit -m "feat: 20-leg betslips reuse matches across slips with distinct odds (up to 50)"
```

---

### Task 4: Live verification — 20-leg reserve loads in the UI

**Files:** none (verification only; may set a documented `--size` cap if the site rejects 20 legs)

**Interfaces:** none.

- [ ] **Step 1: Confirm the betslip service accepts a 20-leg combo.** Build one 20-leg slip live and reserve it:

```bash
py make_betslips.py --size 20 --slips 1 --hours 23
```

Expected: one `BETSLIP 1 (20 legs, ...)` block ending `>> BOOKING CODE: <code>` (not `reserve failed`).

- [ ] **Step 2: Round-trip the code + assert full selection shape.** Replace `<CODE>`:

```bash
py -c "import httpx,json; qs='culture=en-GB&timezoneOffset=-60&integration=eljam3ia&deviceType=1&numFormat=en-GB&countryCode=TN'; r=httpx.get('https://sb2betslip-altenar2.biahosted.com/api/Betslip/FindReservedBet?'+qs+'&key=<CODE>',timeout=30).json(); bs=json.loads(r['Result']['Betslip']); ss=bs['selections']; print('legs',len(ss),'full',all(s.get('market',{}).get('sportMarketId') and s.get('sport') and s.get('championship') and s['odd'].get('intSelectionId') is not None for s in ss))"
```

Expected: `legs 20 full True`.

- [ ] **Step 3: Load it in the live UI.** In the eljam3ia betting page: clear a stale betslip if present (DevTools → Application → Local Storage → remove `WSDK_eljam3ia_betSelections`, refresh), then BETSLIP panel → **Enter Booking Code** → type the code. Expected: 20 legs render as a **Multiple** with no "Oops! This section didn't load" crash; total odds ≈ product of the legs.
  - **Contingency:** if the site rejects the combo or truncates it (max-selections cap `C`), record `C` and set the default `GROUP_SIZE = C` in `make_betslips.py`; note the cap in the plan and README. No other logic changes.

- [ ] **Step 4: Commit** (only if the contingency changed code; otherwise skip)

```bash
git add make_betslips.py
git commit -m "fix: cap betslip legs to site maximum"
```

---

### Task 5: Pipeline forwarding, docs, Browser-flow update, end-to-end

**Files:**
- Modify: `run_all.py` (argparse + forward loop), `README.md`, `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`

**Interfaces:** Consumes `--slips`/`--size`/`--target` names from Tasks 1 & 3.

- [ ] **Step 1: Forward flags in `run_all.py`.** In its argparse block change `--target` to a string passthrough and add `--slips`:

```python
    parser.add_argument("--target", default=None, help="odd range 'min..max' (forwarded)")
    parser.add_argument("--slips", type=int, default=None, help="max betslips (forwarded)")
```

and extend the forward loop tuple to include `slips`:

```python
    for flag in ("target", "tolerance", "hours", "scope", "slips"):
        if getattr(args, flag) is not None:
            forward += [f"--{flag}", str(getattr(args, flag))]
```

(`--target` as a string flows to both scripts, which both parse ranges.)

- [ ] **Step 2: Update `README.md`.** In the parameters/usage text set: "Qualifying window is **[1.25, 1.50]** (target range `1.30..1.45` ± `0.05`). Betslips are **20-leg accumulators, up to 50 per run**; a match may recur across slips, each time with a **different odd**." Add example:

```
py run_all.py --target 1.3..1.45 --size 20 --slips 50   # defaults, shown explicitly
py run_all.py --target 1.4 --size 10 --slips 7          # old-style single target, 10-leg
```

- [ ] **Step 3: Update the as-built spec** `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`:
  - Parameters: `TARGET_ODD` → `TARGET range 1.30..1.45 (--target)`; `TOLERANCE 0.05 → window [1.25, 1.50]`; betslips `--size 20`, `--slips 50`, cross-slip match reuse with distinct odds.
  - **Browser execution flow (Claude in Chrome):** rewrite to the current reality:
    1. Left menu → **TODAY → Football**; check all league boxes (site-wide today slate).
    2. Date tab = **Today (next 23 h)**; view = Match odds.
    3. For each event, open it, read every market; keep selections with odds in **[1.25, 1.50]**.
    4. Build 20-leg accumulators; reuse a match in later slips only with a different selection; Book each slip → Booking Code.

- [ ] **Step 4: Full pipeline test**

Run: `py run_all.py`
Expected: Step 1 `All football (next 23h): ...`; Step 2 builds up to 50 twenty-leg slips; `summary.txt` in the new `output/run_*/` lists matrix stats and every booking code.

- [ ] **Step 5: Scheduled-task end-to-end + one live load**

Run: `schtasks /Run /TN "Eljam3ia Odds Pipeline"`, poll for the new `output/run_*/summary.txt`.
Expected: today-window scope, 20-leg slips, task ends `Ready` / `LastTaskResult 0`. Load one fresh code on the live site (BETSLIP panel → Enter Booking Code) — 20 legs render, no crash.

- [ ] **Step 6: Commit**

```bash
git add run_all.py README.md
git commit -m "feat: pipeline forwards --slips and range --target; docs + browser flow updated"
```

---

## Self-Review

**Spec coverage:** target range 1.30–1.45 / window [1.25,1.50] → Task 1. 20-leg slips → Task 3 (`--size 20`). Up to 50 slips, pool-limited → Task 3 (`--slips 50`, `build_slips`). Match reuse across slips with different odd → Tasks 2–3 (`collect_selections` pools + consume-from-pool). Booking code per slip → Task 3 `reserve`. Browser-flow update → Task 5 Step 3. Pipeline/scheduler inherit → Task 5.

**Placeholder scan:** none — every code step shows complete code; `<CODE>` in Task 4 is an explicit runtime substitution, not a plan gap.

**Type consistency:** `collect_selections` returns items with keys `odd/market/price/label/market_name`; `build_slips` consumes those same dicts and the output loop reads `price/league/match/market_name/label` (all present after the `.update()` in Task 3 Step 3). `parse_target` returns `(min, max)` used identically in scanner (Task 1) and betslips (Task 3). `reserve`/`enrich_odds`/`build_selection` shapes are unchanged from the working build, so the full-selection contract holds.
