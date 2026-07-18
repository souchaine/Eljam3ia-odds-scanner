# Half + Combo Score-Grading Implementation Plan (settle.py)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `settle.py`'s `grade_leg` to grade half-goal markets and `A & B` combo markets from the HT+FT score, lifting per-leg coverage from ~37% toward the high-80s%.

**Architecture:** Refactor today's 8 full-time markets into a pure `_grade_score(key, sel, home, away)` core (adding score sub-types + Double-chance notation normalization), then add two thin wrappers inside `grade_leg` — a **half** wrapper (grades `<core>` on the 1st/2nd-half score derived from `ht_*`) and a **combo** wrapper (splits `A & B` market+selection, grades each part, ANDs with precedence). The public `grade_leg` contract (returns `won|lost|void|unsettleable`, never raises) is unchanged.

**Tech Stack:** Python 3.11 stdlib only (`re`, `dataclasses`). `pytest` (dev). Windows `py` launcher. No new deps.

## Global Constraints

- Boundary: grade ONLY what's derivable from the HT+FT score. Any component that is a stat (`corner|booking|card|shot|tackle|offside|foul`) or event (first-goal scorer) → `unsettleable`.
- `grade_leg` never raises; unknown market/selection → `unsettleable`; str-coerce inputs (already done).
- Verdict strings unchanged: `won|lost|void|unsettleable` (leg). Existing FT behaviour must be identical after the refactor (the score core is behaviour-preserving for full-time).
- Combo precedence: `unsettleable` > `lost` > `void` > `won`.
- Half score: 1st half = `(ht_home, ht_away)`; 2nd half = `(home - ht_home, away - ht_away)`. If `ht_home`/`ht_away` is `None` → `unsettleable`.
- Double chance notations all normalize to the same pair: `1 or draw|1x|1/x` → {1,Draw}; `1 or 2|12|1/2` → {1,2}; `draw or 2|x2|x/2` → {Draw,2}.
- `UNSETTLEABLE` regex must keep ONLY stat/event tokens `corner|booking|card|shot|tackle|offside|foul` (drop `1st half|2nd half|halftime|half-time| & |odd/even`).
- `MatchOutcome` already has `ht_home`/`ht_away`; `read_outcomes_csv` already parses them. Do not change them.
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`; run from there with `py`. Branch: `feature/half-combo-grading`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `settle.py` | grading | Extract `_grade_score`; narrow `UNSETTLEABLE`; add half/combo dispatch in `grade_leg` |
| `tests/test_grade_leg.py` | grading tests | Add half/combo/subtype cases + FT-regression confirmation |

---

### Task 1: Extract `_grade_score` core (behaviour-preserving) + DC notation + sub-types

**Files:**
- Modify: `settle.py` (add `_grade_score`; make `grade_leg`'s FT path delegate to it)
- Test: `tests/test_grade_leg.py`

**Interfaces:**
- Produces: `_grade_score(key: str, sel: str, home: int, away: int) -> str` — grades a score-derivable market (already-lowercased `key`, raw `sel`) on the given goal pair; returns `won|lost|void|unsettleable`. Task 2 (half/combo) calls it. `grade_leg`'s existing FT dispatch now calls `_grade_score(key, sel, o.home, o.away)`.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_grade_leg.py`:

```python
from settle import _grade_score


def test_grade_score_matches_grade_leg_for_ft_markets():
    # score core on (2,1) must equal the FT grade_leg behaviour
    assert _grade_score("1x2", "1", 2, 1) == "won"
    assert _grade_score("total", "Over 2.5", 2, 1) == "won"
    assert _grade_score("total", "Over 3", 2, 1) == "void"
    assert _grade_score("correct score", "2:1", 2, 1) == "won"
    assert _grade_score("multigoals", "1-3", 2, 1) == "won"
    assert _grade_score("handicap", "2 (+1.5)", 2, 1) == "won"


def test_double_chance_all_notations():
    for sel in ("1 or draw", "1X", "1/X"):
        assert _grade_score("double chance", sel, 2, 1) == "won"   # home win covers 1X
    for sel in ("1 or 2", "12", "1/2"):
        assert _grade_score("double chance", sel, 2, 1) == "won"
    for sel in ("draw or 2", "X2", "x/2"):
        assert _grade_score("double chance", sel, 2, 1) == "lost"


def test_team_total_and_clean_sheet_and_oddeven():
    assert _grade_score("1 total", "Over 1.5", 2, 1) == "won"      # home scored 2 > 1.5
    assert _grade_score("2 total", "Under 0.5", 2, 1) == "lost"    # away scored 1
    assert _grade_score("2 clean sheet", "No", 2, 1) == "won"      # away conceded 2 -> not clean
    assert _grade_score("1 clean sheet", "Yes", 2, 0) == "won"     # away scored 0 -> home clean
    assert _grade_score("odd/even", "Odd", 2, 1) == "won"          # 3 total -> odd
    assert _grade_score("2 odd/even", "Even", 2, 2) == "won"       # away 2 -> even


def test_grade_score_unknown_is_unsettleable():
    assert _grade_score("total corners", "Over 8.5", 2, 1) == "unsettleable"
    assert _grade_score("1x2", "banana", 2, 1) == "unsettleable"
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_grade_leg.py -k "grade_score or double_chance or team_total" -v`
Expected: ImportError — `cannot import name '_grade_score'`

- [ ] **Step 3: Implement** — in `settle.py`, add `_grade_score` (moving the 8 FT market bodies into it, keyed off `key`, using the passed `home`/`away`) and the new sub-types. Then change `grade_leg`'s per-market dispatch to a single delegating line. The `_grade_score` body:

```python
_DC_PAIRS = {
    "1 or draw": {"1", "Draw"}, "1x": {"1", "Draw"}, "1/x": {"1", "Draw"},
    "1 or 2": {"1", "2"}, "12": {"1", "2"}, "1/2": {"1", "2"},
    "draw or 2": {"Draw", "2"}, "x2": {"Draw", "2"}, "x/2": {"Draw", "2"},
}


def _grade_score(key: str, sel: str, home: int, away: int) -> str:
    """Grade a score-derivable market on a goal pair. Returns won|lost|void|unsettleable."""
    total = home + away
    res = "1" if home > away else ("2" if away > home else "Draw")

    if key == "1x2":
        return "won" if sel == res else "lost"

    if key == "total":
        m = re.match(r"\s*(over|under)\s+(\d+(?:\.\d+)?)\s*$", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        over = m.group(1).lower() == "over"
        line = float(m.group(2))
        if total == line:
            return "void"
        return "won" if (total > line if over else total < line) else "lost"

    if key in ("1 total", "2 total"):
        m = re.match(r"\s*(over|under)\s+(\d+(?:\.\d+)?)\s*$", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        goals = home if key.startswith("1") else away
        over = m.group(1).lower() == "over"
        line = float(m.group(2))
        if goals == line:
            return "void"
        return "won" if (goals > line if over else goals < line) else "lost"

    if key == "both teams to score":
        m = re.match(r"\s*(yes|no)\s*$", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        return "won" if (home > 0 and away > 0) == (m.group(1).lower() == "yes") else "lost"

    if key == "double chance":
        allowed = _DC_PAIRS.get(sel.strip().lower())
        return "unsettleable" if allowed is None else ("won" if res in allowed else "lost")

    if key == "correct score":
        m = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", sel)
        if not m:
            return "unsettleable"
        return "won" if (int(m.group(1)), int(m.group(2))) == (home, away) else "lost"

    if key == "multigoals":
        m = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*$", sel)
        if not m:
            return "unsettleable"
        return "won" if int(m.group(1)) <= total <= int(m.group(2)) else "lost"

    if key == "draw no bet":
        if res == "Draw":
            return "void"
        return "won" if sel.strip() == res else "lost"

    if key == "handicap":
        m = re.match(r"\s*([12])\s*\(([-+]?\d+(?:\.\d+)?)\)\s*$", sel)
        if not m:
            return "unsettleable"
        team, hcap = m.group(1), float(m.group(2))
        h = home + (hcap if team == "1" else 0.0)
        a = away + (hcap if team == "2" else 0.0)
        if h == a:
            return "void"
        return "won" if (("1" if h > a else "2") == team) else "lost"

    if key in ("1 clean sheet", "2 clean sheet"):
        m = re.match(r"\s*(yes|no)\s*$", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        conceded = away if key.startswith("1") else home   # team 1 keeps clean iff away scored 0
        clean = conceded == 0
        return "won" if clean == (m.group(1).lower() == "yes") else "lost"

    if key in ("odd/even", "1 odd/even", "2 odd/even"):
        m = re.match(r"\s*(odd|even)\s*$", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        n = total if key == "odd/even" else (home if key.startswith("1") else away)
        is_odd = n % 2 == 1
        return "won" if is_odd == (m.group(1).lower() == "odd") else "lost"

    return "unsettleable"
```

Then in `grade_leg`, delete the inlined per-market branches (1x2 … handicap) and replace the whole
`key == ...` chain with:

```python
    return _grade_score(key, sel, o.home, o.away)
```

(Keep the `str(... or "").strip()` coercion and the `UNSETTLEABLE` early-return above it for now;
Task 2 narrows the regex and inserts the half/combo dispatch before it.)

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: all pass (existing FT tests + the new ones — FT behaviour is unchanged).

- [ ] **Step 5: Full-suite regression**

Run: `py -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_grade_leg.py
git commit -m "refactor: extract _grade_score core; add DC notations + team/clean-sheet/odd-even subtypes"
```

---

### Task 2: Half + combo wrappers in `grade_leg`; narrow the unsettleable regex

**Files:**
- Modify: `settle.py` (`UNSETTLEABLE` regex; `grade_leg` dispatch — add half + combo + the `1st/2nd half both teams to score` special case)
- Test: `tests/test_grade_leg.py`

**Interfaces:**
- Consumes: Task 1 `_grade_score`. Produces: `grade_leg` (unchanged signature) that now grades half and combo markets. Adds module-level helper `_half_score(o, which) -> tuple[int,int] | None`.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_grade_leg.py`:

```python
HT = MatchOutcome("A vs. B", 2, 1, ht_home=1, ht_away=0)   # HT 1-0, FT 2-1
NOHT = MatchOutcome("A vs. B", 2, 1)                        # no half-time score


def test_half_multigoals():
    assert grade_leg("1st half - multigoals", "1-3", HT) == "won"   # 1 HT goal
    assert grade_leg("2nd half - multigoals", "1-3", HT) == "won"   # 2nd half = (2-1)+(1-0)=2
    assert grade_leg("2nd half - multigoals", "3-5", HT) == "lost"


def test_half_missing_ht_is_unsettleable():
    assert grade_leg("1st half - multigoals", "1-3", NOHT) == "unsettleable"


def test_half_clean_sheet_and_total():
    assert grade_leg("2nd half - 2 Clean sheet", "No", HT) == "won"   # home scored in 2nd half
    assert grade_leg("1st half - total", "Over 0.5", HT) == "won"     # 1 HT goal > 0.5


def test_half_stat_market_still_unsettleable():
    assert grade_leg("1st half - total bookings", "Over 0.5", HT) == "unsettleable"
    assert grade_leg("1st half - first corner", "1", HT) == "unsettleable"


def test_combo_dc_and_total():
    assert grade_leg("Double chance & total 5.5", "1/2 & under 5.5", HT) == "won"
    assert grade_leg("Double chance & total 1.5", "1/2 & under 1.5", HT) == "lost"   # 3 goals


def test_combo_dc_match_and_half_btts():
    # DC "12" (home won) AND 1st-half both-teams-score "no" (away 0 at HT -> not both) -> won/won
    assert grade_leg("Double chance (match) & 1st half both teams score", "12 & no", HT) == "won"


def test_combo_with_stat_component_is_unsettleable():
    assert grade_leg("1x2 & total corners", "1 & over 8.5", HT) == "unsettleable"


def test_combo_precedence_lost_beats_void():
    # total push (void) & DC lost -> lost
    assert grade_leg("Double chance & total 3", "x/2 & over 3", HT) == "lost"


def test_first_second_half_both_teams_to_score():
    # HT 1-0 (1st-half BTTS no), 2nd half 1-1 (BTTS yes) -> "No/no": 1st no=won, 2nd no=lost -> lost
    assert grade_leg("1st/2nd half both teams to score", "No/no", HT) == "lost"


def test_first_goal_scorer_combo_unsettleable():
    assert grade_leg("First goal & 1x2", "1 & 1", HT) == "unsettleable"
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_grade_leg.py -k "half or combo or first_" -v`
Expected: failures (half/combo markets currently return `unsettleable`, so several asserts fail).

- [ ] **Step 3: Implement** — narrow the regex and rewrite `grade_leg`'s dispatch. Change:

```python
UNSETTLEABLE = re.compile(r"corner|booking|card|shot|tackle|offside|foul", re.IGNORECASE)
```

Add a half-score helper near `_grade_score`:

```python
def _half_score(o: MatchOutcome, which: str) -> tuple[int, int] | None:
    """(home, away) goals in the given half, or None if half-time score is unknown."""
    if o.ht_home is None or o.ht_away is None:
        return None
    if which == "1st":
        return (o.ht_home, o.ht_away)
    return (o.home - o.ht_home, o.away - o.ht_away)   # 2nd half
```

Rewrite `grade_leg` so its body (after the `str(...).strip()` coercion) is:

```python
    name = str(market or "").strip()
    sel = str(selection or "").strip()
    low = name.lower()

    # combo: split market + selection on " & ", grade each, AND with precedence
    if " & " in low:
        mparts = [p.strip() for p in re.split(r"\s+&\s+", name)]
        sparts = [p.strip() for p in re.split(r"\s+&\s+", sel)]
        if len(mparts) != len(sparts) or len(mparts) < 2:
            return "unsettleable"
        return _combine([grade_leg(mp, sp, o) for mp, sp in zip(mparts, sparts)])

    # "1st/2nd half both teams to score": selection "X/Y" = 1st-half BTTS / 2nd-half BTTS
    if low == "1st/2nd half both teams to score":
        parts = [p.strip() for p in sel.split("/")]
        if len(parts) != 2:
            return "unsettleable"
        v1 = _grade_on_half(o, "1st", "both teams to score", parts[0])
        v2 = _grade_on_half(o, "2nd", "both teams to score", parts[1])
        return _combine([v1, v2])

    # half markets: "1st half - <core>" / "2nd half - <core>" (or without the dash, inside combos)
    hm = re.match(r"(1st|2nd)\s*half\s*-?\s*(.*)$", low)
    if hm and hm.group(2):
        return _grade_on_half(o, hm.group(1), hm.group(2).strip(), sel)

    if UNSETTLEABLE.search(name):
        return "unsettleable"
    return _grade_score(low, sel, o.home, o.away)
```

Add the two helpers used above:

```python
def _grade_on_half(o: MatchOutcome, which: str, core_market: str, sel: str) -> str:
    """Grade a core score market on the 1st/2nd-half score; unsettleable if ht unknown or a stat."""
    if UNSETTLEABLE.search(core_market):
        return "unsettleable"
    hs = _half_score(o, which)
    if hs is None:
        return "unsettleable"
    key = core_market.strip().lower()
    if key in ("both teams score", "both teams to score"):
        key = "both teams to score"
    return _grade_score(key, sel, hs[0], hs[1])


def _combine(verdicts: list[str]) -> str:
    """Combo precedence: unsettleable > lost > void > won."""
    if any(v == "unsettleable" for v in verdicts):
        return "unsettleable"
    if any(v == "lost" for v in verdicts):
        return "lost"
    if any(v == "void" for v in verdicts):
        return "void"
    return "won"
```

Note: the combo branch recurses through `grade_leg`, so a component like `"1st half both teams score"`
re-enters and is caught by the half-markets regex (`1st half ...` without a dash), and a stat component
like `"total corners"` hits `UNSETTLEABLE` → the combo becomes unsettleable via precedence. `First goal`
is neither a stat token nor a score key, so `_grade_score` returns `unsettleable` → combo unsettleable.

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: all pass (existing FT + Task 1 + the new half/combo cases).

- [ ] **Step 5: Full suite + real-file coverage re-measure**

Run: `py -m pytest tests/ -q` → all pass.
Run this one-off to confirm coverage rose (use the newest betslips file):
```bash
py -c "import re,sys; from pathlib import Path; from settle import grade_leg, MatchOutcome; \
bf=sorted(Path('output').glob('run_*/betslips_*.txt'))[-1].read_text(encoding='utf-8'); \
legs=re.findall(r'^\s*\d+\.\s+.*? - .*? - (.*?): (.*?) @ [\d.]+$', bf, re.M); \
o=MatchOutcome('x',2,1,1,0); \
g=sum(1 for m,s in legs if grade_leg(m,s,o)!='unsettleable'); \
print(f'gradeable legs: {g}/{len(legs)} = {100*g/len(legs):.0f}%')"
```
Expected: materially above the old 37% (high-80s%; exact value depends on the file's stat-leg share).

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_grade_leg.py
git commit -m "feat: grade half and combo score markets (HT/FT); narrow unsettleable to stats only"
```

---

### Task 3: Docs

**Files:**
- Modify: `README.md` (Settlement section), `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`

- [ ] **Step 1: Update `README.md`.** In the Settlement / backtest section, change the v1-scope sentence to: "Grades full-time AND half markets (1st/2nd-half goals, multigoals, totals, 1x2, double chance, BTTS, clean sheet, odd/even) and `A & B` combos of those — all from the HT+FT score (enter `ht_home,ht_away` columns to unlock half markets). Stat markets (corners/cards/bookings/shots) and first-goal-scorer markets still need a stats provider and show as *ungradeable*." Note that a slip is only gradeable if ALL its legs are — so SET B slips (with corners/cards legs) stay ungradeable until a stats provider is added.

- [ ] **Step 2: Update the as-built spec** `C:\Users\user\.claude\plans\prompt-eljam3ia-odds-cheerful-owl.md`: under the settlement bullet, note `settle.py` now grades half + combo score markets via `_grade_score` + half/combo wrappers, and that `UNSETTLEABLE` is now stats/event-only.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: settle.py grades half + combo score markets"
```

---

## Self-Review

**Spec coverage:** `_grade_score` refactor + DC notations + sub-types → Task 1. Half wrapper (ht-based, missing-ht → unsettleable, stat-in-half → unsettleable) → Task 2. Combo wrapper (split, recurse, precedence) + `1st/2nd half both teams to score` special case + first-goal exclusion → Task 2. Narrowed `UNSETTLEABLE` → Task 2. Coverage re-measure → Task 2 Step 5. Docs → Task 3. Out-of-scope (stat/event markets) correctly remain unsettleable. Covered.

**Placeholder scan:** none — all code complete; the coverage-re-measure one-liner is a concrete command.

**Type consistency:** `_grade_score(key, sel, home, away) -> str` (Task 1) is called by `grade_leg`'s FT path (Task 1) and by `_grade_on_half` (Task 2). `_half_score(o, which) -> tuple|None`, `_grade_on_half(o, which, core_market, sel) -> str`, `_combine(list[str]) -> str` all defined and used in Task 2. `MatchOutcome.ht_home/ht_away` are the existing fields. `grade_leg`/`grade_slip`/`settle_run` signatures unchanged, so `parse_betslips`/backtest wiring is untouched.
