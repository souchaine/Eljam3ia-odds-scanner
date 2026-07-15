# Settlement Core Implementation Plan (Sub-project 2, provider-agnostic)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `settle.py` module that reads a run's `betslips_*.txt` and a hand-entered scores CSV, grades each leg's full-time score-derivable market (others → `unsettleable`), tallies the two trackers (SET A 0..50, SET B 0..25), and appends per-slip rows to a persistent `backtest.csv`.

**Architecture:** Pure functions — `parse_betslips`, `read_outcomes_csv`, `grade_leg`, `grade_slip`, `settle_run` — with a thin CLI. No external results API (a `ResultsSource` protocol + `NoResultsSource` stub mark the future seam). v1 grades 8 full-time score markets; stat/half/combo markets return `unsettleable`. Standalone module; the scanner/builder are untouched.

**Tech Stack:** Python 3.11 stdlib only (`csv`, `re`, `argparse`, `dataclasses`, `datetime`, `typing`); `pytest` (dev). Windows `py` launcher. No new runtime dependencies.

## Global Constraints

- v1 `grade_leg` handles ONLY full-time, score-derivable markets: `1x2`, `Total` (Over/Under goals), `Both Teams To Score`, `Double chance`, `Correct score`, `Multigoals`, `Draw no bet`, `Handicap` (goal handicap). Any market name matching `corner|booking|card|shot|tackle|offside|foul|1st half|2nd half|halftime|half-time| & |odd/even` OR unrecognized → `unsettleable`. Never raise on unknown input.
- Verdicts are the exact strings `"won"`, `"lost"`, `"void"`, `"unsettleable"` (leg) and `"won"`, `"lost"`, `"ungradeable"` (slip). `void` legs are treated as non-losing (removed from the all-won check).
- `grade_slip` → `"ungradeable"` if any leg is `unsettleable` or its match is missing from outcomes; else `"won"` iff every non-void leg is `won`; else `"lost"`.
- Trackers: SET A score = count of `won` slips (cap 50), SET B = count of `won` slips (cap 25), over gradeable slips only.
- `MatchOutcome` = dataclass `{match: str, home: int, away: int, ht_home: int | None = None, ht_away: int | None = None}`.
- `backtest.csv` columns exactly: `settled_at, run_dir, set, code, legs, pred_win_pct, verdict, gradeable_legs, won_legs` (`utf-8-sig`, append, write header only when the file is new).
- CLI: `py settle.py <betslips_txt> --outcomes <scores_csv> [--backtest output/backtest.csv]`.
- Betslips leg line format (verbatim from the builder): `  N. <league> - <match> - <market>: <selection> @ <odd>`. Section headers: `===== SET A: all-odds ... =====` / `===== SET B: 7-category diversified ... =====`. Slip header: `BETSLIP <label>  (... win% <x> ...)`. Code line: `  >> BOOKING CODE: <code>`.
- Project root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`; run from there with `py`. Branch: continue on `feature/per-category-betslips`.

## File Structure

| File | Responsibility |
|---|---|
| `settle.py` (Create) | Everything: dataclasses, parse, read outcomes, grade, settle, CLI |
| `tests/test_grade_leg.py` (Create) | Per-market grading rules |
| `tests/test_settle.py` (Create) | parse_betslips, read_outcomes_csv, grade_slip, settle_run |
| `README.md` (Modify) | Document `settle.py` usage |

---

### Task 1: Data types + `grade_leg` (score-market grading)

**Files:**
- Create: `settle.py`
- Test: `tests/test_grade_leg.py`

**Interfaces:**
- Produces: `MatchOutcome` (dataclass, fields above); `grade_leg(market: str, selection: str, o: MatchOutcome) -> str` returning `"won"|"lost"|"void"|"unsettleable"`. Tasks 2–3 import both.

- [ ] **Step 1: Write the failing tests** — create `tests/test_grade_leg.py`:

```python
from settle import MatchOutcome, grade_leg

O = MatchOutcome("A vs. B", 2, 1)          # FT 2-1
D = MatchOutcome("C vs. D", 1, 1)          # draw 1-1


def g(market, sel, o=O):
    return grade_leg(market, sel, o)


def test_1x2():
    assert g("1x2", "1") == "won"
    assert g("1x2", "2") == "lost"
    assert g("1x2", "Draw") == "lost"
    assert g("1x2", "Draw", D) == "won"


def test_total_goals():
    assert g("Total", "Over 2.5") == "won"     # 3 > 2.5
    assert g("Total", "Under 2.5") == "lost"
    assert g("Total", "Over 3") == "void"       # exactly 3 -> push
    assert g("Total", "Under 3.5") == "won"


def test_btts():
    assert g("Both Teams To Score", "Yes") == "won"
    assert g("Both Teams To Score", "No") == "lost"
    assert g("Both Teams To Score", "Yes", MatchOutcome("x", 2, 0)) == "lost"


def test_double_chance():
    assert g("Double chance", "1 or draw") == "won"
    assert g("Double chance", "Draw or 2") == "lost"
    assert g("Double chance", "1 or 2") == "won"


def test_correct_score():
    assert g("Correct score", "2:1") == "won"
    assert g("Correct score", "1:1") == "lost"


def test_multigoals():
    assert g("Multigoals", "1-3") == "won"      # 3 goals
    assert g("Multigoals", "4-6") == "lost"
    assert g("Multigoals", "0-1") == "lost"


def test_draw_no_bet():
    assert g("Draw no bet", "1") == "won"
    assert g("Draw no bet", "2") == "lost"
    assert g("Draw no bet", "1", D) == "void"


def test_handicap_goal():
    assert g("Handicap", "2 (+1.5)") == "won"     # away 1+1.5=2.5 vs 2 -> away covers
    assert g("Handicap", "1 (-1.5)") == "lost"    # home 2-1.5=0.5 vs 1 -> home fails
    assert g("Handicap", "2 (+1)") == "void"      # away 1+1=2 == home 2 -> push


def test_unsettleable_markets():
    for m in ["Total corners", "Total bookings", "1st half - total", "Total shots",
              "DC Halftime/ DC Fulltime", "Total & GG/NG", "Odd/even corners", "Total Offside"]:
        assert grade_leg(m, "Over 0.5", O) == "unsettleable"


def test_unknown_market_is_unsettleable():
    assert grade_leg("Some Novel Market", "Yes", O) == "unsettleable"
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: ImportError — `cannot import name 'MatchOutcome'`

- [ ] **Step 3: Implement** — create `settle.py`:

```python
"""Settle a run's betslips against hand-entered match scores; tally trackers + backtest log.

Provider-agnostic core: grades only full-time score-derivable markets (others -> "unsettleable").
A results/stats API adapter can implement ResultsSource later; for now feed a scores CSV.

Usage:
    py settle.py output/run_YYYYMMDD_HHMM/betslips_*.txt --outcomes scores.csv
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# markets we cannot grade from a final score alone (stats / halves / combos)
UNSETTLEABLE = re.compile(
    r"corner|booking|card|shot|tackle|offside|foul|1st half|2nd half|halftime|half-time| & |odd/even",
    re.IGNORECASE)


@dataclass
class MatchOutcome:
    match: str
    home: int
    away: int
    ht_home: int | None = None
    ht_away: int | None = None


def _result(o: MatchOutcome) -> str:
    return "1" if o.home > o.away else ("2" if o.away > o.home else "Draw")


def _num(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def grade_leg(market: str, selection: str, o: MatchOutcome) -> str:
    """Grade one leg from the full-time score. Returns won|lost|void|unsettleable."""
    name = (market or "").strip()
    sel = (selection or "").strip()
    if UNSETTLEABLE.search(name):
        return "unsettleable"
    key = name.lower()
    total = o.home + o.away
    res = _result(o)

    if key == "1x2":
        return "won" if sel == res else "lost"

    if key == "total":
        line = _num(sel)
        if line is None:
            return "unsettleable"
        over = sel.lower().startswith("over")
        if total == line:
            return "void"
        hit = total > line if over else total < line
        return "won" if hit else "lost"

    if key == "both teams to score":
        both = o.home > 0 and o.away > 0
        yes = sel.lower().startswith("y")
        return "won" if both == yes else "lost"

    if key == "double chance":
        pair = {"1 or draw": {"1", "Draw"}, "1 or 2": {"1", "2"}, "draw or 2": {"Draw", "2"}}
        allowed = pair.get(sel.lower())
        if allowed is None:
            return "unsettleable"
        return "won" if res in allowed else "lost"

    if key == "correct score":
        m = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", sel)
        if not m:
            return "unsettleable"
        return "won" if (int(m.group(1)), int(m.group(2))) == (o.home, o.away) else "lost"

    if key == "multigoals":
        m = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*$", sel)
        if not m:
            return "unsettleable"
        lo, hi = int(m.group(1)), int(m.group(2))
        return "won" if lo <= total <= hi else "lost"

    if key == "draw no bet":
        if res == "Draw":
            return "void"
        return "won" if sel == res else "lost"

    if key == "handicap":
        m = re.match(r"\s*([12])\s*\(([-+]?\d+(?:\.\d+)?)\)", sel)
        if not m:
            return "unsettleable"
        team, hcap = m.group(1), float(m.group(2))
        home_adj = o.home + (hcap if team == "1" else 0.0)
        away_adj = o.away + (hcap if team == "2" else 0.0)
        if home_adj == away_adj:
            return "void"
        winner = "1" if home_adj > away_adj else "2"
        return "won" if winner == team else "lost"

    return "unsettleable"
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_grade_leg.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add settle.py tests/test_grade_leg.py
git commit -m "feat: settle.py grade_leg for full-time score markets"
```

---

### Task 2: Parsing + `grade_slip` + `settle_run`

**Files:**
- Modify: `settle.py` (add parsers, `grade_slip`, `settle_run` below `grade_leg`)
- Test: `tests/test_settle.py`

**Interfaces:**
- Consumes: Task 1 `MatchOutcome`, `grade_leg`.
- Produces:
  - `parse_betslips(text: str) -> list[dict]` — each slip `{"set","label","code","pred_win_pct","legs"}`, each leg `{"league","match","market","selection","odd"}`.
  - `read_outcomes_csv(text: str) -> dict[str, MatchOutcome]` keyed by match string.
  - `grade_slip(slip: dict, outcomes: dict) -> str` → `"won"|"lost"|"ungradeable"`.
  - `settle_run(slips: list[dict], outcomes: dict) -> dict` → `{"A": {"won","gradeable","total"}, "B": {...}, "verdicts": [(label, verdict, gradeable_legs, won_legs)]}`.
  Task 3 (CLI) consumes `settle_run`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_settle.py`:

```python
from settle import parse_betslips, read_outcomes_csv, grade_slip, settle_run, MatchOutcome

BETSLIPS = """Eljam3ia dual-set betslips - built 2026
window 1.25..1.5, 20 legs/slip

===== SET A: all-odds =====

BETSLIP A1  (2 legs, combined odds x2.00, win% 25)
   1. LigA - A vs. B - 1x2: 1 @ 1.40
   2. LigA - C vs. D - Total: Over 1.5 @ 1.40
  >> BOOKING CODE: AAA11

===== SET B: 7-category diversified =====

BETSLIP B1  (1 legs, combined odds x1.40, win% 71, families: corners x1)
   1. LigA - A vs. B - Total corners: Over 8.5 @ 1.40
  >> BOOKING CODE: BBB22
"""

OUTCOMES = "match,home,away\nA vs. B,2,1\nC vs. D,3,0\n"


def test_parse_betslips():
    slips = parse_betslips(BETSLIPS)
    assert [s["set"] for s in slips] == ["A", "B"]
    assert slips[0]["code"] == "AAA11" and slips[0]["pred_win_pct"] == 25.0
    assert len(slips[0]["legs"]) == 2
    assert slips[0]["legs"][0] == {"league": "LigA", "match": "A vs. B",
                                   "market": "1x2", "selection": "1", "odd": 1.40}


def test_read_outcomes_csv():
    out = read_outcomes_csv(OUTCOMES)
    assert out["A vs. B"] == MatchOutcome("A vs. B", 2, 1)


def test_grade_slip_won():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    assert grade_slip(slips[0], out) == "won"       # 1x2:1 won + Total Over1.5 (3>1.5) won


def test_grade_slip_ungradeable_on_stat_leg():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    assert grade_slip(slips[1], out) == "ungradeable"   # Total corners -> unsettleable


def test_grade_slip_ungradeable_when_outcome_missing():
    slips = parse_betslips(BETSLIPS)
    assert grade_slip(slips[0], {}) == "ungradeable"


def test_settle_run_tallies_trackers():
    slips = parse_betslips(BETSLIPS)
    out = read_outcomes_csv(OUTCOMES)
    r = settle_run(slips, out)
    assert r["A"] == {"won": 1, "gradeable": 1, "total": 1}
    assert r["B"] == {"won": 0, "gradeable": 0, "total": 1}
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_settle.py -v`
Expected: ImportError — `cannot import name 'parse_betslips'`

- [ ] **Step 3: Implement** — add to `settle.py` below `grade_leg`:

```python
_LEG = re.compile(r"^\s*\d+\.\s+(.*?) - (.*?) - (.*?): (.*?) @ ([\d.]+)\s*$")


def parse_betslips(text: str) -> list[dict]:
    """Parse a betslips_*.txt into slips with set/label/code/pred_win_pct/legs."""
    slips: list[dict] = []
    cur_set = None
    cur = None
    for line in text.splitlines():
        sm = re.match(r"=====\s*SET\s+([AB])\b", line)
        if sm:
            cur_set = sm.group(1)
            continue
        hm = re.match(r"BETSLIP\s+(\S+)\b.*?win%\s*([\d.eE+-]+)", line)
        if hm:
            cur = {"set": cur_set, "label": hm.group(1), "code": None,
                   "pred_win_pct": float(hm.group(2)), "legs": []}
            slips.append(cur)
            continue
        cm = re.match(r"\s*>> BOOKING CODE:\s*(\S+)", line)
        if cm and cur is not None:
            cur["code"] = cm.group(1)
            cur = None
            continue
        lm = _LEG.match(line)
        if lm and cur is not None:
            cur["legs"].append({"league": lm.group(1).strip(), "match": lm.group(2).strip(),
                                "market": lm.group(3).strip(), "selection": lm.group(4).strip(),
                                "odd": float(lm.group(5))})
    return slips


def read_outcomes_csv(text: str) -> dict[str, MatchOutcome]:
    """Read match,home,away[,ht_home,ht_away] rows into MatchOutcomes keyed by match."""
    out: dict[str, MatchOutcome] = {}
    for row in csv.reader(text.splitlines()):
        if not row or row[0].strip().lower() in ("match", ""):
            continue
        try:
            match = row[0].strip()
            home, away = int(row[1]), int(row[2])
            hth = int(row[3]) if len(row) > 3 and row[3].strip() != "" else None
            hta = int(row[4]) if len(row) > 4 and row[4].strip() != "" else None
        except (IndexError, ValueError):
            continue
        out[match] = MatchOutcome(match, home, away, hth, hta)
    return out


def grade_slip(slip: dict, outcomes: dict[str, MatchOutcome]) -> str:
    """won iff every non-void leg won; ungradeable if any leg unsettleable / outcome missing."""
    verdicts = []
    for leg in slip["legs"]:
        o = outcomes.get(leg["match"])
        if o is None:
            return "ungradeable"
        v = grade_leg(leg["market"], leg["selection"], o)
        if v == "unsettleable":
            return "ungradeable"
        verdicts.append(v)
    graded = [v for v in verdicts if v != "void"]
    if not graded:
        return "ungradeable"
    return "won" if all(v == "won" for v in graded) else "lost"


def settle_run(slips: list[dict], outcomes: dict[str, MatchOutcome]) -> dict:
    """Tally per-set trackers and per-slip verdicts."""
    tally = {"A": {"won": 0, "gradeable": 0, "total": 0},
             "B": {"won": 0, "gradeable": 0, "total": 0}}
    verdicts = []
    for slip in slips:
        st = slip["set"] if slip["set"] in tally else "A"
        tally[st]["total"] += 1
        verdict = grade_slip(slip, outcomes)
        won_legs = sum(1 for leg in slip["legs"]
                       if (o := outcomes.get(leg["match"])) is not None
                       and grade_leg(leg["market"], leg["selection"], o) == "won")
        if verdict != "ungradeable":
            tally[st]["gradeable"] += 1
            if verdict == "won":
                tally[st]["won"] += 1
        verdicts.append((slip["label"], verdict, len(slip["legs"]), won_legs))
    return {**tally, "verdicts": verdicts}
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_settle.py -v`
Expected: all pass.

- [ ] **Step 5: Full-suite regression**

Run: `py -m pytest tests/ -q`
Expected: all pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add settle.py tests/test_settle.py
git commit -m "feat: parse betslips, grade_slip, settle_run tallies"
```

---

### Task 3: CLI, backtest.csv, ResultsSource seam, docs

**Files:**
- Modify: `settle.py` (add `ResultsSource`/`NoResultsSource`, `append_backtest`, `main`), `README.md`

**Interfaces:**
- Consumes: Task 2 `parse_betslips`, `read_outcomes_csv`, `settle_run`.
- Produces: `main() -> int`; `append_backtest(path, run_dir, slips, result)`; `class ResultsSource(Protocol)`, `class NoResultsSource`.

- [ ] **Step 1: Add the seam + backtest writer + CLI** — append to `settle.py`:

```python
from typing import Protocol


class ResultsSource(Protocol):
    def outcomes_for(self, slips: list[dict]) -> dict[str, MatchOutcome]:
        ...


class NoResultsSource:
    """Placeholder until a football-data/API-Football adapter is wired in."""
    def outcomes_for(self, slips: list[dict]) -> dict[str, MatchOutcome]:
        return {}


def append_backtest(path: Path, run_dir: str, slips: list[dict], result: dict) -> None:
    by_label = {v[0]: v for v in result["verdicts"]}
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["settled_at", "run_dir", "set", "code", "legs",
                        "pred_win_pct", "verdict", "gradeable_legs", "won_legs"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for slip in slips:
            _, verdict, legs, won_legs = by_label[slip["label"]]
            w.writerow([now, run_dir, slip["set"], slip["code"], legs,
                        f"{slip['pred_win_pct']:g}", verdict, legs, won_legs])


def main() -> int:
    ap = argparse.ArgumentParser(description="Settle a run's betslips against match scores.")
    ap.add_argument("betslips", help="path to a betslips_*.txt")
    ap.add_argument("--outcomes", required=True, help="scores CSV: match,home,away[,ht_home,ht_away]")
    ap.add_argument("--backtest", default="output/backtest.csv", help="append per-slip rows here")
    args = ap.parse_args()

    bpath, opath = Path(args.betslips), Path(args.outcomes)
    if not bpath.exists():
        print(f"betslips file not found: {bpath}")
        return 1
    if not opath.exists():
        print(f"outcomes file not found: {opath}")
        return 1

    slips = parse_betslips(bpath.read_text(encoding="utf-8"))
    outcomes = read_outcomes_csv(opath.read_text(encoding="utf-8-sig"))
    result = settle_run(slips, outcomes)

    for st, cap in (("A", 50), ("B", 25)):
        t = result[st]
        print(f"SET {st}: {t['won']}/{t['gradeable']} gradeable won "
              f"-> tracker {min(t['won'], cap)}/{cap}  ({t['total']} slips total)")
    ungr = sum(1 for _l, v, _n, _w in result["verdicts"] if v == "ungradeable")
    if ungr:
        print(f"  ({ungr} slip(s) ungradeable — stat/half legs or missing scores)")

    backtest = Path(args.backtest)
    backtest.parent.mkdir(parents=True, exist_ok=True)
    append_backtest(backtest, bpath.parent.name, slips, result)
    print(f"Appended {len(slips)} rows to {backtest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Full-suite + offline CLI smoke** (no network)

Run: `py -m pytest tests/ -q` → all pass.
Create `scratch_scores.csv` with `match,home,away` plus a couple rows matching a real recent
`betslips_*.txt`'s match names, then:
Run: `py settle.py output/run_*/betslips_*.txt --outcomes scratch_scores.csv --backtest output/backtest.csv`
Expected: prints `SET A: .../... gradeable won -> tracker N/50`, `SET B: ...`, and appends rows; a
slip with all-scored legs grades, corner/stat-heavy SET B slips report ungradeable. Confirm
`output/backtest.csv` has the header + one row per slip.

- [ ] **Step 3: Docs.** In `README.md`, add a "Settlement / backtest" section: "`settle.py` grades a
run's betslips against a hand-entered scores CSV (`match,home,away[,ht_home,ht_away]`), prints the two
trackers (SET A 0..50, SET B 0..25 — winning slips), and appends per-slip rows to `output/backtest.csv`.
v1 grades full-time score markets (1x2, totals, BTTS, double chance, correct score, multigoals,
draw-no-bet, handicap); corners/cards/shots and half-split markets show as *ungradeable* until a stats
provider is added. Booking-code accumulators of 20 legs win ~never, so trackers read near zero — the
backtest is for measuring, not a target." Include the example command.

- [ ] **Step 4: Commit**

```bash
git add settle.py README.md
git commit -m "feat: settle.py CLI + backtest.csv + ResultsSource seam; docs"
```

---

## Self-Review

**Spec coverage:** `parse_betslips`/`read_outcomes_csv` → Task 2. `grade_leg` (8 score markets + unsettleable filter) → Task 1. `grade_slip`/`settle_run` (trackers) → Task 2. `backtest.csv` + CLI + `--outcomes` bridge → Task 3. `ResultsSource`/`NoResultsSource` seam → Task 3. Docs → Task 3. Out-of-scope items (external adapter, half/stat/combo markets) correctly absent. Covered.

**Placeholder scan:** none — all code complete; `scratch_scores.csv` in Task 3 Step 2 is a real file the implementer creates, not a gap.

**Type consistency:** `MatchOutcome` (Task 1) used by every later function. `grade_leg(market, selection, o) -> str` (Task 1) consumed by `grade_slip` (Task 2). Slip dict shape `{"set","label","code","pred_win_pct","legs":[{"league","match","market","selection","odd"}]}` produced by `parse_betslips` (Task 2), consumed by `grade_slip`/`settle_run` (Task 2) and `append_backtest`/`main` (Task 3). `settle_run` returns `{"A":{"won","gradeable","total"},"B":{...},"verdicts":[(label,verdict,legs,won_legs)]}` consumed by `main`/`append_backtest` (Task 3). Consistent.
