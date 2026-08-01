# Stats-Provider Integration Implementation Plan (settle.py `ResultsSource`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking. **BLOCKED — no free or public source covers this dataset (tested
> 2026-07-31).** See Task 0 below and the design doc
> `docs/superpowers/specs/2026-07-29-stats-provider-integration-design.md`.

**Goal:** Add a provider adapter that auto-fetches final+HT scores AND match/player stats for a run's
matches, so the stat families (`player`, `corners`, `cards`, `stat-other`, `interval`) grade and
whole slips become gradeable — without ever guessing a score, a stat, or a name match.

**Architecture:** Extend the DATA, never `grade_leg`'s `won|lost|void|unsettleable` contract. A
`MatchStats` payload rides alongside `MatchOutcome`; `grade_leg` gains an optional `stats=` kwarg;
stat-market grading lands family-by-family as new dispatch branches + `_market_family` entries in
lockstep (the drift-guard property test enforces the lockstep). The provider is one more
implementation of the existing `ResultsSource` seam; the scores CSV stays a valid manual source.

**Tech Stack:** Python 3.11; `httpx` (already a scraper dep) for the provider client; stdlib `csv`/
`json`/`dataclasses` for the rest. `pytest` (dev). Windows `py` launcher.

## Global Constraints (binding)

- `grade_leg` never raises; every existing call site/test must pass UNCHANGED (the new `stats=`
  param is keyword-only, defaulted `None`).
- **Never fuzzy-match names.** Normalized-exact or explicit-alias match only; anything else →
  the match is unmatched → its legs are `unsettleable`. No token-overlap/edit-distance auto-accept.
- **Never guess a stat.** A `None` stat field → the dependent leg is `unsettleable`, never a 0.
- Grader + `_market_family` extended in lockstep; `tests/test_market_family_property.py` must stay
  green (it fails if a newly-gradeable market classifies as `other`).
- Settlement stays offline-replayable: cache raw provider JSON under `output/run_*/provider/`; a
  re-settle must not re-hit the network.
- Respect whatever quota the eventual provider imposes: one fixtures-by-date+league call,
  then one stats call per matched fixture, all cached. Single-thread, backoff/retry, partial-save.
- Per-family reporting only; no blended aggregate. New stat families slot into the existing
  per-family + `calibrate.py` tables with real numbers once wired.
- Branch: `feature/stats-provider`. Project root uses the `py` launcher.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `settle.py` | grading + settlement | Add `MatchStats`; widen `ResultsSource`; `grade_leg(..., stats=None)`; stat-market branches + `_market_family` entries; thread stats through `_leg_verdicts`/`settle_run` |
| `provider.py` (new) | provider adapter | `ApiFootballSource(ResultsSource)`: fixtures-by-date, per-match statistics, JSON cache, name resolution |
| `names.py` (new) | name matching | `normalize(name)`, alias-table load, `resolve(altenar_name, candidates) -> id|None` (never fuzzy) |
| `data/aliases.csv` (new) | curated aliases | Altenar name → provider fixture/team key, seeded from a reconciliation pass |
| `tests/…` | tests | grading tests per stat family; name-matching tests (incl. unmatched→None); adapter tests against CACHED JSON fixtures (no live network in CI) |

---

### Task 0 (GATE, blocks everything): a source with adequate coverage — NOT YET FOUND

**Status 2026-07-31: no free or public source clears this gate.** Tested and measured against the
real backlog (2,818 played, in-play-clean fixtures / 39,728 gate-eligible selections):

- **API-Sports / API-Football free** — key rejected (RapidAPI key on an account with no
  API-Football subscription); season restriction unverifiable (pricing + docs 403) and likely fatal
  since every backlog fixture sits in a currently-running season.
- **Sportmonks free** — Danish Superliga + Scottish Premiership only: **36 fixtures (1.3%)**.
- **Public / keyless** (openfootball, TheSportsDB, OpenLigaDB) — major European domestic leagues
  only: **32 fixtures (1.1%)**, and even those are doubtful (our `Bundesliga` is Austrian).
- **apifootball.com** — the ONLY untested candidate. Publishes half-time fields
  (`match_hometeam_halftime_score`), which is the requirement that matters most. Free-tier league
  coverage undocumented.

**The blocker is the backlog's composition, not the providers**: 707 of 2,818 fixtures are in a
single unnamed competition (`League 2932`), and the rest skew to U20/regional/3rd-tier leagues that
no commercial or open dataset covers. Provider-shopping cannot fix that.

Before ANY build resumes, a candidate source must reproduce the golden record — **Central Cordoba
0-2 Atletico Tucuman, HT 0-0** (Argentine Primera, 2026-07-31T00:15Z) — on **both** FT and HT. That
check exists because a lookup for this exact fixture once returned a 1-1 result from July **2025**,
a different match from a different season presented as the real one.

If no source clears it, the tier-1 subset (**246 fixtures / 9,607 selections**) is the only tractable
target and needs a paid tier or patient manual lookup. Everything below stays valid whenever a
source is found.

### Task 1: `MatchStats` + widened seam + `grade_leg(stats=)` (no behavior change yet)

**Interfaces:** `@dataclass MatchStats` (all fields Optional); `ResultsSource.stats_for(slips) ->
dict[str, MatchStats]`; `NoResultsSource.stats_for` returns `{}`; `grade_leg(market, selection, o,
*, stats=None)`.

- [ ] Step 1 (RED): tests asserting `grade_leg` signature accepts `stats=` and every existing
  verdict is byte-identical with `stats=None`; `NoResultsSource().stats_for([]) == {}`.
- [ ] Step 2 (GREEN): add `MatchStats`, widen the Protocol + placeholder, thread an optional
  `stats` param through `grade_leg`/`_leg_verdicts`/`settle_run` (unused by score markets).
- [ ] Step 3: full suite green, unchanged (pure plumbing).

### Task 2: `ApiFootballSource` adapter against CACHED JSON (no live CI network)

**Interfaces:** `ApiFootballSource(api_key, cache_dir)` implementing `outcomes_for` + `stats_for`;
reads/writes `output/run_*/provider/*.json`; maps provider fixture → `MatchOutcome` (FT + HT) and →
`MatchStats`.

- [ ] Step 1 (RED): tests that parse a **committed sample provider JSON fixture** into a known
  `MatchOutcome`/`MatchStats` (HT from the halftime score object; corners/cards/shots from the
  statistics array). No live calls in tests.
- [ ] Step 2 (GREEN): implement parsing + on-disk cache (fetch only on cache miss).
- [ ] Step 3: a thin live-smoke script (manual, not in CI) hitting the free historical season to
  confirm the shapes match the fixtures.

### Task 3: name matching (`names.py` + alias table)

- [ ] Step 1 (RED): `normalize` cases (accents, "CF"/"FC"/"SC" suffixes, whitespace); `resolve`
  returns the id on normalized-exact or alias hit and **`None` on anything ambiguous/unknown**;
  a near-miss ("Estudiantes" vs "Estudiantes Río Cuarto") returns `None`, NOT a guess.
- [ ] Step 2 (GREEN): implement; load `data/aliases.csv`.
- [ ] Step 3: reconciliation pass over the real corpus → seed `aliases.csv`; print the unmatched
  list as the manual-curation worklist.

### Task 4+: stat families, one audit-gated commit each (grader+classifier lockstep)

For each family, in order of leg volume (corners → cards → player), a separate commit:
- [ ] audit the real selection vocabulary for that family (like the score-tranche gates);
- [ ] RED tests over the real shapes, incl. `stats=None` → `unsettleable`;
- [ ] GREEN: add the dispatch branch reading `MatchStats` + the `_market_family` mapping;
- [ ] confirm the drift-guard property test still passes (regenerate its fixture — the new markets
      become gradeable, so `_gen_gradeable_fixture.py` must be re-run and the delta reviewed).

### Task N: wire into `main()` + calibration

- [ ] `settle.py --source api-football --api-key …` selects the provider (default stays the scores
  CSV); provider outcomes+stats feed `settle_run`; `backtest_legs.csv` now carries graded stat legs;
  `calibrate.py` shows real hit% for the stat families.

## Final whole-branch review (per project convention)

One review on the strongest model over `feature/stats-provider`, sweeping the real corpus and
adversarially probing the name-matcher (the highest-risk component — a wrong fixture silently
mis-grades a whole match). Then finishing-a-development-branch ("both").
