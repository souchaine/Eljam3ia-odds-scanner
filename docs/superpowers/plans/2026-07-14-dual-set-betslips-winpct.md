# Dual-Set Betslips + Win% Implementation Plan (Sub-project 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each betslip run produce two labelled sets of 20-leg booking codes — **SET A** (up to 50 all-odds slips) and **SET B** (up to 25 slips diversified across the 7 market families) — with a de-vigged **win%** printed on every slip, wired into the daily pipeline.

**Architecture:** Add a pure `novig_prob` (per-selection no-vig probability) computed at collection time and a pure `slip_win_pct` (product of legs). Add a pure `build_diversified_slips()` (family round-robin greedy) alongside the existing `build_slips()`. Rework `make_betslips.main()` to build both sets, annotate each slip with win%, and write two labelled sections; `run_all.py summarize()` reports both. Mixed/`--per-category` behaviour is superseded by the default "both sets" output but a `--set` switch preserves single-set runs.

**Tech Stack:** Python 3.11, `httpx` (runtime), `pytest` (dev). Windows `py` launcher. Existing Altenar API + existing `collect_selections`/`build_slips`/`enrich_odds`/`reserve`/`market_category`/`CATEGORY_ORDER`.

## Global Constraints

- Odds window unchanged: `[1.25, 1.50]` (target range 1.30..1.45 ± 0.05).
- Both sets are **20-leg** (`--size 20`). SET A ≤ **50** slips (`--slips-a`, default `MAX_SLIPS=50`); SET B ≤ **25** slips (`--slips-b`, default `SLIPS_B=25`).
- SET B diversification is **soft**: family round-robin over `CATEGORY_ORDER`; take one unused selection per family per turn from a match not already in the slip (prefer most-remaining match); skip families with no stock; fill to 20 legs from whatever families remain. Invariants (shared with `build_slips`): a match is unique **within** a slip; each odd-id used at most once **across the set**; at most one trailing partial.
- Win%: `p_novig(sel) = (1/price_sel) / Σ_market_outcomes (1/price_o)` over the selection's own market's active outcomes; `slip_win_pct = 100 * Π legs p_novig`. Guard divide-by-zero: a selection with no valid market sum falls back to `1/price_sel`. Win% always renders.
- Selections keep the FULL widget shape (unchanged `build_selection`/`enrich_odds`/`reserve`). `enrich_odds` runs on used odds only. Names via `clean()`. No new runtime dependencies.
- `run_all.py` (and the 09:00 scheduled task) produce both sets by default. `summarize()` must list every `BETSLIP \S+` code across both sets (regex already `^(BETSLIP \S+.*)$`).
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`; run from there with the `py` launcher. Branch: continue on `feature/per-category-betslips`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `make_betslips.py` | Betslip builder | Add `novig_prob` field in `collect_selections`; add `slip_win_pct`, `build_diversified_slips`, `SLIPS_B`; rework `main()` for two sets + win% + `--set`/`--slips-a`/`--slips-b` |
| `run_all.py` | Pipeline | Forward `--set`/`--slips-a`/`--slips-b` (optional); summarize already handles `BETSLIP \S+` |
| `tests/test_winpct.py` | New: `novig_prob` + `slip_win_pct` | Create |
| `tests/test_diversified.py` | New: `build_diversified_slips` | Create |
| `README.md`, `~/.claude/plans/prompt-eljam3ia-odds-cheerful-owl.md` | Docs | Document dual-set output + win% |

---

### Task 1: Win-probability primitives (`novig_prob`, `slip_win_pct`)

**Files:**
- Modify: `make_betslips.py` (add two pure functions below `market_category`; extend `collect_selections` to attach `novig_prob`)
- Test: `tests/test_winpct.py`

**Interfaces:**
- Produces:
  - `novig_prob(price: float, market_prices: list[float]) -> float` — no-vig probability of one outcome given all active outcome prices of its market; if `market_prices` empty/invalid, returns `1/price`.
  - `slip_win_pct(slip: list[dict]) -> float` — `100 * Π p["novig_prob"]` over a slip's legs.
  - `collect_selections(...)` items gain key `"novig_prob": float`. Tasks 2–3 read `s["novig_prob"]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_winpct.py`:

```python
import math

from make_betslips import novig_prob, slip_win_pct


def test_novig_two_way_even_market():
    # 1.90 / 1.90 -> implied 0.5263 each, sum 1.0526, no-vig 0.5 each
    assert abs(novig_prob(1.90, [1.90, 1.90]) - 0.5) < 1e-9


def test_novig_normalizes_over_all_outcomes():
    # market 2.0 / 4.0 / 4.0 -> implied 0.5/0.25/0.25 = 1.0 (no vig) -> 0.5 for the 2.0 pick
    assert abs(novig_prob(2.0, [2.0, 4.0, 4.0]) - 0.5) < 1e-9


def test_novig_empty_market_falls_back_to_raw():
    assert abs(novig_prob(1.25, []) - 0.8) < 1e-9


def test_novig_skips_zero_prices():
    assert abs(novig_prob(2.0, [2.0, 2.0, 0.0]) - 0.5) < 1e-9


def test_slip_win_pct_is_product_times_100():
    slip = [{"novig_prob": 0.5}, {"novig_prob": 0.5}]
    assert abs(slip_win_pct(slip) - 25.0) < 1e-9


def test_slip_win_pct_empty_slip_is_zero():
    assert slip_win_pct([]) == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_winpct.py -v`
Expected: ImportError — `cannot import name 'novig_prob'`

- [ ] **Step 3: Implement** — add below `market_category` in `make_betslips.py`:

```python
def novig_prob(price: float, market_prices: list[float]) -> float:
    """No-vig implied probability of one outcome, normalized over its market's active outcomes."""
    try:
        raw = 1.0 / float(price)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    total = sum(1.0 / p for p in market_prices if p)
    return raw / total if total > 0 else raw


def slip_win_pct(slip: list[dict]) -> float:
    """Model win probability of a slip as a percent: 100 * product of legs' no-vig probs."""
    if not slip:
        return 0.0
    prob = 1.0
    for s in slip:
        prob *= s.get("novig_prob", 0.0)
    return 100.0 * prob
```

Then extend `collect_selections`: when a qualifying odd is appended, compute the market's active
outcome prices and attach `novig_prob`. Change the append block so it reads:

```python
                if lo - EPS <= price <= hi + EPS:
                    seen.add(odd_id)
                    market_prices = [
                        odds_by_id[i]["price"]
                        for grp in (market.get("desktopOddIds") or market.get("mobileOddIds") or [])
                        for i in (grp if isinstance(grp, list) else [grp])
                        if i in odds_by_id and odds_by_id[i].get("oddStatus", 0) == 0
                    ]
                    out.append({"odd": odd, "market": market, "price": price,
                                "label": clean(odd.get("name")) or "?", "market_name": name,
                                "novig_prob": novig_prob(price, market_prices)})
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_winpct.py -v`
Expected: 6 passed

- [ ] **Step 5: Full suite regression**

Run: `py -m pytest tests/ -q`
Expected: previously-passing tests still pass, + 6 new.

- [ ] **Step 6: Commit**

```bash
git add make_betslips.py tests/test_winpct.py
git commit -m "feat: de-vigged win-probability primitives + novig_prob on selections"
```

---

### Task 2: Diversified slip builder (`build_diversified_slips`)

**Files:**
- Modify: `make_betslips.py` (add function below `build_slips`; add `SLIPS_B` constant near `MAX_SLIPS`)
- Test: `tests/test_diversified.py`

**Interfaces:**
- Consumes: `market_category`, `CATEGORY_ORDER` (existing).
- Produces:
  - `SLIPS_B = 25` (module constant).
  - `build_diversified_slips(pools: dict[str, list[dict]], size: int, max_slips: int) -> list[list[dict]]`
    — greedy family round-robin; each returned slip has distinct match keys; each pool item used at
    most once overall; ≤ `max_slips` slips; each slip ≤ `size` legs; stops when < 2 matches retain
    stock; at most one trailing partial. Each selection dict must expose `market_name` (used to
    classify via `market_category`). Task 3 consumes the returned slips.

- [ ] **Step 1: Write the failing tests** — create `tests/test_diversified.py`:

```python
from make_betslips import build_diversified_slips


def sel(match, oddid, market_name):
    return {"match": match, "market_name": market_name, "odd": {"id": oddid}}


def pools():
    # 6 matches; two families present: "corners" and "main"
    return {
        "m1": [sel("m1", 1, "Total corners"), sel("m1", 2, "1x2")],
        "m2": [sel("m2", 3, "Corner 1x2"), sel("m2", 4, "Total")],
        "m3": [sel("m3", 5, "Handicap")],
        "m4": [sel("m4", 6, "Total corners")],
        "m5": [sel("m5", 7, "1x2")],
        "m6": [sel("m6", 8, "Corner 1x2")],
    }


def test_distinct_matches_within_each_slip():
    for slip in build_diversified_slips(pools(), size=4, max_slips=10):
        keys = [s["match"] for s in slip]
        assert len(keys) == len(set(keys))


def test_no_odd_id_reused_across_slips():
    slips = build_diversified_slips(pools(), size=4, max_slips=10)
    ids = [s["odd"]["id"] for slip in slips for s in slip]
    assert len(ids) == len(set(ids))


def test_first_slip_spans_both_families_when_possible():
    from make_betslips import market_category
    slip = build_diversified_slips(pools(), size=4, max_slips=10)[0]
    fams = {market_category(s["market_name"]) for s in slip}
    assert "corners" in fams and "main" in fams


def test_respects_max_and_size():
    slips = build_diversified_slips(pools(), size=4, max_slips=1)
    assert len(slips) == 1
    assert len(slips[0]) <= 4
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_diversified.py -v`
Expected: ImportError — `cannot import name 'build_diversified_slips'`

- [ ] **Step 3: Implement** — add `SLIPS_B = 25` near `MAX_SLIPS`, and add below `build_slips`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_diversified.py -v`
Expected: 4 passed

- [ ] **Step 5: Full suite regression**

Run: `py -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add make_betslips.py tests/test_diversified.py
git commit -m "feat: diversified 7-family slip builder (soft round-robin)"
```

---

### Task 3: Two-set output + win% in `make_betslips.main()`

**Files:**
- Modify: `make_betslips.py` — `main()` (argparse, build both sets, grouped output with win%)

**Interfaces:**
- Consumes: Task 1 `slip_win_pct`; Task 2 `build_diversified_slips`, `SLIPS_B`; existing `build_slips`, `enrich_odds`, `reserve`.
- Produces: CLI `--set {both,a,b}` (default `both`), `--slips-a` (default `MAX_SLIPS`), `--slips-b` (default `SLIPS_B`). Output sections `SET A` / `SET B`, slip labels `A1..`, `B1..`, each line ending `>> BOOKING CODE: <code>` and header carrying `win% <x>`.

- [ ] **Step 1: Replace the argparse `--slips`/`--per-category` block** in `main()` with:

```python
    parser.add_argument("--set", choices=["both", "a", "b"], default="both",
                        help="which set(s) to build: a=all-odds, b=7-category diversified")
    parser.add_argument("--slips-a", type=int, default=MAX_SLIPS, help="max SET A slips (default 50)")
    parser.add_argument("--slips-b", type=int, default=SLIPS_B, help="max SET B slips (default 25)")
    parser.add_argument("--per-category", action="store_true",
                        help="(legacy) build category-pure slips instead of the two sets")
```

Keep `--size`, `--target`, `--tolerance`, `--hours`, `--scope`, `--out`, `--league`.
Keep the existing `--per-category` legacy branch working (leave its code path intact for back-compat;
the new default is the two-set build). Compute after `tmin,tmax`/`lo,hi`:

```python
    lo, hi = tmin - args.tolerance, tmax + args.tolerance
```

- [ ] **Step 2: Replace the slip-building block.** After `pools` is collected and `enrich`-ready, build
an ordered `groups: list[tuple[str, list[dict]]]` (label carries set+index) for the default two-set
mode. Replace the current single/`--per-category` slip build with:

```python
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
```

- [ ] **Step 3: Rewrite the output loop** to print a section header when the set changes and a win% per
slip. Replace the current output loop with:

```python
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
```

(Confirm the tags/`collect` loop above still tag each selection with `league`/`match`/`sport`/
`category`/`championship`/`competitors` as today — unchanged.)

- [ ] **Step 4: Unit regression + live smoke**

Run: `py -m pytest tests/ -q` → all pass.
Run: `py make_betslips.py --scope top --hours 0 --league "Liga Profesional" --slips-a 2 --slips-b 2 --size 8`
Expected: `===== SET A: all-odds =====` with up to 2 slips, `===== SET B: 7-category diversified =====`
with up to 2 slips; each `BETSLIP A1/A2/B1/B2` header shows `win% <x>`; each ends `>> BOOKING CODE`.
SET B slips visibly mix families (different `market` names across families). Confirm `--set a` builds
only SET A and `--per-category` still groups by family.

- [ ] **Step 5: Commit**

```bash
git add make_betslips.py
git commit -m "feat: dual-set betslip output (SET A 50 all-odds + SET B 25 diversified) with win%"
```

---

### Task 4: Pipeline default, docs, live E2E

**Files:**
- Modify: `run_all.py` (forward `--set`/`--slips-a`/`--slips-b`), `README.md`, `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`

**Interfaces:** Consumes Task 3 CLI flags. Default `run_all.py` (no flags) must yield both sets.

- [ ] **Step 1: Forward optional flags in `run_all.py`.** Add argparse entries and append to `slip_args`
(betslip step only), mirroring `--size`:

```python
    parser.add_argument("--set", choices=["both", "a", "b"], default=None, help="set(s) to build (forwarded)")
    parser.add_argument("--slips-a", type=int, default=None, help="max SET A slips (forwarded)")
    parser.add_argument("--slips-b", type=int, default=None, help="max SET B slips (forwarded)")
```

Inside `if not args.skip_betslips:`, after the `--size` append:

```python
        for f, v in (("--set", args.set), ("--slips-a", args.slips_a), ("--slips-b", args.slips_b)):
            if v is not None:
                slip_args += [f, str(v)]
```

(Default run passes none → `make_betslips.py` uses its own defaults = both sets, 50 + 25.)

- [ ] **Step 2: Confirm `summarize()` lists both sets.** No code change expected — the regex is
`r"^(BETSLIP \S+.*)$"`, which matches `BETSLIP A1 ...` and `BETSLIP B1 ...`. Verify with a unit test —
append to `tests/test_run_all_summarize.py`:

```python
def test_summarize_lists_dual_set_codes(tmp_path):
    (tmp_path / "betslips_20260101_0000.txt").write_text(
        "h\n\n===== SET A: all-odds =====\n"
        "BETSLIP A1  (20 legs, combined odds x800.00, win% 0.02)\n  >> BOOKING CODE: AA111\n\n"
        "===== SET B: 7-category diversified =====\n"
        "BETSLIP B1  (20 legs, combined odds x700.00, win% 0.03)\n  >> BOOKING CODE: BB222\n\n",
        encoding="utf-8")
    import run_all
    out = run_all.summarize(tmp_path)
    assert "AA111" in out and "BB222" in out
```

Run: `py -m pytest tests/test_run_all_summarize.py -q` → passes (RED only if regex regressed).

- [ ] **Step 3: Update docs.** In `README.md` add under the betslips section: "Each run builds **two
sets**: SET A = up to 50 all-odds 20-leg slips; SET B = up to 25 slips diversified across the 7 market
families. Every slip shows a de-vigged **win%** (model probability; for 20-leg accumulators this is
inherently tiny). Restrict with `--set a|b`; sizes via `--slips-a`/`--slips-b`." Update the as-built
spec `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md` betslip bullet accordingly, and
add a note that win% uses proportional de-vig (`novig_prob`).

- [ ] **Step 4: Full pipeline E2E.**

Run: `py run_all.py --slips-a 3 --slips-b 3 --hours 0 --scope top`
Expected: Step 1 scan; Step 2 builds SET A (≤3) + SET B (≤3); `summary.txt` lists all codes across
both sets. Round-trip one SET B code and assert 20 (or partial) full-shape legs; load it in the live
UI (BETSLIP panel → Enter Booking Code, clearing stale `WSDK_eljam3ia_betSelections`) — renders as a
Multiple, no crash.

- [ ] **Step 5: Commit**

```bash
git add run_all.py README.md tests/test_run_all_summarize.py
git commit -m "feat: pipeline builds both sets by default; docs + summarize test for dual-set"
```

---

## Self-Review

**Spec coverage:** SET A (50 all-odds) → Task 3 (`build_slips`, `--slips-a`). SET B (25 diversified,
soft) → Task 2 (`build_diversified_slips`) + Task 3. Win% de-vig → Task 1 (`novig_prob`/`slip_win_pct`)
+ Task 3 output. Two labelled sections + win% per slip → Task 3 Step 3. Daily task both-sets default →
Task 4. Out of scope (settlement/trackers) → not planned here, per spec. Covered.

**Placeholder scan:** none — every code step is complete; `<code>`/`<x>` in run output are runtime
values, not gaps.

**Type consistency:** `novig_prob(price, market_prices)->float` and `slip_win_pct(slip)->float`
(Task 1) are consumed unchanged in Task 3; selections carry `novig_prob` (Task 1) read by
`slip_win_pct`. `build_diversified_slips(pools,size,max_slips)->list[list[dict]]` (Task 2) returns the
same slip shape `build_slips` does, consumed identically in Task 3's `groups`. `SLIPS_B=25`,
`--slips-a`/`--slips-b`/`--set` names match between Tasks 3 and 4. Slip dicts carry `price`,
`market_name`, `league`, `match`, `novig_prob` — all set by `collect_selections`/the tagging loop.
