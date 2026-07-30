# Settleable Betslips — As-Built Design (make_betslips.py + settle.py)

**Retroactive spec.** This documents what SHIPPED in `68c17e5` (gate), `88905a4` (lockstep fix +
drift-guard rebuild) and `52bb2a3` (builder, SET A removal, format, void semantics) — not the
pre-implementation design, which was wrong in two places that are called out below as decisions.

## Context

The betslip builder produced two sets per run: SET A (≤50 all-odds 20-leg slips) and SET B (≤25
"7-category diversified" 20-leg slips). Measured against a real slate (`run_20260730_0931`, 3,682
qualifying selections, 148 matches, average odd **1.3774**) both sets failed at their two purposes:

1. **Not winnable.** Win% = `100 / combined_odds`, so a 20-leg slip at the pool's average odd wins
   **0.17%** of the time (1 in 604; 1 in 618 measured on the odds actually selected into slips,
   whose average was 1.379). Observed SET B headers read `win% 0.12`–`0.21`. No amount of formatting
   or randomisation moves this — only leg count does.
2. **Not settleable.** A slip is gradeable only if EVERY leg is. SET B's mandated mix included
   `corners x3` and `carte x1`, which are 0% gradeable from a score, so *every* SET B slip was
   ungradeable by construction — before counting the player props (`Shots - <player>`,
   `Saves Goalkeeper`) that `market_category`'s fallback `main` bucket was silently absorbing
   (only 35/424 of `main` legs were gradeable).

Additionally `build_diversified_slips` was fully deterministic — fixed `CATEGORY_ORDER` walk,
`max()` on the deepest pool, `.pop()` from the end — so every slip shared one structural
fingerprint and repeated the same selections.

The goal: slips that are **winnable** and that **settle today from a scores CSV**, with no paid
stats provider. Those two goals point the same way, because the score-derivable families are
exactly the ones that both grade and are plentiful.

## Verification gates (run against real data BEFORE the design was fixed; all three changed it)

**Gate 1 — the gated pool does NOT skew low-odd.** The approved design assumed filtering to
settleable markets would bias the pool toward short-priced multigoals/DC and depress win%. Measured:
pre-gate average odd **1.3774**, post-gate **1.3843** — the gated pool skews marginally *higher*.
At 4 legs: 27.78% pre-gate vs **27.23%** gated. The 4-leg default therefore survives the gate
unchanged. The assumption was wrong and the design proceeded on the measurement.

**Gate 2 — `grade_leg` never raises across the real vocabulary.** All 6,547 distinct
`(market, selection)` pairs from 48 real matrix runs × 225 representative outcomes = **1,473,075**
`grade_leg` calls: 0 exceptions, every return in `{won, lost, void, unsettleable}` (invariant #1
confirmed empirically, not assumed). Locked by `tests/test_settleable_gate.py`.

**Gate 3 — the gate exposed a live lockstep bug the old drift guard could not see.** Sweeping the
FULL matrices (not betslip legs) found `1 to score` (×9), `2 to score` (×9) and `2 exact goals` (×1)
were gate-ELIGIBLE yet classified `other`. The previous guard's fixture was built from betslip legs,
and the old builder never picked these markets, so the misclassification was invisible. Under the
settleable builder they ARE picked — a latent bug would have become active pollution of the `other`
bucket in `calibrate.py`'s per-family table. Fixed in `88905a4`.

## Design

### 1. The gate lives in `settle.py`, beside the grader

```python
REPRESENTATIVE_OUTCOMES  # 225: every FT 0-4 x 0-4 with every valid HT split (ht <= ft)
is_settleable(market, selection) -> bool   # lru_cached
is_void_capable(market, selection) -> bool # lru_cached
```

`is_settleable` is True iff `grade_leg` yields a REAL verdict (`won|lost|void`) for **every**
representative outcome — never `unsettleable`, never raising.

**Decision: the gate is strictly stronger than "gradeable on some scoreline."** At build time the
outcome is unknown, so eligibility must hold for every outcome the slip could settle against:

- `Both halves over 2` is **excluded**: it grades on most scorelines but returns `unsettleable`
  when a half total lands exactly on the integer line (a push inside a compound, which the grader
  refuses to guess). Build time cannot know which scoreline occurs.
- `Total`/`Over 2` is **included**: it returns `void` on the push, and a push is a real settlement
  outcome, not a failure to grade.

**Decision: the gate is co-located with the grader, not in `make_betslips.py`.** Eligibility is
defined *by* grading, so putting it anywhere else creates a second predicate that can drift — the
exact failure mode that produced the `market_category` (7 families, `carte`) vs `_market_family`
(14 families, `cards`) divergence. `settle.py` imports nothing project-local, so `make_betslips`
importing it creates no cycle. Drift is now structurally impossible rather than merely tested.

**LOAD-BEARING INVARIANT: settlement input always carries half-time scores.** Half, HT/FT and
both-halves markets return `unsettleable` when `ht_home`/`ht_away` are missing, so every
representative outcome supplies them. If a settlement source ever omits HT, this gate becomes wrong
in the *dangerous* direction — it would admit markets that cannot actually be graded. Concretely,
without HT the eligible pool collapses from 1,931 to roughly `multigoals` + a little `main`, since
`1st half` (477), `2nd half` (314), `both halves` (160), `htft` (25) and half-carrying `combo`
selections all fall out. Stated in code as a comment on `REPRESENTATIVE_OUTCOMES`.

### 2. Drift guard: the fixture predicate MUST be the gate

`tests/data/gradeable_markets.tsv` enumerates the **gate-eligible** set over the FULL matrices
(335 pairs); `tests/data/market_vocabulary.tsv` holds all 6,547 pairs for the never-raises sweep.
Both regenerate via `py tests/_gen_gradeable_fixture.py`.

The guard's predicate must match the gate exactly, or it fails in both directions:

| Case | Verdict | Why |
|---|---|---|
| gate-EXCLUDED market classified `other` | **tolerated** | never selectable, never reaches a per-family report (e.g. `Both halves over 2`) |
| gate-ELIGIBLE market classified `other` | **fails** | the builder WILL pick it, it WILL settle, and it pollutes the catch-all bucket in `calibrate.py` |

Using a single probe outcome instead would both miss real bugs (Gate 3) and raise false positives.
Both directions are explicitly tested.

### 3. Builder: random, without replacement, complete slips only

`build_settleable_slips(pools, legs, max_slips, rng)`. Pool = selections passing the gate. Each slip
takes `--legs` legs (default 4), each on a **distinct match** AND a **distinct settle family**; the
remaining pool is reshuffled **per slip** so slips share no structural fingerprint. Selections are
consumed (never reused). Only COMPLETE slips are emitted — when one cannot be filled the builder
stops rather than emit a partial.

**Decision (corrects the approved design): the feasibility rule is**

```
R slips are feasible  iff  sum(min(depth_i, R)) >= R * legs
```

**not** "the ceiling is the depth of the Nth-deepest family (N = legs)." Each slip consumes one
selection from each of `legs` distinct families, so a family contributes at most once per slip —
at most R times across R slips. The Nth-deepest formulation is only the special case where exactly
`legs` families exist. With MORE families than legs a family can sit out some slips, so the true
ceiling is higher: five families of depth 10 support **12** four-leg slips, not 10. Both cases are
test-locked in `test_max_complete_slips_is_bounded_by_shallow_families_not_total_pool`.

Measured on the real slate (gated pool 1,931 selections; depths `1st half` 477, `or-combo` 405,
`main` 360, `2nd half` 314, `combo` 174, `both halves` 160, `htft` 25, `multigoals` 16):

| legs | family-depth ceiling | naive `pool // legs` | overstatement | per-slip win% |
|---|---|---|---|---|
| 4 | 482 | 482 | — | 27.2% |
| 5 | **344** | 386 | 12% | 19.7% |
| 6 | **187** | 321 | **72%** | 14.2% |

The shallow families (`multigoals` 16, `htft` 25) bind first and strand stock in the deep ones. The
builder reports the real ceiling next to the naive figure at build time. The starvation pathology is
tested directly: one deep family (20) + three shallow (2 each) at 4 legs yields exactly 2 complete
slips, no hang, no partial, with 18 selections stranded in the deep family.

### 4. Void semantics — VERIFIED, not assumed

This is the decision most likely to be misread later, so it is stated in full.

**Settlement drops a void leg and re-prices.** `settle._verdict_from` filters voids out and the slip
wins iff every remaining leg won: a 4-leg slip with one push settles as a 3-leg slip.

**The header `win%` is a FLOOR**, defined as P(all `--legs` legs win) = `100 / combined_odds`. When a
leg pushes the slip needs fewer winners, so the realised chance is **higher, never lower**. Traced:
a 4-leg slip at 1.40 shows a floor of **26.03%**; with one leg pushed it settles on 3 legs whose
joint probability is **36.44%**. The floor is not an exact rate and the preamble says so verbatim.
Aligning the displayed number exactly is impossible — whether a push occurs is outcome-dependent and
unknowable at build time — so instead push-capable legs are annotated (`is_void_capable`) and the
rule is stated in the file header.

**`calibrate.py` is NOT affected — verified by trace, not assumption.** Its implied and settled
sides are computed on the SAME leg set:

- `calibrate.py` accumulates `inv_sum`/`inv_n` **inside** the `if verdict in ("won","lost")` branch,
  so a void leg contributes to neither `graded`/`won` (settled side) nor the implied average.
- Discriminating trace: family with `Total Over 2 @2.00 (void)`, `1x2/1 @1.25 (won)`,
  `1x2/2 @4.00 (lost)` → implied **52.50** = mean(1/1.25, 1/4.00). Contamination by the void odd
  would read **51.67**. Removing the void row changes only `n`/`distinct`; `graded/won/hit/implied/
  gap` are identical.
- Structural: `calibrate.py` never references `pred_win_pct`, `slip_win_pct` or `backtest.csv`. It
  consumes `backtest_legs.csv` (per-leg odd + verdict) only. **The slip-level floor never enters the
  hit-vs-implied comparison** — calibrate is per-LEG, the floor is per-SLIP.

Excluding pushes from both sides is also *semantically* correct, not just symmetric: for a
push-refunded bet, fair decimal odds satisfy `d*w + p = 1`, hence `1/d = w/(w+l) = P(win | no push)`
— precisely the estimand `hit%` measures on the non-void subset.

**Push-capable markets in real data are mostly NOT integer-line totals.** The dominant forms are
`Draw no bet` (voids on a draw) and `Handicap: 1 (+0)` (voids on level). Affected families: `main`
**59/360** eligible selections, `1st half` **2/477**; `or-combo`, `2nd half`, `combo`,
`both halves`, `htft`, `multigoals` are all **0**. On the real slate 4 of 25 slips carry the
annotation.

**Known latent trap (documented, deliberately not changed):** `settle.append_backtest` writes the
floor into `backtest.csv`'s `pred_win_pct` column, and nothing reads it back. If a future analysis
compares that column against the observed slip win-rate, push-capable slips would show a **spurious
positive edge** that is pure floor-vs-settled mismatch, not signal. Any such analysis must first
restrict to slips with zero push-capable legs, or recompute the floor on the settled leg set.

### 5. Format and reproducibility

- The section header keeps the literal `SET B` token: `settle.parse_betslips` keys slips off
  `===== SET [AB]` and existing `backtest*.csv` history joins on that letter. Only the
  human-readable remainder changed (`SET B: settleable`). Locked by a round-trip test that generates
  a file and parses it back to `set == "B"` — guarding against silently writing empty `set` values
  into the backtest.
- Odds are **displayed** at 2 decimals (bookmaker style); combined odds and win% are computed from
  **full precision**, and the unrounded `price` is what `reserveBet` receives.
- `--legs` prints the resulting per-slip win% at build time, so raising it surfaces the geometric
  decay immediately (4 → 27.2%, 6 → 14.2%) instead of it being invisible until settlement.
- `--seed` is optional; when unset a real seed is drawn from system entropy and **written to the file
  header**, so feeding it back reproduces that exact file. Tested end-to-end (extract the recorded
  seed from a rendered header, rebuild, compare) — not merely same-seed determinism, because the
  guarantee users rely on is that the *recorded* value is the real one.

## Scope as shipped

- **Deleted:** SET A generation, `--slips-a`, `--set`, and `build_diversified_slips` + its test —
  the latter became unreachable once SET B is gate-driven. Recoverable from git history.
- **Retained:** `build_slips` and `market_category` (+`CATEGORY_ORDER`), still used by the legacy
  `--per-category` mode.
- **Deferred follow-up (named, not done):** reconciling `market_category` (7 families) with
  `_market_family` (14 families). They serve different modes and are separately tested; reconcile
  only if the two reports are ever shown side by side.
- **Out of scope:** the outcomes provider, which stays gated behind P2's free-tier stat-depth probe
  (`2026-07-29-stats-provider-integration-design.md`). Everything here grades TODAY from a scores
  CSV, which is what lets `calibrate.py` produce real per-family numbers with no spend.

## Note: flag removal needs a grep beyond the module

Removing `--set` and `--slips-a` caused two breakages the unit suite could not catch, because it
tests the module while the pipeline **shells into** it:

1. `run_all.py` still forwarded `--set` / `--slips-a` / `--slips-b`, so the full pipeline would have
   died with `unrecognized arguments` on the betslip step. The unit tests import `make_betslips`
   directly and never exercise that subprocess boundary.
2. An argparse `help=` string containing `win%` crashed `--help` with
   `TypeError: %i format: a real number is required` — argparse `%`-formats help text, so a literal
   percent must be escaped `%%`.

**Rule for future flag changes:** grep `run_all.py` and any orchestration wrapper (`run_all.cmd`,
scheduled tasks, README examples) before committing, and smoke-test `--help` on every entry point.

## Verification (real slate `run_20260730_0931`)

- Gated pool: **1,931 / 3,682** selections settleable (52%) across 140 matches, average odd **1.3843**.
- Built 25 slips × 4 legs (seed 1234): all complete, no selection reused, every leg on a distinct
  match and distinct family.
- Round-tripped through `parse_betslips`: 25 slips, all `set == "B"`, **100 legs parsed, 0
  unsettleable, 25/25 slips gradeable**.
- Suite: 170 passed.
