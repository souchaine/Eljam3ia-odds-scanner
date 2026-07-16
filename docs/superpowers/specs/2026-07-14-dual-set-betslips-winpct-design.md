# Dual-Set Betslips + Win% — Design (Sub-project 1)

> **SUPERSEDED (2026-07-16) — the de-vig approach below was a bug.** This spec's `novig_prob`
> normalized `1/price` over a market's listed outcomes. Altenar bundles many *lines* into one market
> (a "Total" market carries Over 0.5 … Over 3 and every Under), so that denominator sums to ~10
> rather than a real market's ~1.05 — crushing every leg ~10×, producing absurd win% values (~1e-20
> for 20 legs) and, because the bundle size differs per market, breaking monotonicity between a
> slip's win% and its odds. **Shipped behaviour:** `implied_prob(price) = 1/price` and
> `slip_win_pct = 100 × Π(1/price) = 100 / combined_odds`. Do not re-introduce outcome-set
> normalization without first solving line-pairing (e.g. pairing `Over 2.5` only with `Under 2.5`).

## Context

The betslip builder currently produces one kind of output (mixed 20-leg accumulators, up to 50, or
`--per-category` pure-per-family slips). The user wants each run to produce **two labelled sets** of
20-leg booking codes and, for every slip, an honest **win-probability estimate**:

- **SET A — all-odds:** up to **50** twenty-leg slips from the full mixed pool (today's default build).
- **SET B — 7-category diversified:** up to **25** twenty-leg slips where each slip's legs are spread
  across the 7 market families (main, combo DC, 1st half, 2nd half, corners, carte/cards, multigoals).

Both sets, plus a de-vigged win% per slip, must flow through the daily scheduled pipeline. This is
Sub-project 1 of two. **Sub-project 2** (result settlement, the two 0..50 / 0..25 trackers, and the
backtest log toward a 50%-win goal) is a separate design and depends on a match-results data source
that does not yet exist in this codebase — explicitly out of scope here.

### Feasibility caveat (documented, accepted by user)

A 20-leg accumulator wins only if all 20 legs win; its true probability is the product of the legs'
no-vig probabilities. At ~1.40 legs (~68% true) that is ~0.02%; even all-1.25 legs give ~0.5%.
Diversifying SET B across families does **not** change this (it's still a product of 20 probabilities).
So both sets' win% will read tiny, and the eventual trackers will sit far below the 50% aspiration —
this is arithmetic, not a bug. The win% annotation exists precisely to make that visible. Reaching a
high win rate requires far fewer legs; the backtest in Sub-project 2 will demonstrate this empirically.

## Architecture

Two independent slip builders feed one output writer; a pure de-vig function annotates each slip.

### SET A — all-odds (unchanged build)
Reuse the existing `build_slips(pools, size=20, max_slips=50)` on the full per-match selection pool.
No behaviour change from today's mixed mode.

### SET B — `build_diversified_slips(pools, size, max_slips)` (new, pure)
Goal: each 20-leg slip spreads legs across the 7 families, best-effort ("soft" balance), because thin
families (carte ≈ 2 matches, multigoals ≈ 5 on a typical day) cannot supply many legs.

Algorithm (greedy, family round-robin):
- Derive per-category sub-pools from `pools`: for each match, bucket its selections by
  `market_category(s["market_name"])`. A selection belongs to exactly one family (classifier is
  disjoint), so no double-counting.
- To build one slip: iterate the 7 families in `CATEGORY_ORDER` round-robin; on each turn take one
  unused selection from that family, from a match **not already in this slip**, preferring the match
  with the most remaining selections (spreads usage, same spirit as `build_slips`). Skip a family with
  no eligible stock this turn. Continue until 20 distinct-match legs are collected or no family can
  contribute.
- Consume each taken selection (pop from its pool) so, across the whole SET B, **each odd-id is used
  at most once** and a match reused in a later slip spends a different odd — identical reuse invariant
  to `build_slips`.
- Stop when fewer than 2 distinct matches remain with stock; emit at most one trailing partial slip.

Consequence (surfaced): on thin days a SET B slip may not reach a leg from every family — it includes
what the families can supply and fills the rest from abundant families. Full 25×20 is only reached
when the day's slate is rich enough.

### Win% — `novig_prob(selection)` and `slip_win_pct(slip)` (new, pure)
For a selection, compute its **no-vig implied probability** by normalizing across all active outcomes
of its own market:

```
p_novig(sel) = (1 / price_sel) / Σ_over_market_outcomes (1 / price_o)
```

`collect_selections` already holds the market and `odds_by_id`, so it attaches `s["novig_prob"]` at
collection time (the market's outcome odds come from the market's `desktopOddIds`). Then:

```
slip_win_pct = 100 * Π_legs p_novig(leg)
```

Proportional (multiplicative) de-vig is the standard method for evenly-priced markets; it is a simple,
transparent baseline (Shin/power methods are a later refinement, not needed now). Guard against a
missing/zero price by skipping that outcome from the denominator; if a selection has no valid market
sum, its `novig_prob` falls back to the raw `1/price` (over-counts vig slightly, never crashes).

## Data flow

`GetEventDetails` per match → `collect_selections` (now also computes `novig_prob` per selection) →
per-match `pools` → **SET A** via `build_slips`, **SET B** via `build_diversified_slips` → flatten used
odds → `enrich_odds` (only used) → `reserve` each slip → write both sections with codes + win%.

## Output format

One `betslips_*.txt`:

```
Eljam3ia dual-set betslips - built <ts>
window 1.25..1.5, 20 legs/slip; SET A all-odds (up to 50), SET B 7-category diversified (up to 25)

===== SET A: all-odds (N slips, avg win% X) =====
BETSLIP A1  (20 legs, combined odds x836.20, win% 0.021%)
  1. <league> - <match> - <market>: <selection> @ <odd>
  ...
  >> BOOKING CODE: ABC12

===== SET B: 7-category diversified (M slips, avg win% Y) =====
BETSLIP B1  (20 legs, combined odds x742.05, win% 0.034%, families: main x3; corners x4; ...)
  ...
  >> BOOKING CODE: XYZ99
```

Slip header carries combined odds and `win%`; SET B additionally lists the family breakdown so the
diversification is visible. `run_all.py summarize()` lists every `BETSLIP \S+` code under both sets and
reports the per-set count + average win% (its regex was already loosened to `^(BETSLIP \S+.*)$`).

## Daily task integration

The pipeline (`run_all.py`, and thus the 09:00 scheduled task) produces both sets by default — no new
flag needed for the default run. A CLI switch keeps the old single-set behaviours available
(`--set a` / `--set b` / default both), so existing `--per-category`/mixed usages don't break.

## CLI / config

- `make_betslips.py` default (and pipeline default): build both sets (A: 50, B: 25).
- Counts configurable: `--slips-a 50`, `--slips-b 25` (fall back to `MAX_SLIPS`/`SLIPS_B=25`).
- `--set {both,a,b}` to restrict; `--size 20` unchanged applies to both.
- The current `--per-category` (pure-per-family) mode may remain as-is or be folded under SET B during
  implementation — decided in the plan; not a behaviour the user needs both of.

## Error handling

- Reuse existing reserve retry/partial-save + `if not slips: return 1` guard, extended to "no slips in
  either set".
- Thin-family SET B: produce fewer/shorter slips, never crash; note the shortfall in the header.
- `novig_prob` never divides by zero (guarded); win% always renders.

## Testing

Unit (pure, TDD):
- `novig_prob`: a 2-outcome market at 1.90/1.90 → 0.5 each; a 1.40 selection in a market summing to
  1.05 implied → correct normalized value; zero/missing price guarded.
- `slip_win_pct`: product of leg probs (e.g. two 0.5 legs → 25%).
- `build_diversified_slips`: distinct matches within each slip; each odd-id used once across the set;
  family spread is best-effort (given rich pools, a slip draws from ≥ K families); respects size/max.

Live E2E: run the builder; assert SET A up to 50 and SET B up to 25 twenty-leg slips; every slip line
shows a plausible win%; SET B slips visibly span multiple families; round-trip one code (full shape)
and load it in the live betslip UI without the "Oops" crash.

## Out of scope (→ Sub-project 2)

Match-result settlement, the 0..50 and 0..25 trackers, the backtest history log, and any "improve
toward 50%" tuning. Requires investigating whether Altenar exposes results (or adding a results
source) — brainstormed separately after this ships.
