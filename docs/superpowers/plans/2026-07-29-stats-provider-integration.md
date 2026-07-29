# Stats-Provider Integration Implementation Plan (settle.py `ResultsSource`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking. **BLOCKED until the user decides provider + budget** — see the design doc
> `docs/superpowers/specs/2026-07-29-stats-provider-integration-design.md` §7.

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
- Respect the provider quota (API-Football free = 100 req/day): one fixtures-by-date+league call,
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

### Task 0 (GATE, blocks everything): free-tier stat-depth probe

Per design §7, the spend decision is **gated on the free tier**, not chosen up front. Before any
build endorsement, run the zero-cost probe (user supplies a free API-Football key; no credentials are
requested or entered by the implementer):
- [ ] `/leagues` → read per-season coverage flags (`statistics_fixtures`, `statistics_players`,
  `events`, `lineups`) for **each league the corpus actually scrapes**, for the free past season(s).
- [ ] `/fixtures/statistics` + `/fixtures/players` on a sample of real fixtures in those leagues →
  **inspect the payload**: are Corner Kicks / Cards / Total Shots / per-player fields present AND
  non-empty? (A "covered" league can return `200` + empty array — the flag is not proof.)
- [ ] Record pass/fail per league. **If the target leagues' stats are empty → gate FAILS → stop and
  recommend score-only** (don't pay for data you can't even validate). Otherwise proceed to Task 1
  and, after settling a historical stat slate, read the per-family gaps via `calibrate.py` (design
  §7 steps 1–2) before any pay-live vs score-only decision (§7 step 3).

The tasks below assume an API-Football-shaped adapter; swapping providers changes only Task 2.

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
