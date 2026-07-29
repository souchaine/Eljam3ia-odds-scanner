# Score-Derivable Coverage Tranche Implementation Plan (settle.py)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grade the remaining HT+FT-score-derivable market shapes (~255 legs) that currently return `unsettleable`, and report hit rate per market family instead of as a blended aggregate.

**Architecture:** Same pattern as the shipped half/combo work — extend the pure `_grade_score(key, sel, home, away)` core with new score sub-types (which inherit half-prefixing through the existing `_grade_on_half` for free), add two `grade_leg` dispatch branches that need context `_grade_score` cannot see (HT/FT needs both halves; OR-combos need multi-component parsing), and add a `_market_family` classifier feeding per-family tallies in `settle_run`. No new module, no new dependency.

**Tech Stack:** Python 3.11 stdlib only (`re`, `dataclasses`, `csv`). `pytest` (dev). Windows `py` launcher.

## Global Constraints

- `grade_leg` never raises; unknown market/selection -> `unsettleable`; verdicts are exactly `won|lost|void|unsettleable`.
- All existing FT/half/combo tests must pass UNCHANGED (regression). Do not modify `_grade_score`'s existing 8 FT market branches.
- **Gate 2 (binding):** `handicap 1X2` selection `"S (a:b)"` -> `adj_home = home + a`, `adj_away = away + b`, `S` in `{1, 2, Draw}`, won iff result == S. **Equality is a `Draw` win, NEVER a void.** This is a NEW branch, distinct from the existing Asian `handicap` key (which does void on equality — leave it alone).
- **Gate 1 (binding):** multigoals selections have THREE forms: `"N-M"` (closed range), `"N+"` (open-ended, >= N), `"No goal"` (== 0). Never `split("-")` naively. Apply all three to the existing plain `multigoals` key too.
- **Gate 3 (binding):** `MatchOutcome.home/.away` are full-time CUMULATIVE; 2nd half = FT - HT.
- Missing `ht_home`/`ht_away` for any half or HT/FT leg -> `unsettleable`.
- Report hit rate PER FAMILY with per-family n. Emit NO blended aggregate. The slip-level tracker stays in output but is NOT a success metric.
- Out of scope, must stay `unsettleable`: player markets (`shots - <p>`, `shots on goal - <p>`, `saves goalkeeper (<p>)`, `to score or assist <p>`), `total corners|bookings|shots`, `race to N corners`, `first|last corner`, `first|last goal`, `first scoring type`, `a penalty in the match`, `15 minutes - ...`, `first goal & 1x2`, `both halves over`.
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`. Run with `py`. Branch: `feature/score-derivable-tranche`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `settle.py` | grading + settlement | Add score sub-types to `_grade_score`; add `_grade_htft` + `_grade_or` dispatch; add `_market_family`; per-family tallies in `settle_run` + `main` |
| `tests/test_grade_leg.py` | grading tests | Add sub-type / handicap-1X2 / HT/FT / OR tests |
| `tests/test_settle_run.py` | settlement tests | Add per-family tally tests (create if absent) |

---

### Task 1: Phase 1 grading — team sub-types, handicap 1X2, HT/FT

**Files:**
- Modify: `settle.py` (`_grade_score` new keys; new `_grade_htft`; `grade_leg` dispatch)
- Test: `tests/test_grade_leg.py`

**Interfaces:**
- Produces: `_grade_htft(o: MatchOutcome, sel: str, dc: bool = False) -> str`. Extends `_grade_score` with keys `1 multigoals`, `2 multigoals`, `N exact goals`, `N to score`, `handicap 1x2`, and extends the existing `multigoals` key's selection forms.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_grade_leg.py`:

```python
HTFT = MatchOutcome("A vs. B", 2, 1, ht_home=1, ht_away=0)   # FT 2-1, HT 1-0, 2nd half 1-1


def test_team_multigoals_all_three_selection_forms():
    o = MatchOutcome("x", 3, 0)
    assert grade_leg("1 multigoals", "1-3", o) == "won"      # home 3 in [1,3]
    assert grade_leg("1 multigoals", "1-2", o) == "lost"
    assert grade_leg("2 multigoals", "No goal", o) == "won"  # away scored 0
    assert grade_leg("1 multigoals", "No goal", o) == "lost"
    assert grade_leg("1 multigoals", "3+", o) == "won"       # home 3 >= 3
    assert grade_leg("1 multigoals", "4+", o) == "lost"
    assert grade_leg("1 multigoals", "banana", o) == "unsettleable"


def test_plain_multigoals_gains_open_ended_and_no_goal():
    o = MatchOutcome("x", 3, 1)                              # 4 total
    assert grade_leg("Multigoals", "4+", o) == "won"
    assert grade_leg("Multigoals", "5+", o) == "lost"
    assert grade_leg("Multigoals", "No goal", MatchOutcome("x", 0, 0)) == "won"
    assert grade_leg("Multigoals", "1-3", o) == "lost"       # existing form still works


def test_team_exact_goals_and_to_score_on_half():
    assert grade_leg("1st half - 1 exact goals", "1", HTFT) == "won"   # home 1 at HT
    assert grade_leg("1st half - 2 exact goals", "0", HTFT) == "won"   # away 0 at HT
    assert grade_leg("1st half - 2 exact goals", "1", HTFT) == "lost"
    assert grade_leg("1st half - 2 to score", "No", HTFT) == "won"     # away didn't score in H1
    assert grade_leg("1st half - 1 to score", "Yes", HTFT) == "won"


def test_handicap_1x2_direction_and_no_void():
    o = MatchOutcome("x", 2, 1)
    # (a:b) = home-start : away-start; leading token = bet side
    assert grade_leg("Handicap 1x2", "1 (1:0)", o) == "won"    # adj 3-1 -> 1
    assert grade_leg("Handicap 1x2", "2 (0:1)", o) == "lost"   # adj 2-2 -> Draw, so "2" loses
    assert grade_leg("Handicap 1x2", "2 (0:2)", o) == "won"    # adj 2-3 -> 2
    # equality is a Draw WIN, never a void (Gate 2)
    assert grade_leg("Handicap 1x2", "Draw (0:1)", o) == "won"  # adj 2-2 -> Draw
    assert grade_leg("Handicap 1x2", "1 (0:1)", o) == "lost"


def test_handicap_1x2_never_voids_unlike_asian_handicap():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Handicap 1x2", "1 (0:1)", o) != "void"
    assert grade_leg("Handicap", "2 (+1)", o) == "void"        # existing Asian market unchanged


def test_handicap_1x2_on_half():
    # 2nd half = 1-1; "1 (1:0)" -> adj 2-1 -> 1 -> won
    assert grade_leg("2nd half - handicap 1X2", "1 (1:0)", HTFT) == "won"
    assert grade_leg("2nd half - handicap 1X2", "2 (0:1)", HTFT) == "won"   # adj 1-2 -> 2


def test_htft_uses_cumulative_ft():
    # Gate 3: FT is cumulative. HT result 1, FT result 1 -> "1/1" won.
    # If FT were treated as 2nd-half-only (1,1) the FT result would be Draw -> lost.
    assert grade_leg("Halftime/fulltime", "1/1", HTFT) == "won"
    assert grade_leg("Halftime/fulltime", "1/X", HTFT) == "lost"
    assert grade_leg("Halftime/fulltime", "X/1", HTFT) == "lost"


def test_htft_dc_variant_and_missing_ht():
    o = MatchOutcome("x", 1, 2, ht_home=0, ht_away=1)   # HT 0-1 (away), FT 1-2 (away)
    assert grade_leg("DC Halftime/ DC Fulltime", "X2/X2", o) == "won"
    assert grade_leg("DC Halftime/ DC Fulltime", "1X/1X", o) == "lost"
    assert grade_leg("Halftime/fulltime", "1/1", MatchOutcome("x", 2, 1)) == "unsettleable"


def test_htft_total_combo_recurses():
    # combo wrapper already splits on " & "; each side graded independently
    assert grade_leg("Halftime/fulltime & total 2.5", "1/1 & over 2.5", HTFT) == "won"
    assert grade_leg("Halftime/fulltime & total 6.5", "1/1 & over 6.5", HTFT) == "lost"


def test_out_of_scope_markets_stay_unsettleable():
    for m, s in [("Shots - Neymar", "Over 0.5"), ("Saves goalkeeper (Jandrei)", "Over 2.5"),
                 ("To score or assist Neymar", "Over 0.5"), ("Total corners", "Over 8.5"),
                 ("Race to 5 corners", "1"), ("First scoring type", "Goal"),
                 ("A penalty in the match", "Yes"), ("Corner 1x2", "1 (1:0)"),
                 ("15 minutes - 1x2 from 0:00 to 14:59", "1"), ("Both halves over 1.5", "No")]:
        assert grade_leg(m, s, HTFT) == "unsettleable", m
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_grade_leg.py -k "multigoals or exact_goals or handicap_1x2 or htft or out_of_scope" -v`
Expected: FAIL — new markets currently return `unsettleable` (and `Multigoals "4+"` returns `unsettleable`).

- [ ] **Step 3: Implement**

In `settle.py`, add a shared multigoals-selection helper and use it for BOTH the existing plain
`multigoals` key and the new team keys:

```python
def _multigoals_hit(sel: str, goals: int) -> str | None:
    """Grade a multigoals bucket. Forms: "N-M", "N+", "No goal". None if unparseable."""
    s = sel.strip()
    if re.fullmatch(r"no\s+goal", s, re.IGNORECASE):
        return "won" if goals == 0 else "lost"
    m = re.fullmatch(r"(\d+)\s*\+", s)
    if m:
        return "won" if goals >= int(m.group(1)) else "lost"
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return "won" if int(m.group(1)) <= goals <= int(m.group(2)) else "lost"
    return None
```

Replace the existing `multigoals` branch body in `_grade_score` with:

```python
    if key == "multigoals":
        v = _multigoals_hit(sel, total)
        return v if v is not None else "unsettleable"

    if key in ("1 multigoals", "2 multigoals"):
        v = _multigoals_hit(sel, home if key.startswith("1") else away)
        return v if v is not None else "unsettleable"
```

Add the remaining new branches to `_grade_score` (before its final `return "unsettleable"`):

```python
    m = re.fullmatch(r"([12])\s+exact\s+goals", key)
    if m:
        if not re.fullmatch(r"\d+", sel.strip()):
            return "unsettleable"
        goals = home if m.group(1) == "1" else away
        return "won" if goals == int(sel.strip()) else "lost"

    m = re.fullmatch(r"([12])\s+to\s+score", key)
    if m:
        y = re.fullmatch(r"\s*(yes|no)\s*", sel, re.IGNORECASE)
        if not y:
            return "unsettleable"
        goals = home if m.group(1) == "1" else away
        return "won" if (goals > 0) == (y.group(1).lower() == "yes") else "lost"

    if key == "handicap 1x2":
        # Gate 2: (a:b) = home-start:away-start; leading token = bet side; NO void (Draw is a
        # real selection, each line is its own 3-way market).
        m = re.fullmatch(r"\s*(1|2|draw|x)\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)\s*", sel, re.IGNORECASE)
        if not m:
            return "unsettleable"
        side = m.group(1).lower()
        side = "Draw" if side in ("draw", "x") else side
        h = home + int(m.group(2))
        a = away + int(m.group(3))
        res = "1" if h > a else ("2" if a > h else "Draw")
        return "won" if res == side else "lost"
```

Add the HT/FT helper next to `_grade_on_half`:

```python
def _grade_htft(o: MatchOutcome, sel: str, dc: bool = False) -> str:
    """Grade Halftime/fulltime ("1/1") or DC Halftime/DC Fulltime ("X2/X2").

    Needs BOTH halves, so it cannot live in _grade_score. FT is cumulative (Gate 3).
    """
    if o.ht_home is None or o.ht_away is None:
        return "unsettleable"
    parts = [p.strip() for p in sel.split("/")]
    if dc:                      # "X2/X2" -> two double-chance tokens
        if len(parts) != 2:
            return "unsettleable"
        picks = parts
    else:                       # "1/1" -> two single results
        if len(parts) != 2:
            return "unsettleable"
        picks = parts
    ht_res = "1" if o.ht_home > o.ht_away else ("2" if o.ht_away > o.ht_home else "Draw")
    ft_res = "1" if o.home > o.away else ("2" if o.away > o.home else "Draw")
    for pick, res in zip(picks, (ht_res, ft_res)):
        if dc:
            allowed = _DC_PAIRS.get(pick.lower())
            if allowed is None:
                return "unsettleable"
            if res not in allowed:
                return "lost"
        else:
            want = {"1": "1", "2": "2", "x": "Draw", "draw": "Draw"}.get(pick.lower())
            if want is None:
                return "unsettleable"
            if res != want:
                return "lost"
    return "won"
```

Wire the dispatch in `grade_leg`, immediately AFTER the combo branch and BEFORE the
`1st/2nd half both teams to score` special case (so `... & total` combos still split first):

```python
    if low in ("halftime/fulltime", "half time/full time"):
        return _grade_htft(o, sel)
    if re.fullmatch(r"dc\s*halftime\s*/\s*dc\s*fulltime", low):
        return _grade_htft(o, sel, dc=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: all pass, including every pre-existing test unchanged.

- [ ] **Step 5: Full-suite regression**

Run: `py -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_grade_leg.py
git commit -m "feat: grade team multigoals/exact-goals/to-score, 3-way handicap, HT/FT"
```

---

### Task 2: Phase 1 reporting — `_market_family` + per-family tallies

**Files:**
- Modify: `settle.py` (`_market_family`, `settle_run`, `main` output)
- Test: `tests/test_settle_run.py`

**Interfaces:**
- Consumes: `grade_leg` from Task 1. Produces: `_market_family(market: str) -> str`; `settle_run(...)` return dict gains a `"families"` key -> `{family: {"n": int, "gradeable": int, "won": int}}`.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_settle_run.py` (create the file with `from settle import ...` imports if it does not exist):

```python
from settle import _market_family, settle_run, MatchOutcome


def test_market_family_classifies_known_families():
    assert _market_family("1x2") == "main"
    assert _market_family("Double chance") == "main"
    assert _market_family("1st half - multigoals") == "1st half"
    assert _market_family("2nd half - handicap 1X2") == "2nd half"
    assert _market_family("Total corners") == "corners"
    assert _market_family("Total bookings") == "cards"
    assert _market_family("2 multigoals") == "multigoals"
    assert _market_family("Halftime/fulltime") == "htft"
    assert _market_family("Draw or under 1.5") == "or-combo"
    assert _market_family("Double chance & total 5.5") == "combo"


def test_market_family_has_explicit_other_bucket():
    # an unanticipated market must land visibly in "other", not be force-fit
    assert _market_family("Some Novel Market") == "other"
    assert _market_family("Shots - Neymar") == "player"


def test_settle_run_reports_per_family_counts():
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4},
        {"league": "L", "match": "m", "market": "1x2", "selection": "2", "odd": 1.4},
        {"league": "L", "match": "m", "market": "Total corners", "selection": "Over 8.5", "odd": 1.4},
    ]}]
    outcomes = {"m": MatchOutcome("m", 2, 1)}
    res = settle_run(slips, outcomes)
    fam = res["families"]
    assert fam["main"]["n"] == 2
    assert fam["main"]["gradeable"] == 2
    assert fam["main"]["won"] == 1              # "1" won, "2" lost
    assert fam["corners"]["n"] == 1
    assert fam["corners"]["gradeable"] == 0     # needs a provider
    assert fam["corners"]["won"] == 0


def test_settle_run_keeps_existing_per_set_tallies():
    slips = [{"set": "A", "label": "A1", "code": "X", "pred_win_pct": 1.0, "legs": [
        {"league": "L", "match": "m", "market": "1x2", "selection": "1", "odd": 1.4}]}]
    res = settle_run(slips, {"m": MatchOutcome("m", 2, 1)})
    assert res["A"]["total"] == 1 and res["A"]["won"] == 1
    assert "verdicts" in res
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_settle_run.py -v`
Expected: ImportError on `_market_family`, and `KeyError: 'families'`.

- [ ] **Step 3: Implement**

Add to `settle.py`:

```python
# family classification for per-family hit-rate reporting. Order matters: the first match
# wins, so stat/player families are checked before the period families.
_FAMILIES = [
    ("player",     r"shots?\s*-|shots on goal\s*-|saves goalkeeper|to score or assist"),
    ("corners",    r"corner"),
    ("cards",      r"booking|card"),
    ("stat-other", r"\bshots?\b|tackle|offside|foul|penalty in the match|scoring type"),
    ("interval",   r"\d+\s*minutes\s*-"),
    ("htft",       r"halftime\s*/\s*fulltime|dc\s*halftime"),
    ("combo",      r" & "),
    ("or-combo",   r"\bor\b"),
    ("multigoals", r"multigoals"),
    ("1st half",   r"1st\s*half|first\s*half"),
    ("2nd half",   r"2nd\s*half|second\s*half"),
    ("main",       r"^(1x2|total|both teams to score|double chance|correct score|"
                   r"draw no bet|handicap|handicap 1x2|[12] (total|clean sheet|odd/even)|odd/even)"),
]


def _market_family(market: str) -> str:
    """Classify a market into a reporting family. Unanticipated markets land in 'other'."""
    name = str(market or "").strip().lower()
    for fam, pat in _FAMILIES:
        if re.search(pat, name):
            return fam
    return "other"
```

In `settle_run`, tally per family alongside the existing per-set work. Inside the `for slip in slips`
loop, after computing `lv = _leg_verdicts(slip, outcomes)`:

```python
        for leg, v in zip(slip["legs"], lv):
            f = families.setdefault(_market_family(leg["market"]),
                                    {"n": 0, "gradeable": 0, "won": 0})
            f["n"] += 1
            if v != "unsettleable":
                f["gradeable"] += 1
                if v == "won":
                    f["won"] += 1
```

Declare `families: dict[str, dict[str, int]] = {}` before the loop and return it:

```python
    return {**tally, "verdicts": verdicts, "families": families}
```

In `main`, print the per-family table after the per-set lines, and label the tracker:

```python
    print("\nPer-family leg hit rate (no blended aggregate — the gradeable subset is a biased sample):")
    print(f"  {'family':<12} {'n':>5} {'gradeable':>10} {'won':>5}  hit%")
    for fam in sorted(result["families"], key=lambda k: -result["families"][k]["n"]):
        f = result["families"][fam]
        hit = f"{100 * f['won'] / f['gradeable']:.0f}%" if f["gradeable"] else "  -"
        print(f"  {fam:<12} {f['n']:>5} {f['gradeable']:>10} {f['won']:>5}  {hit:>4}")
```

And change the tracker header line in `main` to make its status explicit:

```python
    print("Slip trackers (diagnostic only — a 20-leg parlay is near-information-free):")
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_settle_run.py -v`
Expected: all pass.

- [ ] **Step 5: Full suite + real-file per-family measure**

Run: `py -m pytest tests/ -q` -> all pass.
Then run the real settlement to see the per-family table render (uses the newest betslips file;
scores CSV may be absent — if so, note it and instead print the per-family `n`/`gradeable` split with
this one-liner):
```bash
py -c "import re,sys; from pathlib import Path; from settle import grade_leg, _market_family, MatchOutcome; import collections; bf=sorted(Path('output').glob('run_*/betslips_*.txt'))[-1]; legs=re.findall(r'^\s*\d+\.\s+.*? - .*? - (.*?): (.*?) @ [\d.]+$', bf.read_text(encoding='utf-8'), re.M); o=MatchOutcome('x',2,1,1,0); c=collections.defaultdict(lambda:[0,0]); [ (c[_market_family(m)].__setitem__(0,c[_market_family(m)][0]+1), c[_market_family(m)].__setitem__(1,c[_market_family(m)][1]+(grade_leg(m,s,o)!='unsettleable'))) for m,s in legs ]; [print(f'{k:<12} n={v[0]:>4} gradeable={v[1]:>4}') for k,v in sorted(c.items(), key=lambda kv:-kv[1][0])]"
```
Expected: an `other` bucket that is small; `multigoals`/`htft`/`2nd half` gradeable counts materially up from zero.

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_settle_run.py
git commit -m "feat: per-family leg hit-rate reporting; tracker demoted to diagnostic"
```

---

### Task 3: Phase 2 — OR-combos (simple + compound)

**Files:**
- Modify: `settle.py` (`_grade_or`, `any clean sheet` sub-type, `grade_leg` dispatch)
- Test: `tests/test_grade_leg.py`

**Interfaces:**
- Consumes: `_grade_score`, `_combine` from earlier work. Produces: `_grade_or(market: str, sel: str, o: MatchOutcome) -> str`.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_grade_leg.py`:

```python
def test_simple_or_market_carries_both_legs():
    o = MatchOutcome("x", 2, 1)                       # home win, 3 goals, no clean sheet
    assert grade_leg("Draw or under 1.5", "Yes", o) == "lost"   # neither
    assert grade_leg("1 or under 1.5", "Yes", o) == "won"       # home win satisfies
    assert grade_leg("Draw or over 2.5", "Yes", o) == "won"     # 3 > 2.5 satisfies
    assert grade_leg("2 or over 2.5", "Yes", o) == "won"


def test_simple_or_handles_no_as_negation():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("1 or under 1.5", "No", o) == "lost"       # OR is true -> "No" loses
    assert grade_leg("Draw or under 1.5", "No", o) == "won"     # OR is false -> "No" wins


def test_or_any_clean_sheet():
    assert grade_leg("2 or any clean sheet", "Yes", MatchOutcome("x", 2, 0)) == "won"   # home clean
    assert grade_leg("1 or any clean sheet", "Yes", MatchOutcome("x", 0, 2)) == "won"   # away clean
    assert grade_leg("Draw or any clean sheet", "Yes", MatchOutcome("x", 2, 1)) == "lost"


def test_or_both_teams_to_score():
    assert grade_leg("1 or both teams to score", "Yes", MatchOutcome("x", 2, 1)) == "won"
    assert grade_leg("2 or both teams to score", "Yes", MatchOutcome("x", 2, 0)) == "lost"


def test_compound_or_binds_selection_tokens_by_type_not_position():
    # market: "Both team to score or Total 2.5"; selection: "Under 2.5 or no"
    # NOTE the selection order is REVERSED vs the market name. Positional pairing would try to
    # grade BTTS with "Under 2.5" and Total with "no" -> must bind by TYPE.
    o = MatchOutcome("x", 1, 0)                        # 1 goal, BTTS no
    assert grade_leg("Both team to score or Total 2.5", "Under 2.5 or no", o) == "won"
    o2 = MatchOutcome("x", 2, 1)                       # 3 goals (over 2.5), BTTS yes
    assert grade_leg("Both team to score or Total 2.5", "Under 2.5 or no", o2) == "lost"
    assert grade_leg("Both team to score or Total 2.5", "Over 2.5 or yes", o2) == "won"


def test_or_combo_malformed_is_unsettleable():
    o = MatchOutcome("x", 2, 1)
    assert grade_leg("Draw or under 1.5", "banana", o) == "unsettleable"
    assert grade_leg("1 or total corners", "Yes", o) == "unsettleable"   # stat component
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_grade_leg.py -k "_or_" -v`
Expected: FAIL — these currently return `unsettleable`.

- [ ] **Step 3: Implement**

Add an `any clean sheet` sub-type to `_grade_score` (before its final return):

```python
    if key == "any clean sheet":
        y = re.fullmatch(r"\s*(yes|no)\s*", sel, re.IGNORECASE)
        if not y:
            return "unsettleable"
        anyclean = home == 0 or away == 0
        return "won" if anyclean == (y.group(1).lower() == "yes") else "lost"
```

Add the OR grader. It grades each component to a boolean-ish verdict, ORs them, then applies the
Yes/No selection:

```python
_OR_SPLIT = re.compile(r"\s+or\s+", re.IGNORECASE)


def _or_component_verdict(part: str, o: MatchOutcome, tokens: list[str]) -> str:
    """Grade one OR component, consuming the selection token that matches it BY TYPE."""
    p = _score_key(part.strip().lower())
    if p in ("1", "2", "draw", "x"):                       # bare result token
        return _grade_score("1x2", {"x": "Draw", "draw": "Draw"}.get(p, p), o.home, o.away)
    if re.fullmatch(r"(over|under)\s+\d+(?:\.\d+)?", p):   # line carried in the market name
        return _grade_score("total", p, o.home, o.away)
    if "any clean sheet" in p:
        return _grade_score("any clean sheet", _take(tokens, r"yes|no") or "Yes", o.home, o.away)
    if "both team" in p:                                   # both team(s) to score
        return _grade_score("both teams to score", _take(tokens, r"yes|no") or "Yes", o.home, o.away)
    if p.startswith("total"):                              # "Total 2.5" -> line comes from a token
        tok = _take(tokens, r"(over|under)\s+\d+(?:\.\d+)?")
        return _grade_score("total", tok, o.home, o.away) if tok else "unsettleable"
    return "unsettleable"


def _take(tokens: list[str], pattern: str) -> str | None:
    """Pop the first selection token matching pattern (type-binding, not positional)."""
    for i, t in enumerate(tokens):
        if re.fullmatch(pattern, t.strip(), re.IGNORECASE):
            return tokens.pop(i).strip()
    return None


def _grade_or(market: str, sel: str, o: MatchOutcome) -> str:
    """Grade an "A or B" market. Selection is "Yes"/"No", or per-component tokens."""
    if UNSETTLEABLE.search(market):
        return "unsettleable"
    parts = [p for p in _OR_SPLIT.split(market.strip()) if p.strip()]
    if len(parts) != 2:
        return "unsettleable"
    s = sel.strip()
    yesno = re.fullmatch(r"(yes|no)", s, re.IGNORECASE)
    tokens = [] if yesno else [t for t in _OR_SPLIT.split(s) if t.strip()]
    if not yesno and not tokens:
        return "unsettleable"
    verdicts = [_or_component_verdict(p, o, tokens) for p in parts]
    if any(v == "unsettleable" for v in verdicts):
        return "unsettleable"
    hit = any(v == "won" for v in verdicts)
    want_yes = True if not yesno else yesno.group(1).lower() == "yes"
    return "won" if hit == want_yes else "lost"
```

Wire the dispatch in `grade_leg`, AFTER the combo branch (so `A & B` wins) and after the HT/FT
branch, BEFORE the half branch:

```python
    if re.search(r"\s+or\s+", low) and " & " not in low:
        return _grade_or(name, sel, o)
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: all pass.

- [ ] **Step 5: Full suite + OR line audit**

Run: `py -m pytest tests/ -q` -> all pass.
Confirm every OR-combo total line is a half-line (if any integer line appears, STOP and report — push
behaviour must be defined and tested before grading it):
```bash
py -c "import re; from pathlib import Path; bf=sorted(Path('output').glob('run_*/betslips_*.txt'))[-1]; legs=re.findall(r'^\s*\d+\.\s+.*? - .*? - (.*?): (.*?) @ [\d.]+$', bf.read_text(encoding='utf-8'), re.M); lines=[x for m,s in legs if re.search(r'\s+or\s+',m,re.I) and ' & ' not in m for x in re.findall(r'\d+(?:\.\d+)?', m+' '+s)]; ints=[x for x in lines if '.' not in x]; print('total lines seen:', sorted(set(lines))); print('INTEGER lines (must be empty):', sorted(set(ints)))"
```
Expected: `INTEGER lines (must be empty): []`.

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_grade_leg.py
git commit -m "feat: grade OR-combo markets (simple + compound, type-bound selections)"
```

---

### Task 4: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Settlement section.** Extend the market list to mention team multigoals/exact-goals/to-score, 3-way handicap (`handicap 1X2`), HT/FT, and OR-combos. State that reporting is per market family with per-family n, that there is deliberately no blended aggregate (the gradeable subset is a biased sample), and that the slip tracker is diagnostic only — a 20-leg parlay is near-information-free. Keep the existing "stat/event markets need a provider" sentence. Do not quote a coverage percentage.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: score-derivable tranche + per-family reporting"
```

---

## Self-Review

**Spec coverage:** Gate 1 multigoals three forms (incl. plain-`multigoals` gap) -> Task 1. Gate 2 handicap 1X2 direction + no-void -> Task 1 (two dedicated tests). Gate 3 ft-cumulative -> Task 1 (`test_htft_uses_cumulative_ft`). Team exact-goals / to-score -> Task 1. HT/FT + DC variant + `& total` recursion -> Task 1. Per-family reporting with explicit `other` bucket and no blended aggregate -> Task 2. Slip tracker demoted -> Task 2. OR simple + compound with type-binding + `any clean sheet` + half-line audit -> Task 3. Out-of-scope list -> Task 1 `test_out_of_scope_markets_stay_unsettleable`. Docs -> Task 4. Covered.

**Placeholder scan:** none — every step carries complete code or a concrete command.

**Type consistency:** `_multigoals_hit(sel, goals) -> str | None` (Task 1) used by both multigoals branches. `_grade_htft(o, sel, dc=False) -> str` (Task 1) called from `grade_leg`. `_market_family(market) -> str` (Task 2) called in `settle_run`'s leg loop; `settle_run` return gains `"families"` -> `{str: {"n","gradeable","won"}}`, consumed by `main` and the Task 2 tests. `_grade_or(market, sel, o) -> str`, `_or_component_verdict(part, o, tokens) -> str`, `_take(tokens, pattern) -> str | None` (Task 3) — `_take` mutates `tokens`, which is how type-binding consumes each token exactly once. `_score_key` and `_combine` are pre-existing. `grade_leg`/`grade_slip`/`append_backtest` signatures unchanged.

**Dispatch order (single source of truth, `grade_leg`):** combo `" & "` -> HT/FT -> OR -> `1st/2nd half both teams to score` -> half prefix -> `UNSETTLEABLE` stat regex -> `_grade_score` (FT).
