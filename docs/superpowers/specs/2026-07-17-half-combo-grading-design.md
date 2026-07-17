# Half + Combo Score-Grading — Design (settle.py extension)

## Context

`settle.py`'s `grade_leg` v1 grades 8 full-time score markets; everything else → `unsettleable`.
Measured on a real 75-slip file: only **37% of legs** are gradeable and **0/75 slips** fully
gradeable. The biggest blockers are NOT stat markets but score-derivable ones we simply don't parse
yet — half-goal markets and `A & B` combos:

- `2nd half - multigoals` (127), `1st half - multigoals` (72)
- `Double chance & total X` (~198 across lines), `DC (match) & Nth-half both teams score` (~163)
- `1st/2nd half both teams to score` (33), half clean-sheets/odd-even, `1x2 & total`

All of these are derivable from the **half-time + full-time score** (which `read_outcomes_csv` already
parses as `ht_home`/`ht_away`). This extension adds them. The boundary is strict: **derivable from the
HT+FT score, full stop** — anything whose component is a stat (bookings/corners/shots) or event
(first-goal *scorer*) stays `unsettleable`.

**Accepted caveat:** this is a large per-LEG coverage win (~37% → high-80s%, and much richer
`won_legs`/`gradeable_legs` in `backtest.csv`), but SET B slips stay ungradeable at the SLIP level —
each carries ~3 corners + ~3 carte legs that need a stats provider, and one unsettleable leg blocks a
20-leg slip. The trackers won't move much for SET B; SET A (goal-heavy) is where fully-gradeable slips
may appear. The value is measurement signal, not tracker movement.

## Architecture

A refactor + two thin wrappers, all pure, all in `settle.py`. No new dependencies. `grade_leg`'s
public contract (returns `won|lost|void|unsettleable`, never raises) is unchanged.

### 1. Extract the score core: `_grade_score(key, sel, home, away) -> str`
Grades any score-derivable market given ANY goal pair `(home, away)`. Absorbs today's 8 FT markets
(moved out of `grade_leg`'s body verbatim in behaviour) and adds sub-types the data shows:
- `1x2`, `total` (Over/Under goals), `both teams to score`, `double chance`, `correct score`,
  `multigoals`, `draw no bet`, `handicap` — as today, but operating on the passed `(home, away)`.
- **Double chance normalization:** accept all three notations → the same pair:
  `"1 or draw"|"1x"|"1/x"` → {"1","Draw"}; `"1 or 2"|"12"|"1/2"` → {"1","2"};
  `"draw or 2"|"x2"|"x/2"` → {"Draw","2"}.
- **New score sub-types** (needed by half/combo markets):
  - team total: market like `1 total`/`2 total` → Over/Under on that team's goals (team 1 = home).
  - team clean sheet: `1 clean sheet`/`2 clean sheet`, selection `Yes`/`No` → team kept a clean sheet
    (opponent scored 0). `1 win to nil`, `1 or any clean sheet` are NOT in v1 scope → unsettleable.
  - odd/even: `odd/even` (total goals) or `1 odd/even`/`2 odd/even` (team goals), selection
    `Odd`/`Even`. (This is why `odd/even` must be REMOVED from the unsettleable regex — it is score-
    derivable.)
- Unknown market key or unparseable selection → `unsettleable` (never raise; str-coerce as today).

### 2. Half wrapper (inside `grade_leg`)
Before the unsettleable regex, detect a half prefix on the market name:
- `1st half - <core>` → grade `<core>` via `_grade_score` on `(ht_home, ht_away)`.
- `2nd half - <core>` → on `(home - ht_home, away - ht_away)`.
- If `ht_home`/`ht_away` is `None` (not entered) → `unsettleable`.
- If `<core>` (after stripping the prefix) is itself a stat/event market (`bookings`, `corner`,
  `first corner`, `shot`, ...) → `unsettleable` (handled naturally by `_grade_score` returning
  unsettleable for those keys).

### 3. Combo wrapper (inside `grade_leg`)
If the market name contains `" & "`:
- Split the MARKET on `" & "` into component market names, and the SELECTION on `" & "` into the same
  number of parts. If counts mismatch → `unsettleable`.
- Grade each `(component_market, component_selection)` by recursing into `grade_leg` (so a component
  may itself be a half market, e.g. `"1st half both teams score"` → treat `both teams score` as
  `both teams to score` on the half). Component selection tokens like `"12"`, `"1/2"`, `"under 5.5"`,
  `"no"`, `"No/no"` are graded by the same core.
- Combine with precedence: **`unsettleable` > `lost` > `void` > `won`** (any unsettleable → whole combo
  unsettleable; else any lost → lost; else any void → void; else won).
- `"1st/2nd half both teams to score"` selection `"No/no"`: this market's name has no `" & "`; handle
  it as a dedicated case — split the SELECTION on `"/"` into (1st-half BTTS, 2nd-half BTTS), grade each
  on the respective half score, AND them.

### `grade_leg` dispatch order (important)
1. str-coerce inputs (as today).
2. If market contains `" & "` → combo wrapper.
3. Else if market starts with `1st half - ` / `2nd half - ` → half wrapper.
4. Else if the special `1st/2nd half both teams to score` → its dedicated case.
5. Else if the (now-narrowed) unsettleable regex matches → `unsettleable`.
6. Else → `_grade_score(key, sel, home, away)` (full time).

The `UNSETTLEABLE` regex loses `1st half|2nd half|halftime|half-time| & |odd/even` (now handled or
score-derivable) and keeps only true stat/event markers: `corner|booking|card|shot|tackle|offside|foul`.
Stat markets that were previously caught by the half/combo tokens are still caught by these stat tokens
(e.g. `1st half - total bookings` matches `booking`).

## Data flow

`grade_leg(market, selection, outcome)` unchanged externally. Internally it now reads
`outcome.ht_home`/`ht_away` for half/combo-half markets. `grade_slip`/`settle_run`/backtest are
untouched — more legs simply resolve to won/lost instead of unsettleable, so `gradeable_legs`/`won_legs`
rise and some slips flip from ungradeable to won/lost.

## Error handling
- Missing `ht_*` for a half/half-combo leg → `unsettleable` (not an error).
- Selection/market count mismatch in a combo, or any unparseable token → `unsettleable`.
- Never raise; unknown markets → `unsettleable`.

## Testing (pure, TDD)
Synthetic `MatchOutcome` with HT+FT, e.g. `MatchOutcome("x", 2, 1, ht_home=1, ht_away=0)`:
- Half goals: `1st half - multigoals: 1-3` (1 HT goal → won); `2nd half - multigoals: 1-3` (2nd-half
  goals = (2-1)+(1-0)=2 → won); `2nd half - 2 Clean sheet: No` (home scored in 2nd half → No won).
- Half missing ht: same market with `ht_home=None` → unsettleable.
- Combos: `Double chance & total: 1/2 & under 5.5` (home won → 1/2 covers; 3 goals < 5.5 → both won);
  `Double chance (match) & 1st half both teams score: 12 & no` (home won → 12; away 0 at HT → not both
  scored → "no" won); `1x2 & total: 1 & over 1.5` (won/won); combo where one part loses → lost; combo
  with a corners component → unsettleable; combo with a total push → void.
- `1st/2nd half both teams to score: No/no` on 2-1 (HT 1-0): 1st-half BTTS no (away 0) → won; 2nd-half
  BTTS = home 1 & away 1 → yes, so "no" → lost → slip leg "lost".
- DC notation: `1x2 & total`, `Double chance` in all three notations resolve identically.
- Regression: all existing FT `grade_leg` tests still pass unchanged (score core is behaviour-identical
  for FT).
- Re-measure coverage on the real betslips file: leg-gradeable % rises materially from 37%.

## Out of scope (future)
Stat markets (corners/cards/bookings/shots/tackles/offsides/fouls) and event markets (first-goal
scorer, anytime scorer) — need the external stats provider. `win to nil`, `to win either half`,
exact-goals, and other rarer score markets not seen in volume — add later if they appear.
