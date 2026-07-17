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
