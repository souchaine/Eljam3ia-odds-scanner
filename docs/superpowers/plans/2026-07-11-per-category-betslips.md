# Per-Category Betslips (7 Market Families) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--per-category` mode to the betslip builder that classifies each qualifying selection into one of **7 market families** (main, combo DC, 1st half, 2nd half, corners, carte, multigoals) and produces **category-pure** 20-leg accumulators — **up to 25 booking codes per category** (as many as each family's pool supports), grouped in the output.

**Architecture:** One new pure classifier `market_category(name)` maps a market name to exactly one family (specific stat types win over period/generic). In per-category mode, `make_betslips.main()` builds a separate selection pool per family, runs the existing `build_slips()` on each pool (default 25 slips/family), enriches only the used odds, reserves each slip, and writes the betslips file grouped by category. The default mixed mode is unchanged.

**Tech Stack:** Python 3.11, `httpx` (runtime), `pytest` (dev). Windows, `py` launcher. Existing Altenar API and the existing `collect_selections` / `build_slips` / `enrich_odds` / `reserve` helpers.

## Global Constraints

- 7 categories, classified from the (cleaned) market name, in this precedence (first match wins): **corners** (`corner`), **carte** (`booking` or `card`), **multigoals** (`multigoal`), **1st half** (`1st half` / `first half`), **2nd half** (`2nd half` / `second half`), **combo DC** (`double chance` or `dc ` / `/dc` / halftime-fulltime DC), else **main**. Stat-type families (corners/carte/multigoals) intentionally win over period families so a "1st half - total corners" market is `corners`, not `1st half`.
- Per-category default = **25 slips per category** (`--slips` overrides; mixed mode default stays 50). Legs per slip default 20 (`--size`); build as many full slips as each pool supports (thin families produce fewer). At most one trailing partial per category.
- All existing invariants hold **within each category**: a match is unique within a slip; across a category's slips each of that match's qualifying odd ids is used at most once; every leg's odd in [1.25, 1.50].
- Selections keep the FULL widget shape (unchanged `build_selection`/`enrich_odds`/`reserve`). Names via `clean()`. No new runtime dependencies.
- Mixed mode (no `--per-category`) behaves exactly as today. Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`; run from there.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `make_betslips.py` | Betslip builder | Add `market_category()`; `--per-category` + `--slips` default handling; per-category pool build + grouped output in `main()` |
| `run_all.py` | Pipeline | Forward `--per-category` |
| `tests/test_market_category.py` | New: classifier unit tests | Create |
| `README.md`, `~/.claude/plans/prompt-eljam3ia-odds-cheerful-owl.md` | Docs | Document the mode |

---

### Task 1: `market_category()` classifier

**Files:**
- Modify: `make_betslips.py` (add function directly below `collect_selections`)
- Test: `tests/test_market_category.py`

**Interfaces:**
- Consumes: nothing (pure string function).
- Produces: `market_category(name: str) -> str` returning one of exactly `"corners"`, `"carte"`, `"multigoals"`, `"1st half"`, `"2nd half"`, `"combo DC"`, `"main"`. Task 2 imports/uses it and iterates the family order via `CATEGORY_ORDER`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_market_category.py`:

```python
from make_betslips import market_category, CATEGORY_ORDER


def test_corners_wins_over_first_half():
    assert market_category("1st half - total corners") == "corners"


def test_carte_matches_bookings_and_cards():
    assert market_category("Total bookings") == "carte"
    assert market_category("Both teams 3+ bookings each") == "carte"


def test_multigoals():
    assert market_category("1st half - multigoals") == "multigoals"


def test_first_and_second_half():
    assert market_category("1st half - total") == "1st half"
    assert market_category("2nd half - double chance") == "2nd half"


def test_combo_dc():
    assert market_category("Double chance & total 2.5") == "combo DC"
    assert market_category("DC Halftime/ DC Fulltime") == "combo DC"


def test_main_is_default():
    assert market_category("1x2") == "main"
    assert market_category("Correct score") == "main"


def test_category_order_has_seven_families():
    assert CATEGORY_ORDER == ["main", "combo DC", "1st half", "2nd half",
                              "corners", "carte", "multigoals"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_market_category.py -v`
Expected: ImportError — `cannot import name 'market_category'`

- [ ] **Step 3: Implement** — add to `make_betslips.py` directly below `collect_selections` (and add `CATEGORY_ORDER` near the module constants, e.g. below `MAX_SLIPS`):

Near the constants:

```python
CATEGORY_ORDER = ["main", "combo DC", "1st half", "2nd half", "corners", "carte", "multigoals"]
PER_CATEGORY_SLIPS = 25  # default slips per category in --per-category mode
```

Below `collect_selections`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_market_category.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add make_betslips.py tests/test_market_category.py
git commit -m "feat: market_category classifier for 7 betslip families"
```

---

### Task 2: `--per-category` mode in `make_betslips.main()`

**Files:**
- Modify: `make_betslips.py` — import/constants already added in Task 1; `main()` argparse + pool build + output

**Interfaces:**
- Consumes: Task 1 `market_category`, `CATEGORY_ORDER`, `PER_CATEGORY_SLIPS`; existing `collect_selections`, `build_slips`, `enrich_odds`, `reserve`.
- Produces: CLI `--per-category` (store_true) and a `--slips` whose effective default is 25 in per-category mode, 50 otherwise. Task 3 forwards `--per-category`.

- [ ] **Step 1: Change the `--slips` arg to a None sentinel** so the mode can pick the default. In `main()`'s argparse, replace the current `--slips` line with:

```python
    parser.add_argument("--slips", type=int, default=None,
                        help="max betslips per run (mixed) or per category (--per-category)")
    parser.add_argument("--per-category", action="store_true",
                        help="build category-pure slips (main/combo DC/1st half/2nd half/corners/carte/multigoals)")
```

Directly after `tmin, tmax = parse_target(args.target)` / `lo, hi = ...`, add:

```python
    default_slips = PER_CATEGORY_SLIPS if args.per_category else MAX_SLIPS
    max_slips = args.slips if args.slips is not None else default_slips
```

- [ ] **Step 2: Branch the slip building.** The current code (after `picks`/`pools` are collected and `slips = build_slips(pools, args.size, args.slips)`) assumes a single pool. Replace the single `slips = build_slips(pools, args.size, args.slips)` line and the `if not slips: ... return 1` guard with a structure that yields an ordered list of `(label, slip)` pairs for BOTH modes:

```python
        if args.per_category:
            groups: list[tuple[str, list[dict]]] = []
            for cat in CATEGORY_ORDER:
                cat_pools = {
                    key: [s for s in sels if market_category(s["market_name"]) == cat]
                    for key, sels in pools.items()
                }
                cat_pools = {k: v for k, v in cat_pools.items() if v}
                for i, slip in enumerate(build_slips(cat_pools, args.size, max_slips), 1):
                    groups.append((f"{cat} #{i}", slip))
        else:
            groups = [(str(i), slip)
                      for i, slip in enumerate(build_slips(pools, args.size, max_slips), 1)]

        if not groups:
            print("No betslips could be built (no qualifying selections in range).")
            return 1

        used = [s for _label, slip in groups for s in slip]
        enrich_odds(client, used)
```

- [ ] **Step 3: Rewrite the output loop** to iterate `groups` and print a category header when the family changes. Replace the existing `for gi, slip in enumerate(slips, 1):` loop body with:

```python
        current_cat = None
        for gi, (label, slip) in enumerate(groups, 1):
            if args.per_category:
                cat = label.rsplit(" #", 1)[0]
                if cat != current_cat:
                    current_cat = cat
                    header_line = f"\n===== CATEGORY: {cat} ====="
                    print(header_line)
                    lines.append(header_line)
            combined = 1.0
            for s in slip:
                combined *= s["price"]
            header = (f"BETSLIP {label}  ({len(slip)} legs, combined odds x{combined:.2f})"
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
```

- [ ] **Step 4: Update the header/summary lines.** Where `lines` is initialized (the `f"window {lo:g}..{hi:g}, ..."` line), make it mode-aware:

```python
        mode = (f"per-category ({len(CATEGORY_ORDER)} families), up to {max_slips} slips/category"
                if args.per_category else
                f"{args.size} legs/slip, up to {max_slips} slips")
        lines = [f"Eljam3ia multiplier betslips - built {now_utc()}",
                 f"window {lo:g}..{hi:g}, {args.size} legs/slip, {mode}, {len(pools)} matches",
                 "Load a code on eljam3ia.com: BETSLIP panel -> Enter Booking Code (before kickoff).", ""]
```

(Confirm no other code references the old `slips` variable name after this change; the summary/print at the end already uses `txt_path` and the `lines` list.)

- [ ] **Step 5: Unit regression + fast live smoke**

Run: `py -m pytest tests/ -q` → Expected: all pass (24 → still green; this task adds no unit tests but must not break existing ones).
Run: `py make_betslips.py --per-category --scope top --hours 0 --league "Liga Profesional" --size 6 --slips 2`
Expected: output shows `===== CATEGORY: main =====`, `===== CATEGORY: combo DC =====`, ... headers, each with up to 2 slips of 6 legs, every slip ending `>> BOOKING CODE: <code>`; thin families (carte/multigoals) may show fewer or zero slips. Confirm each slip's legs are all the same family (e.g. every leg under `CATEGORY: corners` names a corner market).

- [ ] **Step 6: Commit**

```bash
git add make_betslips.py
git commit -m "feat: --per-category builds category-pure slips (up to 25 per family)"
```

---

### Task 3: Pipeline forwarding, docs, live E2E

**Files:**
- Modify: `run_all.py` (argparse + a store_true forward), `README.md`, `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`

**Interfaces:** Consumes `--per-category` from Task 2.

- [ ] **Step 1: Forward `--per-category` in `run_all.py`.** Add to its argparse:

```python
    parser.add_argument("--per-category", action="store_true",
                        help="build category-pure betslips (forwarded)")
```

After the existing string-flag forward loop, append the store_true flag only to the betslip step (like `--size`/`--slips`):

```python
        if args.per_category:
            slip_args.append("--per-category")
```

(Place inside the `if not args.skip_betslips:` block, next to the `--size`/`--slips` appends. `--per-category` must NOT go to the scanner.)

- [ ] **Step 2: Update `README.md`.** In the Automatic-mode / betslips section add:

```
py run_all.py --per-category            # 7 category-pure families, up to 25 slips each
py make_betslips.py --per-category      # same, betslips only
```

and one sentence: "With `--per-category`, betslips are grouped into 7 market families (main, combo DC, 1st half, 2nd half, corners, carte/cards, multigoals) — up to 25 twenty-leg slips per family, each leg from that family."

- [ ] **Step 3: Update the as-built spec** `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`: add a bullet under the betslip-builder capability noting the `--per-category` mode (7 families, up to 25 slips/family, category-pure legs), and add `market_category` precedence (corners/carte/multigoals win over period families) to the notes.

- [ ] **Step 4: Live E2E — category-pure slips reserve and load.**

Run: `py make_betslips.py --per-category --size 20 --slips 1`
Expected: for each non-empty family, one 20-leg (or partial) slip with a `>> BOOKING CODE`. Pick a code from the `corners` family and round-trip it:

```bash
py -c "import httpx,json; qs='culture=en-GB&timezoneOffset=-60&integration=eljam3ia&deviceType=1&numFormat=en-GB&countryCode=TN'; r=httpx.get('https://sb2betslip-altenar2.biahosted.com/api/Betslip/FindReservedBet?'+qs+'&key=<CORNERS_CODE>',timeout=30).json(); ss=json.loads(r['Result']['Betslip'])['selections']; print('legs',len(ss),'full',all(s.get('market',{}).get('sportMarketId') and s['odd'].get('intSelectionId') is not None for s in ss))"
```

Expected: `legs <=20 full True`. Then load that code in the live UI (BETSLIP panel → Enter Booking Code, clearing stale `WSDK_eljam3ia_betSelections` first) and confirm it renders as a Multiple with no crash.

- [ ] **Step 5: Commit**

```bash
git add run_all.py README.md
git commit -m "feat: pipeline forwards --per-category; docs for category-pure betslips"
```

---

## Self-Review

**Spec coverage:** 7 families classified → Task 1 (`market_category` + `CATEGORY_ORDER`). Per-category pools + up to 25 slips/family, 20 legs, as-many-as-pool-supports → Task 2 (`build_slips` per family, `max_slips` default 25). Grouped output with a booking code per slip → Task 2 Step 3. Mixed mode unchanged → Task 2 keeps the `else` branch identical to prior behavior. Pipeline/docs → Task 3.

**Placeholder scan:** none — every code step is complete; `<CORNERS_CODE>` in Task 3 Step 4 is a runtime substitution, not a gap.

**Type consistency:** `market_category(name)->str` and `CATEGORY_ORDER: list[str]` defined in Task 1, used identically in Task 2. `groups: list[tuple[str, list[dict]]]` is the single shape the output loop consumes in both modes. `max_slips` (int) computed once and passed to every `build_slips` call. Selections in `pools[key]` carry `market_name` (set by `collect_selections`), which `market_category` reads — consistent with the existing `collect_selections` output contract.
