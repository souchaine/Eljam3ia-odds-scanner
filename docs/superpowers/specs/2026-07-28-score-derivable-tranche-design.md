# Score-Derivable Coverage Tranche — Design (settle.py)

## Context

After the half+combo work (`383de8d`), `grade_leg` grades ~603/1500 legs on a real slate. Of the 897
still `unsettleable`, roughly 255 are derivable from the HT+FT score we already read; the rest need a
stats provider (player shots/saves, corners, cards) or goal timing (15-minute intervals, first/last
goal) and stay out of scope.

This extension adds the derivable ones in **two audit-separated commits**, plus per-family reporting.

**Success metric change:** the slip-level tracker is NO LONGER a success metric. A 20-leg parlay is
near-information-free regardless of coverage. Success = per-family hit rate with per-family n.
Never report a blended aggregate — the score-derivable subset is a biased sample of leg types.

## Verification gates (completed before design was finalized)

Run against real data; findings are binding on the design.

**Gate 1 — multigoals buckets.** 21,618 selections sampled across all runs (betslips + matrices):
21,585 closed ranges (`0-1`..`3-7`), **`"No goal"` x18** on `1|2 multigoals`, **`"4+"` x15** on plain
`multigoals`. A naive `split("-")` is therefore WRONG. `"4+"` affects already-shipped code (current
regex doesn't match it -> `unsettleable`: safe but a live coverage gap; close it here).

**Gate 2 — handicap direction.** Verified against the full UNFILTERED live ladder for one event
(`FC Kairat Almaty vs. Omonia Nicosia`):

| bet `1` | odd | bet `2` | odd |
|---|---|---|---|
| `1 (2:0)` | 1.0667 | `2 (0:2)` | 1.1819 |
| `1 (1:0)` | 1.3077 | `2 (0:1)` | 1.625 |
| `1 (0:1)` | 4.2 | `2 (1:0)` | 7.5 |
| `1 (0:2)` | 10.0 | `2 (2:0)` | 17.0 |

Odds fall monotonically for `1` as the FIRST number rises and for `2` as the SECOND rises =>
**`(a:b)` = home-start : away-start; leading token = bet side.** CONFIRMED, not assumed.

**`Draw (a:b)` exists as an explicit selection** (`Draw (1:0)` @ 4.5, `Draw (0:1)` @ 3.75, ...). Each
`(a:b)` line is its own complete 3-way market: per-line `sum(1/p)` = 1.120 for both `(1:0)` and
`(0:1)` (~12% margin). => **equality after the handicap is a `Draw` WIN, never a void.** This is the
opposite of the existing Asian-style `handicap` market, which voids on equality. Encoding a push here
would mis-grade every such leg.

**Gate 3 — ft cumulative.** `MatchOutcome(home, away)` is full-time CUMULATIVE (includes 1st-half
goals); `_half_score` derives 2nd half = FT - HT. Discriminating case, to be locked by a test:
`MatchOutcome(2, 1, ht=1-0)` + HT/FT `"1/1"` -> HT result `1`, FT result `1` -> **won**; if FT were
mistakenly 2nd-half-only `(1,1)` the FT result would be `Draw` -> lost.

## Architecture

Same pattern as the half/combo work. No new module, no new dependency, all derivation from
`MatchOutcome`. `grade_leg`'s contract is unchanged: returns `won|lost|void|unsettleable`, never
raises.

### Phase 1 (commit 1): low-ambiguity block + per-family reporting (~150 legs)

**Extend `_grade_score(key, sel, home, away)`** — these inherit half-prefixing through the existing
`_grade_on_half` for free (`2nd half - handicap 1X2`, `1st half - 2 exact goals`):

- **team multigoals** — keys `1 multigoals` / `2 multigoals`. Selection forms (per Gate 1):
  `"N-M"` -> team goals in `[N, M]`; `"N+"` -> team goals >= N; `"No goal"` -> team goals == 0.
  Anything else -> `unsettleable`. Apply the same three forms to the EXISTING plain `multigoals` key
  so `"4+"`/`"No goal"` stop being a coverage gap there.
- **team exact goals** — key `N exact goals` (seen as `1st half - 2 exact goals`), selection `"0"`,
  a bare integer -> team goals == that integer.
- **team to score** — key `N to score` (seen as `1st half - 2 to score`), selection `Yes`/`No` ->
  team goals > 0.
- **handicap 1x2** — NEW branch, distinct from `handicap`. Selection `"S (a:b)"`, `S` in
  `{1, 2, Draw}`. `adj_home = home + a`, `adj_away = away + b`; result = `1`/`2`/`Draw`;
  won iff result == S. **No void** (Gate 2).

**New `grade_leg` dispatch branch for HT/FT.** These need BOTH ht and ft, so they cannot live in
`_grade_score` (which sees one goal pair). New helper `_grade_htft(o, sel, dc=False)`:
- `Halftime/fulltime`, selection `"1/1"` -> HT result AND FT result (FT cumulative, Gate 3).
- `DC Halftime/ DC Fulltime`, selection `"X2/X2"` -> HT double-chance AND FT double-chance (reuse
  `_DC_PAIRS`).
- Missing `ht_*` -> `unsettleable`.
- Its `& total` combos (`Halftime/fulltime & total 6.5`, sel `"1/1 & under 6.5"`) already work through
  the existing combo wrapper's recursion — no extra code.

**Per-family reporting.** New `_market_family(market) -> str` classifier + settlement output:
- reports, PER FAMILY: `n / gradeable / won`
- has an explicit `other/unrecognized` bucket so an unanticipated market lands VISIBLY rather than
  being force-fit into the nearest family and skewing its n
- emits NO blended aggregate hit rate
- the slip-level tracker stays in the output but is explicitly labelled as not a success metric

### Phase 2 (commit 2): OR-combos (~105 legs)

Landed separately, gated on the parse audit below. Dispatch: market contains `" or "` and no `" & "`
-> `_grade_or(...)`. Two grammars, each with explicit locking tests:

- **Simple OR (93 legs)** — the market carries BOTH legs; the selection is just `"Yes"`:
  `"Draw or under 1.5"`, `"2 or any clean sheet"`, `"1 or both teams to score"`.
  Grade = `(A or B) == Yes`. Handle a bare `"No"` as negation even though none appear in this file.
  Needs an `any clean sheet` sub-type (either side kept a clean sheet).
- **Compound OR (12 legs)** — `"Both team to score or Total 2.5"` with selection
  `"Under 2.5 or no"`. **The selection order is REVERSED relative to the market name**
  (`"Under 2.5"` binds to Total; `"no"` binds to both-teams-score). Bind selection tokens to market
  components **BY TYPE**, not position — positional pairing silently mis-grades. Dedicated locking
  test required.
- Confirm every total line in OR-combos is a half-line (`.5`). If an integer line appears, define and
  test push behaviour before grading it.

## Data flow

`grade_leg(market, selection, outcome)` unchanged externally. `settle_run` gains per-family tallies
alongside the existing per-set tallies; `append_backtest` is unchanged. More legs resolve to
won/lost instead of `unsettleable`.

## Error handling

Never raise. Unknown market/selection -> `unsettleable`. Missing `ht_*` for any half or HT/FT leg ->
`unsettleable`. Malformed handicap/multigoals/OR selection -> `unsettleable`.

## Testing

TDD, pure functions, synthetic `MatchOutcome` carrying ht+ft. All existing FT/half/combo tests must
pass UNCHANGED (regression). Specific locking tests: ft-cumulative (Gate 3); handicap-1X2 equality is
a `Draw` win NOT a void (Gate 2); multigoals `"No goal"`/`"N+"` (Gate 1); compound-OR reversed-order
type binding (Phase 2).

## Out of scope (stay unsettleable)

All player markets (`shots - <player>`, `shots on goal - <player>`, `saves goalkeeper (<player>)`,
`to score or assist <player>`), `total corners|bookings|shots`, `race to N corners`, `first corner`,
`last corner`, `first goal`, `last goal`, `first scoring type`, `a penalty in the match`,
`15 minutes - ...` intervals, `first goal & 1x2` (non-derivable component), `both halves over`
(1 leg, YAGNI). These need a stats provider or goal timing.
