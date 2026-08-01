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
from functools import lru_cache
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
        v = _multigoals_hit(sel, total)
        return v if v is not None else "unsettleable"

    if key in ("1 multigoals", "2 multigoals"):
        v = _multigoals_hit(sel, home if key.startswith("1") else away)
        return v if v is not None else "unsettleable"

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

    if key == "any clean sheet":
        y = re.fullmatch(r"\s*(yes|no)\s*", sel, re.IGNORECASE)
        if not y:
            return "unsettleable"
        anyclean = home == 0 or away == 0
        return "won" if anyclean == (y.group(1).lower() == "yes") else "lost"

    return "unsettleable"


# family classification for per-family hit-rate reporting. Order matters: the first match wins.
#   1. stat/player families are checked BEFORE the period families, so a stat market that also
#      names a period -- "1st half corners" -- reports as "corners", not "1st half".
#   2. multigoals is checked AFTER the period families, so a period-prefixed market --
#      "1st half - multigoals" -- reports as "1st half", not "multigoals".
#   3. htft is checked BEFORE combo, so a market that is itself a combo of an HT/FT leg with
#      something else -- "Halftime/fulltime & total X" -- files as "htft", while an ordinary
#      combo that doesn't involve HT/FT -- "Double chance & total X" -- files as "combo".
_FAMILIES = [
    # `goalscorer` (bare) covers both "Goalscorer - <player>" and "Goalscorer OR the substitute to
    # score - <player>"; no non-player market in the real vocabulary contains the token (goal-timing
    # markets are named "First goal" / "Last goal").
    ("player",     r"shots?\s*-|shots on goal\s*-|saves goalkeeper|to score or assist|goalscorer|"
                   r"passes\s*-"),
    ("corners",    r"corner"),
    ("cards",      r"booking|card"),
    ("stat-other", r"\bshots?\b|tackle|offside|foul|penalty in the match|scoring type"),
    ("interval",   r"\d+\s*minutes\s*-"),
    ("htft",       r"half\s*time\s*/\s*full\s*time|dc\s*halftime"),
    ("combo",      r" & "),
    ("or-combo",   r"\bor\b"),
    ("both halves", r"1st\s*/\s*2nd\s*half|both halves"),
    ("1st half",   r"1st\s*half|first\s*half"),
    ("2nd half",   r"2nd\s*half|second\s*half"),
    ("multigoals", r"multigoals"),
    ("main",       r"^(1x2|total|both teams to score|double chance|correct score|"
                   r"draw no bet|handicap|handicap 1x2|odd/even|"
                   r"[12] (total|clean sheet|odd/even|to score|exact goals))"),
]


def _market_family(market: str) -> str:
    """Classify a market into a reporting family. Unanticipated markets land in 'other'."""
    name = str(market or "").strip().lower()
    for fam, pat in _FAMILIES:
        if re.search(pat, name):
            return fam
    return "other"


def _half_score(o: MatchOutcome, which: str) -> tuple[int, int] | None:
    """(home, away) goals in the given half, or None if half-time score is unknown."""
    if o.ht_home is None or o.ht_away is None:
        return None
    if which == "1st":
        return (o.ht_home, o.ht_away)
    return (o.home - o.ht_home, o.away - o.ht_away)   # 2nd half


def _grade_htft(o: MatchOutcome, sel: str, dc: bool | tuple[bool, bool] = False) -> str:
    """Grade Halftime/fulltime ("1/1"), DC Halftime/DC Fulltime ("X2/X2"), or a mixed form like
    DC Halftime/1X2 Fulltime ("1X/1").

    `dc` is the double-chance flag PER POSITION: pass a bool to apply it to both picks, or a
    (ht_dc, ft_dc) pair to interpret the two positions independently -- a DC pick resolves by
    membership in a _DC_PAIRS set ("1X" = {1, Draw}); a plain pick resolves by 1X2 equality.

    Needs BOTH halves, so it cannot live in _grade_score. FT is cumulative (Gate 3).
    """
    if o.ht_home is None or o.ht_away is None:
        return "unsettleable"
    parts = [p.strip() for p in sel.split("/")]
    if len(parts) != 2:
        return "unsettleable"
    dc_flags = tuple(dc) if isinstance(dc, (list, tuple)) else (dc, dc)
    if len(dc_flags) != 2:
        return "unsettleable"
    ht_res = "1" if o.ht_home > o.ht_away else ("2" if o.ht_away > o.ht_home else "Draw")
    ft_res = "1" if o.home > o.away else ("2" if o.away > o.home else "Draw")
    # Validate BOTH picks first -- resolve each to its allowed result(s) before comparing either
    # against the scoreline. Deciding ("lost") on the first pick before the second is validated
    # made the same unparseable selection grade "lost" or "unsettleable" depending on the score
    # (governing principle: never emit a verdict while a sibling token is unparsed).
    resolved = []   # per position: a set of allowed results to test membership against
    for pick, is_dc in zip(parts, dc_flags):
        if is_dc:
            allowed = _DC_PAIRS.get(pick.lower())
        else:
            one = {"1": "1", "2": "2", "x": "Draw", "draw": "Draw"}.get(pick.lower())
            allowed = {one} if one is not None else None
        if allowed is None:
            return "unsettleable"
        resolved.append(allowed)
    hits = [res in allowed for allowed, res in zip(resolved, (ht_res, ft_res))]
    return "won" if all(hits) else "lost"


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


def _grade_both_halves(low: str, sel: str, o: MatchOutcome) -> str:
    """Grade a score-derivable "both halves ..." market. All observed forms take a Yes/No
    selection and need BOTH half scores; returns unsettleable if the half-time score is unknown,
    the selection isn't Yes/No, or the market isn't a recognized both-halves form.

    Forms:
      - "both halves over|under N": each half's total is over/under the line.
      - "[12] to score in both halves": the team scored (>=1) in each half.
      - "[12] to win both halves": the team won each half outright.
    """
    y = re.fullmatch(r"\s*(yes|no)\s*", sel, re.IGNORECASE)
    if not y:
        return "unsettleable"
    yes = y.group(1).lower() == "yes"
    h1, h2 = _half_score(o, "1st"), _half_score(o, "2nd")
    if h1 is None or h2 is None:
        return "unsettleable"

    m = re.fullmatch(r"both\s+halves\s+(over|under)\s+(\d+(?:\.\d+)?)", low)
    if m:
        over = m.group(1) == "over"
        line = float(m.group(2))
        t1, t2 = h1[0] + h1[1], h2[0] + h2[1]
        if t1 == line or t2 == line:      # push on a half inside a compound -> don't guess
            return "unsettleable"
        cond = (t1 > line and t2 > line) if over else (t1 < line and t2 < line)
        return "won" if cond == yes else "lost"

    m = re.fullmatch(r"([12])\s+to\s+score\s+in\s+both\s+halves", low)
    if m:
        i = 0 if m.group(1) == "1" else 1
        cond = h1[i] >= 1 and h2[i] >= 1
        return "won" if cond == yes else "lost"

    m = re.fullmatch(r"([12])\s+to\s+win\s+both\s+halves", low)
    if m:
        if m.group(1) == "1":
            cond = h1[0] > h1[1] and h2[0] > h2[1]
        else:
            cond = h1[1] > h1[0] and h2[1] > h2[0]
        return "won" if cond == yes else "lost"

    return "unsettleable"


def _combine(verdicts: list[str]) -> str:
    """Combo precedence: unsettleable > lost > void > won."""
    if any(v == "unsettleable" for v in verdicts):
        return "unsettleable"
    if any(v == "lost" for v in verdicts):
        return "lost"
    if any(v == "void" for v in verdicts):
        return "void"
    return "won"


_OR_SPLIT = re.compile(r"\s+or\s+", re.IGNORECASE)


def _take(tokens: list[str], pattern: str) -> str | None:
    """Pop the first selection token matching pattern (type-binding, not positional)."""
    for i, t in enumerate(tokens):
        if re.fullmatch(pattern, t.strip(), re.IGNORECASE):
            return tokens.pop(i).strip()
    return None


# Known OR-component forms, matched with re.fullmatch (whitelist, not substring/prefix) so that
# any unanticipated variant -- e.g. "any clean sheet in the 1st half", "both team to score in
# both halves" -- falls through to unsettleable instead of being graded on the full-time score.
# The provider writes both "Both team to score" (singular) and "both teams to score" (plural).
_OR_BOTH_TEAMS = re.compile(r"both teams?\s+to\s+score")
_OR_ANY_CLEAN_SHEET = re.compile(r"any\s+clean\s+sheet")
_OR_TOTAL = re.compile(r"total\s+\d+(?:\.\d+)?")


def _or_component_verdict(part: str, o: MatchOutcome, tokens: list[str], bare: bool) -> str:
    """Grade one OR component, consuming the selection token that matches it BY TYPE (not
    position -- see the compound-OR hazard: selection order can be reversed vs the market name).

    `bare` is True when the overall selection was a plain "Yes"/"No" wrapper (the simple-OR
    family -- the market name alone carries both legs, so a component with no matching token
    just evaluates its own condition as-is). When `bare` is False (the compound-OR family) every
    token-needing component MUST find its own token; a miss is unsettleable, never a silent guess.

    NOTE: the type-classification here (the _OR_BOTH_TEAMS / _OR_ANY_CLEAN_SHEET / _OR_TOTAL
    fullmatch checks) is mirrored in `_or_component_pattern` below, which needs to know the SAME
    token shape each component would consume in order to catch same-type ambiguity before any
    token is consumed. If a new component type is added here, add a matching branch there too --
    otherwise the ambiguity check silently falls through to None ("no collision risk") for the new
    type, reopening a positional-guess hazard.
    """
    p = part.strip().lower()
    if p in ("1", "2", "draw", "x"):                       # bare result token
        return _grade_score("1x2", {"x": "Draw", "draw": "Draw"}.get(p, p), o.home, o.away)
    if re.fullmatch(r"(over|under)\s+\d+(?:\.\d+)?", p):   # line carried in the market name
        return _grade_score("total", p, o.home, o.away)
    if _OR_ANY_CLEAN_SHEET.fullmatch(p):
        tok = _take(tokens, r"yes|no")
        if tok is None:
            if not bare:
                return "unsettleable"
            tok = "Yes"
        return _grade_score("any clean sheet", tok, o.home, o.away)
    if _OR_BOTH_TEAMS.fullmatch(p):                        # both team(s) to score
        tok = _take(tokens, r"yes|no")
        if tok is None:
            if not bare:
                return "unsettleable"
            tok = "Yes"
        return _grade_score("both teams to score", tok, o.home, o.away)
    if _OR_TOTAL.fullmatch(p):                             # "Total 2.5" -> line comes from a token
        tok = _take(tokens, r"(over|under)\s+\d+(?:\.\d+)?")
        return _grade_score("total", tok, o.home, o.away) if tok else "unsettleable"
    return "unsettleable"


def _or_component_pattern(part: str) -> str | None:
    """The token pattern this OR component would consume via `_take`, or None if it's
    self-contained (a bare 1x2 result, or a total line embedded in the market name itself).

    Used by `_grade_or` to detect two components competing for the SAME token shape -- e.g. two
    yes/no components -- before any token is actually consumed. When that happens there is no
    type signal to bind by, `_take` would fall back to market order, and the observed provider
    grammar reverses selection order relative to the market name, so a positional guess is likely
    wrong. Per the governing principle (a mis-graded leg is worse than an ungraded one), that
    ambiguity must be caught and returned as unsettleable rather than silently guessed.

    NOTE: this duplicates `_or_component_verdict`'s type-classification (same fullmatch checks,
    same hardcoded pattern literals) because it needs to know a component's token shape WITHOUT
    consuming a token. The two are kept in sync by hand -- if a new component type is added to
    `_or_component_verdict`, add a matching branch here too, or the ambiguity check will silently
    fail to classify it (falls through to None = "no collision risk").
    """
    p = part.strip().lower()
    if p in ("1", "2", "draw", "x"):
        return None
    if re.fullmatch(r"(over|under)\s+\d+(?:\.\d+)?", p):
        return None
    if _OR_ANY_CLEAN_SHEET.fullmatch(p) or _OR_BOTH_TEAMS.fullmatch(p):
        return r"yes|no"
    if _OR_TOTAL.fullmatch(p):
        return r"(over|under)\s+\d+(?:\.\d+)?"
    return None


_HALF_PREFIX = re.compile(r"(1st|2nd|first|second)\s*half", re.IGNORECASE)


def _grade_or(market: str, sel: str, o: MatchOutcome) -> str:
    """Grade an "A or B" market. Selection is "Yes"/"No" (simple-OR), or per-component tokens
    bound by type, not position (compound-OR)."""
    if _HALF_PREFIX.match(market.strip()):
        return "unsettleable"     # half-scoped OR markets are not in scope; don't grade on FT
    if UNSETTLEABLE.search(market):
        return "unsettleable"
    parts = [p for p in _OR_SPLIT.split(market.strip()) if p.strip()]
    if len(parts) != 2:
        return "unsettleable"
    # NOTE: there used to be a second, per-component _HALF_PREFIX check here, because the
    # whole-market check above only anchors at position 0 and so misses a half-scope sitting on
    # the SECOND component ("1 or 1st half both teams to score"). It's no longer needed: since
    # _or_component_verdict/_or_component_pattern now WHITELIST known component forms via
    # re.fullmatch (Fix 3) instead of substring-matching, a half-prefixed fragment like "1st half
    # both teams to score" can no longer fullmatch _OR_BOTH_TEAMS (or any other known form) --
    # the leading "1st half " text makes the fullmatch fail, so the component falls through to
    # "unsettleable" on its own and the whole OR market is correctly rejected without help.
    s = sel.strip()
    yesno = re.fullmatch(r"(yes|no)", s, re.IGNORECASE)
    if yesno:
        tokens: list[str] = []
    else:
        tokens = [t for t in _OR_SPLIT.split(s) if t.strip()]
        if len(tokens) != len(parts):          # malformed: neither a bare Yes/No nor one token
            return "unsettleable"              # per component -- don't guess
        patterns = [pat for pat in (_or_component_pattern(p) for p in parts) if pat is not None]
        if len(patterns) != len(set(patterns)):
            return "unsettleable"              # two components compete for the same token shape
    verdicts = [_or_component_verdict(p, o, tokens, bare=bool(yesno)) for p in parts]
    if tokens:                    # a selection token bound to nothing -> don't guess
        return "unsettleable"
    if any(v == "unsettleable" for v in verdicts):
        return "unsettleable"
    if any(v == "void" for v in verdicts):
        return "unsettleable"     # push inside an OR -- settlement rule not defined yet
    hit = any(v == "won" for v in verdicts)
    want_yes = yesno.group(1).lower() == "yes" if yesno else True
    return "won" if hit == want_yes else "lost"


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
        # a half prefix on the first component applies to the whole combo: distribute it onto
        # later components that don't already carry their own half designation (fix for combos
        # like "2nd half - double chance & both teams to score" grading the tail on full time)
        pref = re.match(r"(1st|2nd|first|second)\s*half\s*-\s*", mparts[0], re.IGNORECASE)
        if pref:
            head = mparts[0][:pref.end()]                      # e.g. "2nd half - "
            mparts = [mparts[0]] + [
                mp if re.match(r"(1st|2nd|first|second)\s*half", mp, re.IGNORECASE) else head + mp
                for mp in mparts[1:]
            ]
        return _combine([grade_leg(mp, sp, o) for mp, sp in zip(mparts, sparts)])

    # Halftime/fulltime markets, with an optional per-side "DC"/"1X2" qualifier. The qualifier is
    # read per position so mixed forms ("DC Halftime/ 1X2 Fulltime") interpret the HT pick as a
    # double chance and the FT pick as a plain 1X2, and vice-versa. A missing/"1X2" qualifier is a
    # plain pick; "DC" is a double-chance pick.
    htft_m = re.fullmatch(
        r"\s*(dc|1x2)?\s*half\s*time\s*/\s*(dc|1x2)?\s*full\s*time\s*", low)
    if htft_m:
        return _grade_htft(o, sel, dc=(htft_m.group(1) == "dc", htft_m.group(2) == "dc"))

    # "1st/2nd half both teams to score": selection "X/Y" = 1st-half BTTS / 2nd-half BTTS
    if low == "1st/2nd half both teams to score":
        parts = [p.strip() for p in sel.split("/")]
        if len(parts) != 2:
            return "unsettleable"
        v1 = _grade_on_half(o, "1st", "both teams to score", parts[0])
        v2 = _grade_on_half(o, "2nd", "both teams to score", parts[1])
        return _combine([v1, v2])

    # "both halves ..." markets are score-derivable from BOTH half scores (over/under a line in
    # each half, a team scoring in each half, or winning each half). Every observed form carries
    # "both halves" in its name; unrecognized both-halves forms fall through to unsettleable.
    if "both halves" in low:
        return _grade_both_halves(low, sel, o)

    # "A or B" markets (simple-OR: sel is Yes/No; compound-OR: sel carries per-component tokens,
    # possibly in reversed order vs the market name -- _grade_or binds them by type). The combo
    # branch above (" & " in low) already returns unconditionally, so " & " can never reach here.
    if re.search(r"\s+or\s+", low):
        return _grade_or(name, sel, o)

    # half markets: "1st half - <core>" / "2nd half - <core>" (or without the dash, inside combos);
    # also accepts word forms "First half" / "Second half" seen in real data
    hm = re.match(r"(1st|2nd|first|second)\s*half\s*-?\s*(.*)$", low)
    if hm and hm.group(2):
        which = {"first": "1st", "second": "2nd"}.get(hm.group(1), hm.group(1))
        return _grade_on_half(o, which, hm.group(2).strip(), sel)

    if UNSETTLEABLE.search(name):
        return "unsettleable"
    return _grade_score(_score_key(low), sel, o.home, o.away)


# --- build-time settleability gate -------------------------------------------------------------
#
# Every full-time scoreline in 0-4 x 0-4, paired with every valid half-time split (ht <= ft).
#
# LOAD-BEARING INVARIANT: *settlement input always carries half-time scores.* Half, HT/FT and
# both-halves markets return "unsettleable" when ht_home/ht_away are missing, so every
# representative outcome supplies them. If a settlement source ever stops providing half-time
# scores, this gate becomes wrong in the dangerous direction -- it would admit markets that cannot
# actually be graded, and slips built from them would settle as ungradeable.
REPRESENTATIVE_OUTCOMES = tuple(
    MatchOutcome("probe", home, away, ht_home, ht_away)
    for home in range(5) for away in range(5)
    for ht_home in range(home + 1) for ht_away in range(away + 1)
)


@lru_cache(maxsize=None)
def is_settleable(market, selection) -> bool:
    """May this (market, selection) be put on a betslip? True iff grade_leg yields a REAL verdict
    (won|lost|void) for EVERY representative outcome -- never "unsettleable", never raising.

    Stricter than "gradeable on some scoreline" on purpose: the builder cannot know the outcome, so
    a market that grades on most scorelines but goes unsettleable on others (e.g. "Both halves over
    2", where an integer line landing exactly on a half's total is a push we refuse to guess) must
    be excluded. A market that returns "void" is fine -- a push is a real settlement outcome, not a
    failure to grade -- so "Total"/"Over 2" stays eligible.
    """
    return all(grade_leg(market, selection, o) != "unsettleable" for o in REPRESENTATIVE_OUTCOMES)


@lru_cache(maxsize=None)
def is_void_capable(market, selection) -> bool:
    """True if some representative outcome pushes this leg (verdict "void").

    Settlement DROPS a void leg (see _verdict_from), so a slip carrying one can settle shorter than
    it was built -- the builder annotates these so the displayed win% and the settled result agree.
    """
    return any(grade_leg(market, selection, o) == "void" for o in REPRESENTATIVE_OUTCOMES)


_LEG = re.compile(r"^\s*\d+\.\s+(.*?) - (.*?) - (.*?): (.*?) @ ([\d.]+)\s*$")


def parse_betslips(text: str) -> list[dict]:
    """Parse a betslips_*.txt into slips with set/label/code/pred_win_pct_floor/legs."""
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
                   "pred_win_pct_floor": pred, "legs": []}
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
        # A row with a match name but NO full-time score is a deliberate "not filled in" -- the
        # match was postponed, or its result could not be verified and guessing is forbidden. That
        # is a normal, expected state, so it is skipped QUIETLY. A row whose values are present but
        # unparseable is a genuine data error and must still shout.
        if len(row) < 3 or (row[1].strip() == "" and row[2].strip() == ""):
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


def validate_outcomes(slips: list[dict], outcomes: dict[str, MatchOutcome]) -> dict:
    """Check a hand-filled scores CSV against a betslips file BEFORE settling anything.

    Settlement is forgiving by design -- an unmatched name simply yields `unsettleable` legs -- which
    means a hand-entry typo does not raise, it just silently shrinks the sample. On a CSV typed off a
    scoreboard that is the likeliest failure mode, so it gets named here while it is still fixable.

    Reports:
      unjoined_rows   score rows whose match name matches NO leg (almost always a typo)
      missing_outcomes matches on slips with no score row at all (unfilled / postponed)
      impossible      half-time exceeds full-time -- goals do not un-score; a transposition typo
      ft_without_ht   rows with a full-time score but no half-time, plus what that costs

    `ok` is False if anything would corrupt or silently shrink the settlement. A blank HT is a
    deliberate, supported choice (never guess a score), so it is reported but does NOT block.
    """
    leg_matches = [leg["match"] for s in slips for leg in s["legs"]]
    on_slips = set(leg_matches)
    unjoined = sorted(set(outcomes) - on_slips)
    missing = sorted(on_slips - set(outcomes))
    impossible, ft_no_ht = [], []
    for name, o in outcomes.items():
        if o.ht_home is None or o.ht_away is None:
            if name in on_slips:
                ft_no_ht.append(name)
        elif o.ht_home > o.home or o.ht_away > o.away:
            impossible.append(name)

    # what each problem actually costs, in legs
    lost_missing = sum(1 for m in leg_matches if m in set(missing))
    no_ht = set(ft_no_ht)
    lost_ht = 0
    for s in slips:
        for leg in s["legs"]:
            if leg["match"] in no_ht:
                probe = MatchOutcome(leg["match"], 2, 1)          # FT only, no half-time
                if grade_leg(leg["market"], leg["selection"], probe) == "unsettleable":
                    lost_ht += 1
    return {"unjoined_rows": unjoined,
            "legs_affected_by_unjoined": 0,      # by definition they join nothing
            "missing_outcomes": missing,
            "legs_ungradeable_from_missing": lost_missing,
            "impossible": sorted(impossible),
            "ft_without_ht": sorted(ft_no_ht),
            "legs_lost_to_missing_ht": lost_ht,
            "ok": not (unjoined or missing or impossible)}


def _leg_record(match: str, market: str, selection: str, odd,
                outcomes: dict[str, MatchOutcome]) -> dict:
    """Grade ONE leg into a record. The single place a leg verdict is produced.

    Both slip settlement (settle_run) and full-pool settlement (settle_pool) go through here, so the
    same (match, market, selection) cannot grade differently depending on which file it lands in.
    """
    o = outcomes.get(match)
    verdict = "unsettleable" if o is None else grade_leg(market, selection, o)
    return {"match": match, "family": _market_family(market), "market": market,
            "selection": selection, "odd": odd, "verdict": verdict}


_MATRIX_CELL = re.compile(r"^\s*(.+?)\s*@\s*([\d.]+)\s*$")


def read_odds_matrix(text: str) -> list[dict]:
    """Every selection cell of an odds_matrix_*.csv as {league, match, market, selection, odd}.

    Market names are the column headers; each populated cell is "<selection> @ <odd>".
    """
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    header = rows[0]
    try:
        mcol, lcol = header.index("Match"), header.index("League")
    except ValueError:
        return []
    kcol = header.index("Kickoff (UTC)") if "Kickoff (UTC)" in header else None
    skip = {mcol, lcol}
    for name in ("Kickoff (UTC)", "Event ID"):
        if name in header:
            skip.add(header.index(name))
    out: list[dict] = []
    for row in rows[1:]:
        if len(row) <= mcol or not row[mcol].strip():
            continue
        for ci, cell in enumerate(row):
            if ci in skip or ci >= len(header) or not cell.strip():
                continue
            market = header[ci].strip()
            m = _MATRIX_CELL.match(cell)
            if not market or not m:
                continue
            try:
                odd = float(m.group(2))
            except ValueError:
                continue
            out.append({"league": row[lcol].strip(), "match": row[mcol].strip(),
                        "market": market, "selection": m.group(1).strip(), "odd": odd,
                        "kickoff": row[kcol].strip() if kcol is not None and len(row) > kcol else ""})
    return out


def exclude_inplay(selections: list[dict], scrape_finished_utc: str | None) -> list[dict]:
    """Keep only selections whose fixture kicked off AFTER the scrape finished.

    Odds scraped once a match is under way are IN-PLAY prices: they encode information about a game
    already in progress, so their implied probability is not a pre-match prediction and pooling them
    into calibration injects post-hoc information into a measurement meant to score forecasts.

    Real case: run_20260724_1812 ran for 26 hours (17:12Z Jul 24 -> 19:08Z Jul 25) while its 548
    fixtures kicked off between 17:15Z and 16:00Z the next day -- the scan window spans the whole
    fixture list, so which rows are pre-match is unknowable and all of them must go.

    Conservative by construction: a fixture with an unparseable/absent kickoff, or a matrix with no
    recorded finish time, cannot be SHOWN to be pre-match, so it is excluded rather than assumed
    clean.
    """
    end = _parse_utc(scrape_finished_utc)
    if end is None:
        return []
    kept = []
    for s in selections:
        ko = _parse_utc(s.get("kickoff"))
        if ko is not None and ko > end:
            kept.append(s)
    return kept


def _parse_utc(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def settle_pool(selections: list[dict], outcomes: dict[str, MatchOutcome]) -> list[dict]:
    """Grade every GATE-ELIGIBLE selection on a slate -- the full observable sample, not just the
    ~100 legs that happened to be put on slips.

    Slip structure exists for betting and is irrelevant to calibration, which only needs
    (market, selection, odd, verdict). Gate-ineligible selections are dropped rather than logged as
    unsettleable: they were never observable, so they are not missing data.
    """
    return [_leg_record(s["match"], s["market"], s["selection"], s["odd"], outcomes)
            for s in selections
            if is_settleable(s.get("market"), s.get("selection"))]


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

    Per-family `n` counts every leg occurrence (legs repeated across slips are counted once per
    occurrence, so it's pseudo-replicated as an independent-sample size). `distinct` additionally
    tracks the number of unique (match, market, selection) triples per family, so the hit-rate
    table can show how much of `n` is actually independent signal.
    """
    tally = {"A": {"won": 0, "gradeable": 0, "total": 0},
             "B": {"won": 0, "gradeable": 0, "total": 0}}
    verdicts = []
    families: dict[str, dict[str, int]] = {}
    family_legs: dict[str, set[tuple[str, str, str]]] = {}
    leg_records: list[dict] = []       # one per leg, for the per-leg backtest log / calibration
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
        for leg, v in zip(slip["legs"], lv):
            # built through the SAME _leg_record used by settle_pool, so a slipped leg and the same
            # selection observed in the pool can never carry different verdicts
            rec = _leg_record(leg["match"], leg["market"], leg["selection"], leg["odd"], outcomes)
            fam = rec["family"]
            f = families.setdefault(fam, {"n": 0, "gradeable": 0, "won": 0, "distinct": 0})
            f["n"] += 1
            if v != "unsettleable":
                f["gradeable"] += 1
                if v == "won":
                    f["won"] += 1
            family_legs.setdefault(fam, set()).add((leg["match"], leg["market"], leg["selection"]))
            leg_records.append(rec)
    for fam, legs in family_legs.items():
        families[fam]["distinct"] = len(legs)
    return {**tally, "verdicts": verdicts, "families": families, "leg_records": leg_records}


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
                        "pred_win_pct_floor", "verdict", "gradeable_legs", "won_legs"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for slip, (_label, verdict, legs, won_legs, gradeable_legs) in zip(slips, result["verdicts"]):
            w.writerow([now, run_dir, slip["set"], slip["code"], legs,
                        f"{slip['pred_win_pct_floor']:g}", verdict, gradeable_legs, won_legs])


def append_backtest_legs(path: Path, run_dir: str, result: dict) -> None:
    """Append one row per graded leg to a per-leg backtest log (family + odd + verdict), the input
    calibrate.py needs to compare each family's real hit rate against the odds' implied rate.

    Records come straight from settle_run's leg_records, which are built from the same leg verdicts
    as the per-family tallies, so this log can never disagree with the in-run per-family report.
    """
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["settled_at", "run_dir", "match", "family",
                        "market", "selection", "odd", "verdict"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in result["leg_records"]:
            w.writerow([now, run_dir, r["match"], r["family"],
                        r["market"], r["selection"], f"{r['odd']:g}", r["verdict"]])


def append_backtest_pool_legs(path: Path, run_dir: str, records: list[dict]) -> None:
    """Append full-gated-pool observations to their OWN log.

    CONTAMINATION GUARD -- a slipped leg is a BET; a pool leg is an OBSERVATION. Pooling them would
    corrupt any analysis that assumes one row = one placed bet. Two defences: (1) this is a separate
    file from backtest_legs.csv, and (2) it carries a `source` column that the slip schema does NOT,
    so a naive concatenation yields mismatched headers and fails loudly instead of silently
    averaging bets together with observations.
    """
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["settled_at", "run_dir", "source", "match", "family",
                        "market", "selection", "odd", "verdict"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in records:
            w.writerow([now, run_dir, "pool", r["match"], r["family"],
                        r["market"], r["selection"], f"{r['odd']:g}", r["verdict"]])


def tracker_lines(result: dict) -> list[str]:
    """Per-set slip tracker lines. Diagnostic only -- the per-family LEG table is the measurement.

    Only sets that actually contain slips are reported: SET A no longer exists in the builder, so a
    current run would otherwise print a permanently-0/0 SET A line. A legacy 20-leg file that does
    carry SET A slips still reports it.
    """
    lines = ["Slip trackers (diagnostic only — the per-family leg table below is the measurement):"]
    for st, cap in (("A", 50), ("B", 25)):
        t = result[st]
        if not t["total"]:
            continue
        lines.append(f"SET {st}: {t['won']}/{t['gradeable']} gradeable won "
                     f"-> tracker {min(t['won'], cap)}/{cap}  ({t['total']} slips total)")
    ungr = sum(1 for _l, v, _n, _w, _g in result["verdicts"] if v == "ungradeable")
    if ungr:
        lines.append(f"  ({ungr} slip(s) ungradeable — stat/half legs or missing scores)")
    return lines


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
    ap.add_argument("--backtest-legs", default="output/backtest_legs.csv",
                    help="append per-leg rows here (family/odd/verdict; input for calibrate.py)")
    ap.add_argument("--check", action="store_true",
                    help="validate the scores CSV against the betslips and STOP -- writes nothing")
    ap.add_argument("--pool", default=None,
                    help="odds_matrix_*.csv for this run: ALSO settle every gate-eligible selection "
                         "on the slate (~19x the slipped legs) into --backtest-pool-legs")
    ap.add_argument("--backtest-pool-legs", default="output/backtest_pool_legs.csv",
                    dest="backtest_pool_legs",
                    help="append full-pool OBSERVATIONS here (separate from slip BETS)")
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
    # Pre-flight: a hand-filled CSV fails silently (a typo'd name just yields unsettleable legs),
    # so name the problems before anything is written.
    v = validate_outcomes(slips, outcomes)
    if v["unjoined_rows"]:
        print(f"  ! {len(v['unjoined_rows'])} score row(s) match NO leg (likely a typo):")
        for m in v["unjoined_rows"]:
            print(f"      {m!r}")
    if v["missing_outcomes"]:
        print(f"  ! {len(v['missing_outcomes'])} match(es) on the slips have no score row "
              f"-> {v['legs_ungradeable_from_missing']} leg(s) ungradeable:")
        for m in v["missing_outcomes"]:
            print(f"      {m!r}")
    if v["impossible"]:
        print(f"  !! {len(v['impossible'])} match(es) have a half-time score ABOVE full-time "
              f"(impossible -- check for a transposition):")
        for m in v["impossible"]:
            print(f"      {m!r}")
    if v["ft_without_ht"]:
        print(f"  - {len(v['ft_without_ht'])} match(es) have full-time but no half-time "
              f"-> {v['legs_lost_to_missing_ht']} half-dependent leg(s) will not grade "
              f"(this is the supported 'never guess' path)")
    if args.check:
        print("\n--check: nothing written." +
              ("  Looks clean." if v["ok"] else "  Fix the above first."))
        return 0 if v["ok"] else 1
    if not v["ok"]:
        print("\n  (settling anyway -- the above legs simply will not grade)")

    result = settle_run(slips, outcomes)

    for line in tracker_lines(result):
        print(line)

    print("\nPer-family leg hit rate (no blended aggregate — the gradeable subset is a biased sample):")
    print(f"  {'family':<12} {'n':>5} {'distinct':>8} {'gradeable':>10} {'won':>5}  hit%")
    for fam in sorted(result["families"], key=lambda k: -result["families"][k]["n"]):
        f = result["families"][fam]
        hit = f"{100 * f['won'] / f['gradeable']:.0f}%" if f["gradeable"] else "  -"
        print(f"  {fam:<12} {f['n']:>5} {f['distinct']:>8} {f['gradeable']:>10} {f['won']:>5}  {hit:>4}")

    backtest = Path(args.backtest)
    backtest.parent.mkdir(parents=True, exist_ok=True)
    append_backtest(backtest, bpath.parent.name, slips, result)
    print(f"Appended {len(slips)} rows to {backtest}")

    if args.pool:
        ppath = Path(args.pool)
        if not ppath.exists():
            print(f"pool matrix not found: {ppath}")
            return 1
        precs = settle_pool(read_odds_matrix(ppath.read_text(encoding="utf-8-sig")), outcomes)
        pout = Path(args.backtest_pool_legs)
        pout.parent.mkdir(parents=True, exist_ok=True)
        append_backtest_pool_legs(pout, bpath.parent.name, precs)
        graded = sum(1 for r in precs if r["verdict"] in ("won", "lost"))
        print(f"\nFull gated pool: {len(precs)} settleable selections across "
              f"{len({r['match'] for r in precs})} matches -> {graded} graded")
        print(f"Appended {len(precs)} POOL rows to {pout}  "
              f"(observations, NOT bets -- separate file on purpose)")

    backtest_legs = Path(args.backtest_legs)
    backtest_legs.parent.mkdir(parents=True, exist_ok=True)
    append_backtest_legs(backtest_legs, bpath.parent.name, result)
    print(f"Appended {len(result['leg_records'])} leg rows to {backtest_legs}  "
          f"(run calibrate.py for per-family hit% vs implied%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
