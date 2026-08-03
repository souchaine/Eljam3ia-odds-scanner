"""Joining scraped fixtures to published match reports, and validating what comes back.

These two steps are where a retro-load can corrupt itself invisibly. An unmatched fixture costs
nothing -- it is simply skipped. A WRONGLY matched one writes a plausible scoreline against the
wrong odds and is undetectable downstream, so every rule here fails closed:

- normalization strips only GENERIC club-type tokens (`FC`, `MSK`, `HNK`), never club names;
- qualifiers (women / U-age / reserve) must AGREE on both sides, because "Salzburg vs Hartberg"
  legitimately names two different fixtures on the same day;
- a fixture must match EXACTLY ONE candidate. Ambiguity is rejected, never resolved by guess;
- home and away order is respected -- a reversed fixture is a different match;
- the only tolerated spelling latitude is a closed orthographic table (kyiv/kiev), and matches that
  need it are reported SEPARATELY as aliases so they can carry a full independent cross-check.

Validation then requires each report to be internally consistent: the stated half-time score must
agree with the goal minutes, and the stated full-time score with the goal count. That check costs
nothing per row, so it runs on 100% of them and scales to any volume.
"""

import re
import unicodedata
from dataclasses import dataclass

# Generic club-type tokens across languages. Safe to strip because the same filter runs on both
# sides, and any collision it creates surfaces as AMBIGUOUS and is rejected rather than guessed.
_NOISE = set((
    "fc cf sc afc sk ks ac cd ca ec sv sd ud as ss us rc cs bk ik if ff tc tsv rb sp cp cfr asd "
    "ssd cfc ofk pfc psv vfl vfb fsv bsc sco rcd csd gif iff bif ffc sfc jk jfc kf kss lks gks "
    "mks rks zks msk mfk nk hnk gnk fk club de la el le les los del the and calcio futbol futebol "
    "football klub kulubu spor"
).split())

# Orthographic-only variants of the SAME name. Not a place for "these look similar" -- only
# transliterations and exonyms of one city or club.
_SUBS = {
    "kyiv": "kiev", "moskva": "moscow", "beograd": "belgrade", "praha": "prague",
    "warszawa": "warsaw", "wien": "vienna", "koeln": "koln", "muenchen": "munchen",
    "zuerich": "zurich", "lisboa": "lisbon", "roma": "rome", "torino": "turin",
    "milano": "milan", "napoli": "naples", "sevilla": "seville", "bucuresti": "bucharest",
    "kobenhavn": "copenhagen", "goteborg": "gothenburg", "malmoe": "malmo",
}

_WOMEN = re.compile(r"\b(w|women|womens|ladies|femenino|feminin|feminina|frauen|damen|dam)\b")
_AGE = re.compile(r"\bu\s?(15|16|17|18|19|20|21|23)\b")
# Generic markers only. A club-specific reserve NAME (Vetusta, Castilla) does not belong here: it
# would be an alias wearing a rule's clothing, and it is unnecessary -- such a name is present on
# one side and absent on the other, so the token sets differ and the join already fails closed.
_RESERVE = re.compile(r"\b(ii|reserves|reserve|res)\b")
_GOAL_MINUTE = re.compile(r"(\d{1,3})\s*\.\s*(\+\s*\d+)?")


@dataclass(frozen=True)
class Fixture:
    """One candidate match report, as listed on a results index."""
    ma: str
    comp: str
    home: str
    away: str
    href: str


def _fold(name: str) -> str:
    s = unicodedata.normalize("NFD", (name or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # apostrophes are DELETED, not turned into separators: "Queen's Park" and "Queens Park" are the
    # same club, and splitting them yields a stray "s" token that breaks the join.
    s = s.replace("'", "").replace("’", "").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def qualifiers(name: str) -> str:
    """`W`, `U20`, `R` -- whatever distinguishes this side from the club's first team.

    These must agree across a join. A women's fixture and a men's fixture can carry identical club
    names on the same day; treating them as the same match mis-grades every leg on it.
    """
    s = _fold(name)
    out = []
    if _WOMEN.search(s):
        out.append("W")
    age = _AGE.search(s)
    if age:
        out.append("U" + age.group(1))
    if _RESERVE.search(s):
        out.append("R")
    return ",".join(sorted(out))


def _tokens(name: str) -> list[str]:
    return [t for t in _fold(name).split() if t and t not in _NOISE]


def normalize_key(name: str) -> str:
    """Order-independent key over the significant tokens of a club name."""
    return "_".join(sorted(_tokens(name)))


def normalize_key_alias(name: str) -> str:
    """As `normalize_key`, but folding the closed orthographic table."""
    return "_".join(sorted(_SUBS.get(t, t) for t in _tokens(name)))


def _fixture_key(home: str, away: str, keyfn) -> tuple:
    return (keyfn(home), keyfn(away), qualifiers(home), qualifiers(away))


def match_fixtures(names: list[str], index: list[Fixture]) -> dict:
    """Join scraped fixture names to index candidates. Fails closed at every step.

    Returns `matched` (unique exact), `aliased` (unique only after orthographic folding -- these
    carry the full independent cross-check), `ambiguous` and `unmatched`. The last two are simply
    skipped: an unmatched fixture is free, a wrongly matched one is permanent.
    """
    exact: dict[tuple, list[Fixture]] = {}
    alias: dict[tuple, list[Fixture]] = {}
    for f in index:
        exact.setdefault(_fixture_key(f.home, f.away, normalize_key), []).append(f)
        alias.setdefault(_fixture_key(f.home, f.away, normalize_key_alias), []).append(f)

    matched, aliased, ambiguous, unmatched = [], [], [], []
    for i, name in enumerate(names):
        parts = (name or "").split(" vs. ")
        if len(parts) != 2:
            unmatched.append(i)
            continue
        hits = exact.get(_fixture_key(parts[0], parts[1], normalize_key))
        if hits and len(hits) == 1:
            matched.append((i, hits[0].ma, hits[0].comp))
            continue
        if hits:
            ambiguous.append(i)
            continue
        hits = alias.get(_fixture_key(parts[0], parts[1], normalize_key_alias))
        if hits and len(hits) == 1:
            aliased.append((i, hits[0].ma, hits[0].comp, f"{hits[0].home}_{hits[0].away}"))
        elif hits:
            ambiguous.append(i)
        else:
            unmatched.append(i)
    return {"matched": matched, "aliased": aliased, "ambiguous": ambiguous,
            "unmatched": unmatched}


def _score(text):
    m = re.match(r"^\s*(\d+)\s*:\s*(\d+)\s*$", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _first_half_tally(goals: list[str]) -> tuple[int, int] | None:
    """Running score at the interval, read off the goal list.

    worldfootball prints each goal as the score AFTER it plus the minute, so the last goal at or
    before 45 (including stoppage time, written `45.+2`) carries the half-time score.
    """
    ht = (0, 0)
    seen_any = False
    for g in goals:
        running = _score((g or "").split()[0] if g else "")
        if running is None:
            m = re.match(r"^\s*(\d+):(\d+)", g or "")
            running = (int(m.group(1)), int(m.group(2))) if m else None
        minute = _GOAL_MINUTE.search(g or "")
        if running is None or minute is None:
            return None
        seen_any = True
        if int(minute.group(1)) <= 45:
            ht = running
    return ht if (seen_any or not goals) else None


def validate_report(ft, ht, goals, pso) -> tuple[bool, str]:
    """Is this report internally consistent enough to grade from? 100% of rows pass through here.

    Rejects rather than repairs. A row that cannot be shown to be right is worth less than nothing,
    because it enters the permanent record looking exactly like a row that can.
    """
    if pso:
        return False, "penalty shootout: the headline score is not the match result"
    ftp = _score(ft)
    if ftp is None:
        return False, f"not played / no result published (full-time reads {ft!r})"
    htp = _score(ht)
    if htp is None:
        return False, "no half-time score published; it is never inferred from full-time"
    if htp[0] > ftp[0] or htp[1] > ftp[1]:
        return False, "half-time exceeds full-time -- goals do not un-score"
    if goals and len(goals) != ftp[0] + ftp[1]:
        return False, (f"full-time {ftp[0]}:{ftp[1]} disagrees with {len(goals)} goal event(s)")
    derived = _first_half_tally(goals)
    if derived is None:
        return False, "goal minutes unparseable, so half-time cannot be cross-checked"
    if goals and derived != htp:
        return False, (f"half-time {htp[0]}:{htp[1]} disagrees with goal minutes "
                       f"(they give {derived[0]}:{derived[1]})")
    if not goals and (ftp != (0, 0) or htp != (0, 0)):
        return False, "a non-goalless score with no goal events cannot be cross-checked"
    return True, ""
