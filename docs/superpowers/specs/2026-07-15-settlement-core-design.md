# Settlement Core — Design (Sub-project 2, provider-agnostic core)

## Context

The betslip pipeline produces two sets of booking codes per run (SET A ≤50 all-odds, SET B ≤25
diversified) with a predicted win%. The user wants to **score two trackers** — SET A `0..50` and
SET B `0..25`, +1 per winning slip — and **log data for backtesting**. Investigation
([2026-07-15-subproject2-settlement-feasibility](2026-07-15-subproject2-settlement-feasibility.md))
established that the site API exposes **no match results**, so settlement needs match outcomes from
elsewhere.

This spec covers the **provider-agnostic core**: everything except the automated results fetch. It is
usable immediately by feeding a hand-entered scores CSV; a real results/stats adapter plugs into a
defined seam later. Score grading in v1 covers only **full-time, score-derivable markets**; stat and
half-split markets return `unsettleable`.

Reality check (documented, accepted): 20-leg accumulators at 1.25–1.50 win ~never, so both trackers
will read near zero. The backtest's value is empirical measurement, not hitting a target.

## Architecture

New module **`settle.py`** (settlement is its own responsibility; scanner/builder untouched). Pure
functions for parsing + grading; thin I/O around them; a CLI to run it.

### Data types
- `MatchOutcome`: `{match: str, home: int, away: int, ht_home: int | None, ht_away: int | None}`.
  v1 grading uses `home`/`away` (full time); `ht_*` reserved for half markets (future).
- `Leg`: `{league, match, market, selection, odd: float, novig_prob?}` (from the betslips file).
- `Slip`: `{set: "A"|"B", label, code, pred_win_pct: float, legs: list[Leg]}`.

### Functions (pure, TDD)
- `parse_betslips(text) -> list[Slip]` — parse a `betslips_*.txt`: section headers (`SET A`/`SET B`)
  → set; `BETSLIP <label> (... win% <x> ...)` → label + predicted win%; `>> BOOKING CODE: <c>` →
  code; leg lines `  N. <league> - <match> - <market>: <selection> @ <odd>` → legs.
- `read_outcomes_csv(text) -> dict[str, MatchOutcome]` — columns `match,home,away[,ht_home,ht_away]`,
  keyed by exact match string (matches the betslips `match` field). Header row optional.
- `grade_leg(market: str, selection: str, o: MatchOutcome) -> "won"|"lost"|"void"|"unsettleable"` —
  dispatch on market. **v1 handles (full-time, score only):** `1x2`, `Total` (Over/Under goals),
  `Both Teams To Score`, `Double chance`, `Correct score`, `Multigoals`, `Draw no bet`, `Handicap`
  (goal handicap). ANY market whose name contains a stat/half/combo marker
  (`corner|booking|card|shot|tackle|offside|foul|1st half|2nd half|halftime|half-time| & |odd/even`)
  or is otherwise unrecognized → `unsettleable`. `void` for exact-line pushes (e.g. `Total: Over 2`
  with 2 total goals; whole-number handicaps landing on the line).
- `grade_slip(slip: Slip, outcomes) -> "won"|"lost"|"ungradeable"` — `ungradeable` if any leg is
  `unsettleable` or its match is absent from `outcomes`; else `won` iff every leg is `won` (treating
  `void` legs as non-losing / removed); else `lost`.
- `settle_run(slips, outcomes) -> RunResult` — per set: `won` count (the tracker score, ≤50 / ≤25),
  `gradeable` count, `total` count. Returns the two scores + per-slip verdicts.

### Results seam (future adapter)
`class ResultsSource(Protocol): def outcomes_for(self, slips) -> dict[str, MatchOutcome]: ...` and a
`NoResultsSource` returning `{}` (everything ungradeable). A football-data.org / API-Football adapter
implements this later; the CLI's `--outcomes csv` path bypasses it for now.

## Data flow

`betslips_*.txt` + `scores.csv` → `parse_betslips` / `read_outcomes_csv` → `grade_slip` per slip →
`settle_run` tallies trackers → append one row per slip to a persistent `backtest.csv` and print the
two tracker scores.

## Output

- **Console:** `SET A: 3/12 gradeable won -> tracker 3/50` and `SET B: 0/2 gradeable won -> tracker
  0/25` (won / gradeable, then the capped tracker score), plus each slip's verdict.
- **`backtest.csv`** (appended, `utf-8-sig`): `settled_at, run_dir, set, code, legs, pred_win_pct,
  verdict, gradeable_legs, won_legs`. One row per slip; accumulates across runs for analysis.

## CLI

`py settle.py <betslips_*.txt> --outcomes scores.csv [--backtest output/backtest.csv]`
(default backtest path `output/backtest.csv`). Prints trackers; appends rows.

## Error handling

- A leg whose match is missing from outcomes → its slip is `ungradeable` (not an error).
- Malformed scores row → skip with a note. Missing betslips/outcomes file → clear error, exit 1.
- Never raise on an unknown market — return `unsettleable`.

## Testing

Pure unit tests with synthetic outcomes: e.g. `MatchOutcome("A vs. B", 2, 1)` →
`1x2:1`=won, `1x2:2`=lost, `Total:Over 2.5`=won, `Total:Under 2.5`=lost, `Total:Over 3`=void,
`Both Teams To Score:Yes`=won, `Double chance:1 or draw`=won, `Correct score:2:1`=won,
`Multigoals:1-3`=won, `Draw no bet:2`=lost, `Handicap:2 (+1.5)`=won, `Total corners:Over 8.5`=unsettleable.
Plus `parse_betslips` on a small dual-set fixture, `read_outcomes_csv`, and `settle_run` tally
(a fully-graded SET A slip that won → tracker +1; a slip with an unsettleable leg → ungradeable).

## Out of scope (future sub-projects)
External results/stats adapter (provider choice + API key + fixture matching); half-based markets
(need `ht_*`); stat markets (corners/cards/shots/tackles/offsides/fouls — need a stats provider);
combo markets (`X & Y`); team totals; win-to-nil/clean-sheet; any tuning toward a target win rate.
