# Session Handoff — 2026-07-29

Purpose: full record of this session + the forward plan, so a NEW session can pick up with zero
context. Read this first, then `.superpowers/sdd/progress.md` (the durable ledger) if you need
per-task detail.

---

## 1. Project TL;DR

**kora** scrapes eljam3ia.com (an **Altenar** sportsbook widget) via its unauthenticated JSON API,
finds football selections with odds in a target window (~[1.25, 1.50]), builds 20-leg accumulator
betslips, reserves shareable **booking codes** (no money moves), and **settles/backtests** them
against hand-entered HT+FT scores. Python 3.11 + `httpx` (scraper), stdlib-only `settle.py`,
`pytest` (dev). Windows, `py` launcher.

- Repo root: `C:\Users\user\OneDrive - Ministere de l'Enseignement Superieur et de la Recherche Scientifique\Desktop\kora`
- Remote: `https://github.com/souchaine/Eljam3ia-odds-scanner.git`
- **State at handoff: `main` = `ae6b86e`, clean, pushed. 126/126 tests green.**
- Review-reference branches kept on origin (never delete): `feature/half-combo-grading`,
  `feature/score-derivable-tranche`, `feature/settlement-core`, `feature/per-category-betslips`.

## 2. File map

| File | Role |
|---|---|
| `eljam3ia_odds_scanner.py` | Scan leagues → `output/run_*/odds_matrix_*.csv` (+ meta sidecar). Shared config/helpers (`clean`, `fetch`, `get_all_football_events`, target window) imported by the others. |
| `make_betslips.py` | Build SET A (≤50 all-odds 20-leg slips) + SET B (≤25 diversified across 7 families) → reserve booking codes → `output/run_*/betslips_*.txt`. Win% = `100/combined_odds`. |
| `run_all.py` | One-command pipeline: scan → matrix → betslips → codes → summary. |
| `settle.py` | Settlement core (stdlib only): parse betslips file + scores CSV → grade every leg → per-family table + diagnostic slip trackers → append `output/backtest.csv`. |
| `merge_matrices.py` | Union matrix CSVs, dedupe by event id. |
| `tests/` | 126 tests: `test_grade_leg.py` (grading), `test_settle_run.py` (families/tallies), plus scanner/betslip/pipeline suites. |
| `docs/superpowers/specs/` + `plans/` | Committed design specs + implementation plans per sub-project. |
| `.superpowers/sdd/progress.md` | **Durable SDD ledger** (git-ignored). Source of truth for what's done. |

## 3. What this session shipped (2 sub-projects, both merged + pushed)

### 3a. Half + combo grading (merge `383de8d`)

- Extracted pure core `_grade_score(key, sel, home, away)` — behaviour-identical for the 8 original
  FT markets; added DC-notation normalization (`1x`/`1/x`/`1 or draw` → one pair), team total,
  team clean sheet, odd/even.
- Half wrapper: `1st|2nd half - <core>` graded on the half score (2nd = FT − HT); word forms
  `First/Second half` accepted; missing `ht_*` → unsettleable.
- Combo wrapper: `A & B` split, each component recursed, combined with precedence
  `unsettleable > lost > void > won`.
- `UNSETTLEABLE` regex narrowed to stat tokens only: `corner|booking|card|shot|tackle|offside|foul`.
- **Critical caught by final review** (seam between the two tasks): a half-prefixed combo
  (`2nd half - double chance & both teams to score`) graded post-`&` components on FULL TIME.
  Fixed by distributing the half prefix over components (`c0d76e9`) + regression test.

### 3b. Score-derivable tranche (merge `ae6b86e`) — this session's main work

**Three verification gates run against real data BEFORE any code** (all three changed the design):

1. **Multigoals**: 21,618 selections sampled → three forms exist: `"N-M"`, `"N+"` (×15, hit
   already-shipped code as a silent coverage gap), `"No goal"` (×18). Naive `split("-")` = wrong.
2. **Handicap 1X2**: full UNFILTERED live ladder (Kairat v Omonia) proves `(a:b)` =
   home-start:away-start, leading token = bet side (odds monotone in the line). **`Draw (a:b)` is an
   explicit selection; each line is its own 3-way market (Σ1/p = 1.120) ⇒ equality is a Draw WIN,
   NEVER a void** — opposite of the Asian `handicap` key, which voids and is untouched.
3. **FT cumulative**: `MatchOutcome.home/.away` include 1st-half goals; 2nd half = FT − HT. Locked
   by a discriminating HT/FT test.

**Phase 1 (commit `e0f7d0f`)**: team multigoals (three forms, also applied to plain `multigoals`),
team exact-goals (`N exact goals`), team to-score (`N to score`), `handicap 1x2` (3-way, no void),
`_grade_htft` for `Halftime/fulltime` `"1/1"` + `DC Halftime/ DC Fulltime` `"X2/X2"` (its `& total`
combos recurse through the combo wrapper for free).

**Per-family reporting (commit `522e633`)**: `_market_family` classifier (ordered, first-match-wins:
player/stat families BEFORE period families; explicit `other` bucket so unanticipated markets land
visibly). `settle_run` returns `"families"` = `{family: {n, distinct, gradeable, won}}` built from
the SAME leg verdicts as the per-set tallies. Output = per-family table, **NO blended aggregate**
(the gradeable subset is a biased sample); slip trackers retained but labelled **diagnostic only**.

**Phase 2 OR-combos (commit `212c9c2` + fix waves `47fe7fd`, `b56ce7a`)**: two grammars —
simple (`"Draw or under 1.5"` / `Yes|No`, market carries both legs) and compound
(`"Both team to score or Total 2.5"` / `"Under 2.5 or no"` — **selection order is REVERSED vs the
market, tokens bind BY TYPE, never positionally**). Guards: unbound leftover tokens, void-in-OR
(push), half-scope on EITHER component, same-type-ambiguous components → all `unsettleable`.

**Final whole-branch review** (swept all 44 betslip files, 15,541 legs; found 4 issues, all fixed in
`d810a1a`):
- `_grade_htft` decided before validating → same unparseable selection graded `lost` OR
  `unsettleable` depending on the score. Now: resolve both picks, then decide.
- Unanchored `2nd\s*half` force-fit `1st/2nd half both teams to score` into the `2nd half` family
  (14% skew) → new `both halves` family.
- OR components matched by substring + blacklist → whitelist via `re.fullmatch`; per-component
  half-prefix blacklist became provably redundant and was removed (whole-market check kept).
- Per-family `n` double-counts legs repeated across slips (1500 vs 1153 distinct, 24%) → added
  `distinct` column.

**Result: gradeable legs 603/1500 (40%) → 1090/1500 (73%)** on the current slate. Every remaining
ungraded leg is a genuine stat/event market (player shots/saves/assist, corners, cards, race-to-N,
first/last goal, scoring type, penalty, 15-min intervals) — they need a **stats provider**, not more
parsing.

## 4. Binding invariants — do not violate in future work

1. `grade_leg(market, selection, outcome)` NEVER raises; returns exactly
   `won|lost|void|unsettleable`. **A mis-graded leg is strictly worse than an ungraded one** —
   anything ambiguous/unrecognized/unbound → `unsettleable`, never a guess.
   **Validate fully, THEN decide** (never emit a verdict while a sibling token is unparsed).
2. `grade_leg` dispatch order: combo `" & "` → HT/FT → OR (` or `, whole-market half check) →
   `1st/2nd half both teams to score` special case → half prefix → `UNSETTLEABLE` stat regex →
   `_grade_score` (FT).
3. `handicap 1x2` never voids (3-way with explicit Draw lines); Asian `handicap` DOES void; keep
   both, never merge them.
4. Multigoals = three forms (`N-M`, `N+`, `No goal`) everywhere multigoals appears.
5. FT is cumulative; 2nd half = FT − HT; missing `ht_*` → unsettleable for half/HT-FT legs.
6. OR compound selections bind BY TYPE (grammar reverses order); component recognition is a
   `re.fullmatch` WHITELIST — new component types must be added to BOTH `_or_component_verdict`
   AND `_or_component_pattern` (cross-ref comments in code).
7. Reporting: per-family with `n` + `distinct`; NEVER a blended aggregate; `other` bucket must stay
   a genuine catch-all (never force-fit); grader (`grade_leg`) and classifier (`_market_family`)
   must be extended in lockstep.
8. Win% = `100/combined_odds`. **NEVER de-vig by normalizing across an Altenar market's outcomes**
   — markets bundle many lines (Σ1/p ≈ 10, not ~1.05); it broke monotonicity once already.
9. `reserveBet` needs the FULL widget selection shape (odd enriched via `GetOddsStates`, event,
   market, sport, category, championship, competitors, widgetInfo) or the site UI crashes on load.
   Codes go stale when matches kick off — mint shortly before use.
10. Names from the feed need whitespace-collapse (`clean()`); UTF-8 stdout/stderr reconfigure in
    every entry point (cp1252 crash on names like 'ă'); `eventsCount` = matches + outrights; no
    pagination on `GetEvents`; keep politeness (single-thread, ~0.7 s + jitter, retries/backoff).
11. Eljam3ia has NO results feed — settlement input is a hand-entered scores CSV
    (`match,home,away[,ht_home,ht_away]`) or, in future, a `ResultsSource` adapter
    (seam + `NoResultsSource` placeholder already exist in `settle.py`).

## 5. Workflow conventions (the user's standing preferences)

- Every feature: **superpowers flow** — brainstorm → spec (`docs/superpowers/specs/`) → plan
  (`docs/superpowers/plans/`) → **subagent-driven development** (fresh implementer per task +
  task reviewer; fix subagents for findings; ONE final whole-branch review on the strongest model)
  → finishing-a-development-branch.
- Branch finish = **"both", always**: merge to `main` locally (`--no-ff`, descriptive
  `Merge feature/<name>: <summary>`), verify full suite on the merged result, push `main`, push the
  feature branch, KEEP the branch as a review reference. Commit stray plan/spec docs onto the branch
  first so they ride along.
- Track progress in `.superpowers/sdd/progress.md` — append per task; it is the recovery map after
  any interruption (API outages killed subagents twice; the ledger + `git log` beat memory).
- Verification-gate pattern for parser work: audit the REAL data (all runs, and live API when the
  filtered sample is inconclusive) before writing grading code. Every gate this session changed the
  design.
- Review hygiene: controller reproduces every finding before dispatching a fix; ONE fix subagent per
  findings list (not per finding); reviewers never see dispatch prompts (a "fabricated citation"
  finding was a false positive for exactly that reason — adjudicated, no fix).
- Do NOT quote blended coverage/hit-rate numbers in docs; per-family only.

## 6. Forward plan (priority order for the new session)

### P1 — First REAL settlement run (no code needed)
The E2E used synthetic scores; no real hit rates exist yet. Steps: after a slate's matches finish,
hand-enter `match,home,away,ht_home,ht_away` for the ~30 matches of the latest run (match names
exactly as in the betslips file), then:
`py settle.py output/run_*/betslips_*.txt --outcomes scores.csv`
→ first genuine per-family hit rates into `output/backtest.csv`. Repeat over several slates before
drawing any conclusion (per-family n is small on one slate).

### P2 — Stats provider integration (the only path to the remaining 27% + slip-level grading)
- Goal: auto-fetch final+HT scores AND stats (corners, cards, shots, per-player) so stat families
  grade and whole slips become gradeable.
- Seam exists: `ResultsSource` Protocol in `settle.py` (`outcomes_for(slips) -> {match: MatchOutcome}`);
  extend `MatchOutcome` (or a parallel `MatchStats`) rather than reworking `grade_leg`'s contract.
- Candidates: API-Football, football-data.org (evaluate free-tier coverage of the leagues actually
  scraped — the slates are worldwide, incl. Argentine/Brazilian leagues).
- Hard part: matching Altenar's whitespace-collapsed team names to the provider's names — plan for a
  normalization + alias table with an explicit "unmatched → unsettleable" rule (never fuzzy-guess).
- This should be its own brainstorm → spec → plan → SDD cycle.

### P3 — Backtest analysis (after several real runs accumulate)
Per-family hit rate vs the odds' implied probability (calibration): are 1.25–1.50 legs in family X
winning at the ~67–80% the odds imply? That comparison, per family with n and distinct, is the
project's actual measurement goal.

### P4 — Small deferred items (optional, cheap)
- `DC Halftime/ 1X2 Fulltime` (~5 legs): per-position flag in `_grade_htft` grades it with no new
  parsing.
- `Both halves over/under N` is actually score-derivable (both half scores are known) — was YAGNI'd
  at 1 leg; add to `_grade_score` + classifier lockstep if it grows.
- Final review's recommendation: a property test over the real market vocabulary asserting every
  gradeable market classifies into a non-`other` family (prevents grader/classifier drift).
- Known accepted divergence: `make_betslips.py::market_category` (7 families, `carte`) vs
  `settle.py::_market_family` (14 families, `cards`) — different purposes, both tested; reconcile
  only if the two reports are ever shown side by side.
- Pre-existing, deliberately kept: `1x2`/`draw no bet` grade a garbage selection as `lost` (locked
  by tests; changing it would break FT-identical history).

### P5 — Operational cadence (if the user wants automation)
`run_all.py` already does scan→slips→codes in one command; a scheduled daily run + a settlement run
the morning after is the natural loop. Codes must always be minted at run time (staleness).

## 7. Quick-start commands

```bash
# full pipeline (scan -> matrix -> dual-set betslips -> booking codes)
py run_all.py

# settle a run against real scores
py settle.py output/run_YYYYMMDD_HHMM/betslips_*.txt --outcomes scores.csv

# tests
py -m pytest tests/ -q
```
