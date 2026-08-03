# Backlog Retro-Settlement — Design

**Status:** approved 2026-08-03. Supersedes the "retro-expansion declined" note in
`.superpowers/sdd/progress.md` (2026-08-02), which was correct at the time: the browser score
method existed but name-matching at volume had no discipline attached to it. This design supplies
that discipline.

**Goal.** Settle the unsettled backlog so per-family calibration reaches a sample where an edge
would be visible. Today: 62 matches, ±11pp. One slate a day reaches ±2.2pp in about a year; the
backlog reaches it in one session.

## 1. What is in scope

Measured 2026-08-03 across the 28 unsettled run directories, after `exclude_inplay` per matrix:

| | count |
|---|---|
| distinct gate-eligible fixtures | 3,676 |
| kickoff dates | 29 (22 past, ~40 fixtures future-dated) |
| gated selections, raw | 48,438 |
| distinct (match, market, selection) triples | 32,101 |
| **duplicate rows across runs** | **16,337 (34%)** |
| fixtures appearing in >1 run | 1,474 (40%) |
| fixtures in unnamed/numbered competitions | 1,056 (29%) |

`exclude_inplay` wipes `run_20260724_1812` to zero fixtures, as expected — it is a 26-hour scan
whose window spans its own fixture list. Confirming that is a precondition of the run.

### Excluded, and not to be reconsidered mid-run

- **Unnamed / numbered competitions** (`League 2932` = 849 fixtures alone, 29% of the backlog).
  A numbered league cannot be competition-cross-checked, so a name match inside it is unverifiable.
  A wrong pairing is the one error class no test in this project catches — it produces a plausible
  number, silently. Yield is not a reason to revisit this.
- **Future-dated fixtures** (~40). Not played.
- Slip building, `run_all.py`, and the 09:00 cron. Making the builder history-aware is a separate
  piece of work that must wait for these numbers, so that today's noise is not baked into stakes.

## 2. Hard requirement: dedupe as a tested invariant

40% of backlog fixtures were scraped in more than one run. Appending them naively inflates
`graded`, shrinks the error bars, and makes the calibration **lie in the confident direction** — a
plausible number carrying unearned precision, which is the worst way for this bug to fail.

- Dedupe key: **(match, market, selection)**.
- Survivor rule: **the earliest pre-match scrape wins** (after `exclude_inplay`).
  Why earliest, stated so it is not re-litigated later: the same fixture priced on different days
  carries different odds, so a rule is required. *Latest* is closer to kickoff and therefore the
  best-informed price — it leaks the most late information into what is meant to be a pre-match
  forecast. *Best odds* is selection bias by construction. *Earliest* is neutral, mechanical, and
  maximally distant from kickoff.
- A test asserts **zero duplicate triples survive a retro-load**, so a future re-run cannot silently
  reintroduce them.
- The run reports raw rows seen vs distinct triples loaded.

## 3. Hard requirement: verification that does not decay with volume

Slate 2 cross-checked 8 of 42 rows (~19%) against an independent source. That rate does not survive
2,000 fixtures, and a rate that quietly decays toward zero as volume rises is worse than a stated
low rate. Fixed up front:

- **100% self-consistency.** Stated HT must agree with the goal minutes on the match report. This
  scales for free because it is computed from data already fetched. **A row that fails is rejected**,
  not repaired.
- **Independent cross-check: a fixed random 5%, plus 100% of any fixture joined via an alias**
  rather than a unique-exact name match. Alias joins are where a wrong pairing can hide, so they
  carry the full check.
- Both achieved rates are reported. If either falls below target, say so — never proceed silently.
- Penalty shootouts: a `pso` marker means the headline score is not the match result (O'Higgins–Boca
  showed 3:4; the real result was 1:0). Checked on every cup fixture.

## 4. Join discipline

Unchanged from the project invariants, restated because this run is where they would break:

- Unique-exact normalized name match on **both** sides **plus competition agreement**, or an
  explicit recorded alias. **Never fuzzy. Never date-alone.**
- Reserve / second / U-teams can never match first teams.
- Unmatched → **skipped**. An unmatched fixture costs nothing; a wrongly-matched one corrupts the
  measurement permanently and invisibly.
- Every alias used and every unmatched fixture is reported.

## 5. Reporting: `n_dates` beside `n_matches`

The ±2.2pp figure at ~1,600 matches assumes independence, and these observations are *less*
independent than across-slate ones: ~1,600 fixtures cluster into ~22 kickoff dates, and within a
date, market-wide pricing conditions correlate.

- Per family, report **n_legs, n_matches, and n_dates**.
- Treat the true band as **wider** than the naive n_matches figure. Under-claim precision.
- Existing rules stand: per-family only, no blended aggregate, floors respected (`--min-n`,
  `--min-matches` are **not** to be lowered to make numbers appear), `implied%` visible, an empty
  family shows `-`.

`backtest_pool_legs.csv` has no kickoff date, so this needs a new `kickoff_date` column. Appending a
new field against the existing header would misalign every retro row, so the file gets a **tested
one-time migration** that back-fills the column for existing rows from their run matrices, and the
writer refuses to append when header and row shape disagree.

## 6. Architecture

Python owns selection, validation and settlement; the agent owns the browser fetch. Cloudflare
blocks plain HTTP, so the fetch cannot live in Python — but everything that can be tested does.

| unit | responsibility |
|---|---|
| `backlog.py` (new) | `backlog_selections` (walk unsettled runs, `exclude_inplay`, gate); `dedupe_selections` (the invariant); `is_named_competition` (the 29% exclusion); `worklist_by_date` |
| `output/scores_cache/<YYYY-MM-DD>.csv` | verified results, one file per date, append-only. Same schema as the existing scores CSV plus provenance. **Resumability lives here**: a fixture already cached is never re-fetched, so the worklist shrinks and the job survives across sessions. |
| `settle.py` | unchanged grader; `--pool` gains dedupe + `kickoff_date` |
| `calibrate.py` | gains `n_dates` |

Retro rows are **observations, not bets** — they go to `backtest_pool_legs.csv` with `source=pool`
and never to `backtest.csv`, because no slip was ever placed on them. Their `run_dir` is written as
`backlog_<kickoff-date>` so `--by-run` shows one column per match-day rather than 28 near-duplicate
run columns, and retro rows stay visibly distinct from live slates.

## 7. Execution shape

1. Build and test the Python units.
2. Migrate the pool legs schema.
3. Browser fetch per date into the score cache, with the 100% self-check applied at write time.
4. Verification sampling at the stated rates.
5. **Settle to a throwaway path and present the join report** — matched/unmatched, alias list,
   self-consistency failures, dedupe counts. **STOP.** This is the last reversible moment; a report
   that takes 60 seconds to read is cheap against a dedupe or alias error propagating into every
   number the project produces from here.
6. On approval only: load for real, report per-family n_legs/n_matches/n_dates/gap/roi with floors
   applied, plus `--by-run` reversal detection across the full history, and append to
   `docs/CALIBRATION-LOG.md`.

## 8. Expected outcome

Stated in advance so it cannot be rationalised afterwards: **the most likely honest result is that
every family converges near zero**, because eljam3ia prices these markets roughly correctly. That
is a real finding and gets reported as plainly as a positive one would.

Expect more reversals at scale — `1st half` already went +6.4 → −6.0 and `htft` +28 → −0.9.
Reversals are the system working.
