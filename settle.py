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
    name = str(market or "").strip()
    sel = str(selection or "").strip()
    if UNSETTLEABLE.search(name):
        return "unsettleable"
    key = name.lower()
    total = o.home + o.away
    res = _result(o)

    if key == "1x2":
        return "won" if sel == res else "lost"

    if key == "total":
        low = sel.lower()
        if low.startswith("over"):
            over = True
        elif low.startswith("under"):
            over = False
        else:
            return "unsettleable"
        line = _num(sel)
        if line is None:
            return "unsettleable"
        if total == line:
            return "void"
        hit = total > line if over else total < line
        return "won" if hit else "lost"

    if key == "both teams to score":
        low = sel.lower()
        if low.startswith("y"):
            yes = True
        elif low.startswith("n"):
            yes = False
        else:
            return "unsettleable"
        both = o.home > 0 and o.away > 0
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
        m = re.match(r"\s*([12])\s*\(([-+]?\d+(?:\.\d+)?)\)\s*$", sel)
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
            try:
                pred = float(hm.group(2))
            except ValueError:
                pred = 0.0  # informational only; keep the slip
            cur = {"set": cur_set, "label": hm.group(1), "code": None,
                   "pred_win_pct": pred, "legs": []}
            slips.append(cur)
            continue
        cm = re.match(r"\s*>> BOOKING CODE:\s*(\S+)", line)
        if cm and cur is not None:
            cur["code"] = cm.group(1)
            cur = None
            continue
        lm = _LEG.match(line)
        if lm and cur is not None:
            try:
                odd = float(lm.group(5))
            except ValueError:
                odd = 0.0  # grade_leg ignores the odd; keep the leg so the slip stays complete
            cur["legs"].append({"league": lm.group(1).strip(), "match": lm.group(2).strip(),
                                "market": lm.group(3).strip(), "selection": lm.group(4).strip(),
                                "odd": odd})
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


def _leg_verdicts(slip: dict, outcomes: dict[str, MatchOutcome]) -> list[str]:
    """Per-leg verdicts, one per leg. A leg whose match has no outcome is 'unsettleable'."""
    out = []
    for leg in slip["legs"]:
        o = outcomes.get(leg["match"])
        if o is None:
            out.append("unsettleable")
        else:
            out.append(grade_leg(leg["market"], leg["selection"], o))
    return out


def _verdict_from(leg_verdicts: list[str]) -> str:
    """ungradeable if any leg is unsettleable (or nothing is left after voids); else won iff all won."""
    if any(v == "unsettleable" for v in leg_verdicts):
        return "ungradeable"
    graded = [v for v in leg_verdicts if v != "void"]
    if not graded:
        return "ungradeable"
    return "won" if all(v == "won" for v in graded) else "lost"


def grade_slip(slip: dict, outcomes: dict[str, MatchOutcome]) -> str:
    """won iff every non-void leg won; ungradeable if any leg unsettleable / outcome missing."""
    return _verdict_from(_leg_verdicts(slip, outcomes))


def settle_run(slips: list[dict], outcomes: dict[str, MatchOutcome]) -> dict:
    """Tally per-set trackers and per-slip verdicts."""
    tally = {"A": {"won": 0, "gradeable": 0, "total": 0},
             "B": {"won": 0, "gradeable": 0, "total": 0}}
    verdicts = []
    for slip in slips:
        st = slip["set"] if slip["set"] in tally else "A"
        tally[st]["total"] += 1
        lv = _leg_verdicts(slip, outcomes)
        verdict = _verdict_from(lv)
        won_legs = sum(1 for v in lv if v == "won")
        if verdict != "ungradeable":
            tally[st]["gradeable"] += 1
            if verdict == "won":
                tally[st]["won"] += 1
        verdicts.append((slip["label"], verdict, len(slip["legs"]), won_legs))
    return {**tally, "verdicts": verdicts}
