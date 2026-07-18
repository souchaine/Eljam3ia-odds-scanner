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
from typing import Protocol

# markets we cannot grade from a final score alone (stat/event tokens only;
# halves and combos are handled explicitly by grade_leg's dispatch below)
UNSETTLEABLE = re.compile(r"corner|booking|card|shot|tackle|offside|foul", re.IGNORECASE)


@dataclass
class MatchOutcome:
    match: str
    home: int
    away: int
    ht_home: int | None = None
    ht_away: int | None = None


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


def _half_score(o: MatchOutcome, which: str) -> tuple[int, int] | None:
    """(home, away) goals in the given half, or None if half-time score is unknown."""
    if o.ht_home is None or o.ht_away is None:
        return None
    if which == "1st":
        return (o.ht_home, o.ht_away)
    return (o.home - o.ht_home, o.away - o.ht_away)   # 2nd half


def _score_key(name: str) -> str:
    """Strip decorations combo/half components can carry that _grade_score's bare keys don't
    expect: a trailing parenthetical annotation ("double chance (match)" -> "double chance") and
    a trailing bare line number ("total 5.5" -> "total"; the line is already read from `sel`)."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    s = re.sub(r"\s+\d+(?:\.\d+)?$", "", s).strip()
    return s


def _grade_on_half(o: MatchOutcome, which: str, core_market: str, sel: str) -> str:
    """Grade a core score market on the 1st/2nd-half score; unsettleable if ht unknown or a stat."""
    if UNSETTLEABLE.search(core_market):
        return "unsettleable"
    hs = _half_score(o, which)
    if hs is None:
        return "unsettleable"
    key = _score_key(core_market.strip().lower())
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


def grade_leg(market: str, selection: str, o: MatchOutcome) -> str:
    """Grade one leg from the full-time score. Returns won|lost|void|unsettleable."""
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
    return _grade_score(_score_key(low), sel, o.home, o.away)


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
            print(f"  ! skipping malformed outcomes row: {row}", file=sys.stderr)
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
    """Tally per-set trackers and per-slip verdicts.

    Each verdicts entry is (label, verdict, legs, won_legs, gradeable_legs).
    """
    tally = {"A": {"won": 0, "gradeable": 0, "total": 0},
             "B": {"won": 0, "gradeable": 0, "total": 0}}
    verdicts = []
    for slip in slips:
        st = slip["set"] if slip["set"] in tally else "A"
        tally[st]["total"] += 1
        lv = _leg_verdicts(slip, outcomes)
        verdict = _verdict_from(lv)
        won_legs = sum(1 for v in lv if v == "won")
        gradeable_legs = sum(1 for v in lv if v != "unsettleable")
        if verdict != "ungradeable":
            tally[st]["gradeable"] += 1
            if verdict == "won":
                tally[st]["won"] += 1
        verdicts.append((slip["label"], verdict, len(slip["legs"]), won_legs, gradeable_legs))
    return {**tally, "verdicts": verdicts}


class ResultsSource(Protocol):
    def outcomes_for(self, slips: list[dict]) -> dict[str, MatchOutcome]:
        ...


class NoResultsSource:
    """Placeholder until a football-data/API-Football adapter is wired in."""
    def outcomes_for(self, slips: list[dict]) -> dict[str, MatchOutcome]:
        return {}


def append_backtest(path: Path, run_dir: str, slips: list[dict], result: dict) -> None:
    """Append one row per slip. slips and result["verdicts"] are positionally aligned."""
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["settled_at", "run_dir", "set", "code", "legs",
                        "pred_win_pct", "verdict", "gradeable_legs", "won_legs"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for slip, (_label, verdict, legs, won_legs, gradeable_legs) in zip(slips, result["verdicts"]):
            w.writerow([now, run_dir, slip["set"], slip["code"], legs,
                        f"{slip['pred_win_pct']:g}", verdict, gradeable_legs, won_legs])


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):  # tolerate non-cp1252 names (e.g. 'ă') on Windows
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
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
    ungr = sum(1 for _l, v, _n, _w, _g in result["verdicts"] if v == "ungradeable")
    if ungr:
        print(f"  ({ungr} slip(s) ungradeable — stat/half legs or missing scores)")

    backtest = Path(args.backtest)
    backtest.parent.mkdir(parents=True, exist_ok=True)
    append_backtest(backtest, bpath.parent.name, slips, result)
    print(f"Appended {len(slips)} rows to {backtest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
