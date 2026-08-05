"""Retro-settlement of the unsettled backlog: which observations are eligible, and exactly one of
each.

The project accumulates one slate a day, and at that rate the sample reaches a band where an edge
would be visible in about a year. The backlog -- 28 run directories of already-scraped odds -- gets
there in one pass, but only if two things are true: every observation is genuinely pre-match, and
no observation is counted twice.

Deduplication is the reason this module exists. 40% of backlog fixtures were scraped in more than
one run, so 48,438 gated selections carry only 32,101 distinct (match, market, selection) triples.
Appending the raw rows would inflate `graded`, shrink the error bars and make the calibration lie
IN THE CONFIDENT DIRECTION -- a plausible number carrying unearned precision. That failure is
invisible downstream, so the invariant is pinned by a test, not left to a script step.

Usage:
    py backlog.py [--output output] [--worklist YYYY-MM-DD] [--scores-cache output/scores_cache]
"""

import argparse
import csv
import re
import sys
from pathlib import Path

from settle import _parse_utc, exclude_inplay, is_settleable, read_odds_matrix

# Runs already represented in the backtest files; settling them again would double-count.
SETTLED_RUNS = {"run_20260715_0900", "run_20260731_0039", "run_20260801_1007"}

# "League 2932", "League 11070" -- Altenar's placeholder for a competition it does not name.
_NUMBERED = re.compile(r"^(league\s+)?\d+$", re.IGNORECASE)


def is_named_competition(league: str) -> bool:
    """False for a competition that cannot be cross-checked against an external source.

    A numbered placeholder (`League 2932`, 849 fixtures on its own) gives no country, no tier and
    no way to confirm that a name match landed on the right fixture. Since a wrong pairing produces
    a plausible number silently -- the one error class no test here catches -- those fixtures are
    excluded outright rather than matched hopefully. Note `League Cup` is a REAL name and must
    survive: it differs from `League 2932` by one token, and a prefix rule would drop it.
    """
    name = (league or "").strip()
    return bool(name) and not _NUMBERED.match(name)


def dedupe_selections(selections: list[dict]) -> list[dict]:
    """One row per (match, market, selection): the EARLIEST pre-match scrape wins.

    A fixture priced on several days carries several odds, so a rule is required; this one is
    stated here so it is not re-litigated later:

    - *latest* sits closest to kickoff and is therefore the best-informed price -- it leaks late
      information into what is meant to be a pre-match forecast;
    - *best odds* is selection bias by construction;
    - *earliest* is neutral, mechanical, and maximally distant from kickoff.

    A row with no parseable scrape time cannot be SHOWN to be pre-match (the same view
    `exclude_inplay` takes), so it is dropped rather than sorted to the front. Ties break on the run
    name, so the result does not depend on input order.
    """
    best: dict[tuple, tuple] = {}
    for s in selections:
        end = _parse_utc(s.get("scrape_end"))
        if end is None:
            continue
        key = (s.get("match"), s.get("market"), s.get("selection"))
        rank = (end, str(s.get("run", "")))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, s)
    return [row for _, row in best.values()]


def canonical_kickoffs(selections: list[dict]) -> dict[str, str]:
    """One kickoff DATE per fixture: the one recorded by its earliest scrape.

    Deduplication keys on (match, market, selection), so different MARKETS of one fixture can
    survive from different runs -- and when a kickoff is rescheduled between scrapes those rows
    disagree about the date. Left alone that lists the fixture on two dates and inflates `n_dates`,
    which is a reported statistic. The earliest scrape wins here for the same reason it wins in
    `dedupe_selections`: it is the neutral, mechanical choice.
    """
    best: dict[str, tuple] = {}
    for s in selections:
        ko = (s.get("kickoff") or "").strip()
        match = s.get("match")
        end = _parse_utc(s.get("scrape_end"))
        if not ko or not match or end is None:
            continue
        rank = (end, str(s.get("run", "")))
        if match not in best or rank < best[match][0]:
            best[match] = (rank, ko[:10])
    return {match: day for match, (_, day) in best.items()}


def worklist_by_date(selections: list[dict], already_scored: set,
                     finished_before: str | None = None) -> dict[str, list[str]]:
    """Fixtures still needing a score, grouped by their canonical kickoff date.

    Resumability lives here: a fixture already in the score cache is never re-fetched, so the
    worklist shrinks with every pass and the job survives across sessions. A date with nothing left
    disappears entirely rather than lingering as an empty entry.

    `finished_before` drops fixtures that have not finished yet. A match still in progress has no
    result, and asking for one is how a guess gets invited.
    """
    cutoff = _parse_utc(finished_before)
    out: dict[str, set] = {}
    for s in selections:
        match = s.get("match")
        ko = _parse_utc(s.get("kickoff"))
        if not match or ko is None or match in already_scored:
            continue
        if cutoff is not None and ko >= cutoff:
            continue
        out.setdefault(match, None)
    days = canonical_kickoffs(selections)
    grouped: dict[str, set] = {}
    for match in out:
        day = days.get(match)
        if day:
            grouped.setdefault(day, set()).add(match)
    return {day: sorted(names) for day, names in sorted(grouped.items()) if names}


GRADED_VERDICTS = ("won", "lost", "void")

# A rejection is remembered only when re-fetching CANNOT change it. Everything here is a property
# of what the SOURCE published: a shootout, an absent goal timeline, or a self-contradictory report
# reads the same tomorrow. "not fetched" and "not played" are deliberately absent -- a throttled
# request returns a page with no result, which validates as "not played", and caching that would
# permanently discard a real fixture because of one bad request.
_PERMANENT = ("penalty shootout", "no goal events", "disagrees with goal minutes",
              "disagrees with", "never inferred from full-time", "goals do not un-score",
              "goal minutes unparseable")
_TRANSIENT = ("not fetched", "not played", "no result published")

REJECTIONS_FILE = "rejected.csv"


def is_permanent_rejection(reason: str) -> bool:
    """Will re-fetching this fixture produce a different answer? If it might, do not cache it."""
    text = (reason or "").lower()
    if any(t in text for t in _TRANSIENT):
        return False
    return any(p in text for p in _PERMANENT)


def read_rejections(rejected_dir) -> set:
    """Fixtures whose rejection is permanent, so the worklist can stop re-fetching them."""
    path = Path(rejected_dir) / REJECTIONS_FILE
    if not path.exists():
        return set()
    return {r["match"] for r in csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
            if r.get("match")}


def write_rejections(rejected_dir, rejections: dict, succeeded: set | None = None) -> int:
    """Merge this run's PERMANENT rejections into the list; drop any fixture since scored.

    `succeeded` exists because a rejection is a statement about one attempt, not a verdict on the
    fixture: if a later run manages to verify it, it must leave the list rather than sit there
    suppressing a fixture that now works.
    """
    out = Path(rejected_dir)
    out.mkdir(parents=True, exist_ok=True)
    keep = {m: "" for m in read_rejections(out)}
    for match, reason in (rejections or {}).items():
        if is_permanent_rejection(reason):
            keep[match] = reason
    for match in (succeeded or set()):
        keep.pop(match, None)
    with (out / REJECTIONS_FILE).open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["match", "reason"])
        for match, reason in sorted(keep.items()):
            w.writerow([match, reason])
    return len(keep)


def handled_fixtures(cache_dir, rejected_dir) -> set:
    """Fixtures the loop should not look up again: already scored, or permanently rejected."""
    scored = set()
    cache = Path(cache_dir)
    if cache.exists():
        for f in cache.glob("*.csv"):
            for row in csv.DictReader(f.read_text(encoding="utf-8-sig").splitlines()):
                if row.get("match"):
                    scored.add(row["match"])
    return scored | read_rejections(rejected_dir)


def already_loaded_triples(pool_path) -> dict[tuple, str]:
    """(match, market, selection) -> verdict, for everything already in the pool log.

    Deduping only WITHIN the backlog misses the overlap with the LIVE slates: `run_20260801_0900`
    is in the backlog while `run_20260801_1007` is already settled, and they share fixtures.
    """
    path = Path(pool_path)
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()):
        if r.get("match"):
            out[(r["match"], r.get("market"), r.get("selection"))] = r.get("verdict", "")
    return out


def exclude_already_loaded(selections: list[dict], loaded: dict[tuple, str]) -> list[dict]:
    """Drop backlog rows the pool log already MEASURES; keep those it merely records as unknown.

    A triple already carrying a real verdict (won/lost/void) is the same observation -- re-adding
    it inflates `graded` and narrows the error bars, the confident-direction failure.

    A triple recorded as `unsettleable` is different: that row carries no measurement content at
    all (calibrate excludes it from hit%, implied% and roi), so replacing it with a graded row
    strictly adds information and cannot bias anything. It is kept here and the stale row is purged
    by `purge_unsettleable` before the append, so the file never holds the triple twice.
    """
    return [s for s in selections
            if loaded.get((s.get("match"), s.get("market"), s.get("selection")), "")
            not in GRADED_VERDICTS]


def purge_unsettleable(pool_path, triples: set) -> int:
    """Remove `unsettleable` rows for the given triples; returns how many went.

    Only ever deletes non-measurements. A row with a real verdict is a measurement and is never
    touched, however tempting it would be to "refresh" it.
    """
    path = Path(pool_path)
    if not path.exists():
        return 0
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        return 0
    header, body = rows[0], rows[1:]
    idx = {name: header.index(name) for name in ("match", "market", "selection", "verdict")
           if name in header}
    if len(idx) < 4:
        return 0
    kept, removed = [], 0
    for row in body:
        key = (row[idx["match"]], row[idx["market"]], row[idx["selection"]])
        if row[idx["verdict"]] == "unsettleable" and key in triples:
            removed += 1
            continue
        kept.append(row)
    if removed:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(kept)
    return removed


def _scrape_finished(meta_path: Path) -> str | None:
    """The run's finish time: the latest timestamp anywhere in the matrix's meta sidecar."""
    if not meta_path.exists():
        return None
    best = None
    for row in csv.reader(meta_path.read_text(encoding="utf-8-sig").splitlines()):
        for cell in row:
            t = _parse_utc(cell)
            if t and (best is None or t > best):
                best = t
    return best.isoformat().replace("+00:00", "Z") if best else None


def backlog_selections(output_root, settled: set = SETTLED_RUNS) -> list[dict]:
    """Every gate-eligible, pre-match, named-competition selection across the UNSETTLED runs.

    Each row is tagged with its `run` and that run's `scrape_end` so `dedupe_selections` can apply
    the earliest-wins rule across runs. In-play exclusion happens per matrix, before anything else:
    a run whose scan window spans its own fixture list contributes nothing at all.
    """
    out = []
    for d in sorted(Path(output_root).glob("run_*")):
        if d.name in settled:
            continue
        matrices = [p for p in d.glob("odds_matrix_*.csv") if "meta" not in p.name]
        if not matrices:
            continue
        end = _scrape_finished(next(iter(d.glob("odds_matrix_*_meta.csv")), Path("nope")))
        sels = read_odds_matrix(matrices[0].read_text(encoding="utf-8-sig"))
        for s in exclude_inplay(sels, end):
            if not is_named_competition(s.get("league", "")):
                continue
            if not is_settleable(s.get("market"), s.get("selection")):
                continue
            out.append({**s, "run": d.name, "scrape_end": end})
    return out


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Backlog retro-settlement worklist.")
    ap.add_argument("--output", default="output", help="root holding the run_* directories")
    ap.add_argument("--scores-cache", default="output/scores_cache", dest="cache",
                    help="per-date verified results; a cached fixture is never re-fetched")
    ap.add_argument("--rejected", default="output/scores_rejected",
                    help="permanently-rejected fixtures, skipped instead of re-fetched")
    ap.add_argument("--worklist", default=None,
                    help="print the fixtures still needing a score for this date (YYYY-MM-DD)")
    ap.add_argument("--pool", default="output/backtest_pool_legs.csv",
                    help="existing pool log; triples it already MEASURES are excluded from the "
                         "retro-load so the live slates are not double-counted")
    ap.add_argument("--finished-before", default=None, dest="finished_before",
                    help="drop fixtures kicking off at or after this UTC instant -- they have not "
                         "finished, so they have no result to look up")
    args = ap.parse_args()

    sels = dedupe_selections(backlog_selections(args.output))
    raw = len(sels)
    loaded = already_loaded_triples(args.pool)
    sels = exclude_already_loaded(sels, loaded)
    cache = Path(args.cache)
    scored = handled_fixtures(cache, args.rejected)
    wl = worklist_by_date(sels, scored, finished_before=args.finished_before)

    if args.worklist:
        for name in wl.get(args.worklist, []):
            print(name)
        return 0

    print(f"backlog: {raw} distinct triples after dedupe; {raw - len(sels)} already MEASURED in "
          f"{args.pool} -> {len(sels)} to load, across {len({s['match'] for s in sels})} fixtures")
    print(f"already handled: {len(scored)} fixture(s) — scored in {cache}, or permanently "
          f"rejected in {args.rejected}")
    print(f"\n{'date':<14}{'fixtures still needed':>22}")
    for day, names in wl.items():
        print(f"  {day:<12}{len(names):>20}")
    print(f"\ntotal still needed: {sum(len(v) for v in wl.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
