# Stats-Provider Integration — Design (settle.py `ResultsSource`)

## Status

**Design draft — one decision is the user's and blocks implementation** (provider + budget; see
§7). Everything else here is a concrete, buildable design. This document is the brainstorm+spec
half of P2's own SDD cycle; the plan half is `docs/superpowers/plans/2026-07-29-stats-provider-integration.md`.

## Context

`grade_leg` now settles ~73% of legs on a typical slate from the hand-entered HT+FT score alone
(after the score-derivable tranche `ae6b86e` and the P4 both-halves/HT-FT additions). The remaining
~27% are **genuine stat/event markets** — player shots/saves/assists, corners, cards, race-to-N,
first/last goal, scoring type, penalty, 15-minute intervals — that no amount of score parsing can
grade. They need a real results+stats feed. Two things are blocked on that feed:

1. **The stat families** (`player`, `corners`, `cards`, `stat-other`, `interval`) currently report
   `gradeable = 0` in the per-family table and the calibration report. They are the whole reason
   those families exist.
2. **Slip-level grading.** A 20-leg parlay is ungradeable if *any* leg is unsettleable, so as long
   as most slips carry at least one stat leg, essentially no whole slip is gradeable. (The slip
   tracker is already labelled diagnostic-only for exactly this reason, but a real stat feed is
   what would make it real.)

Eljam3ia itself has **no results feed** (memory `eljam3ia-no-results-feed`): finished matches drop
off the widget, live scores exist only in-play. So the feed must come from an **external provider**,
matched back to Altenar's team names. The seam for this already exists in `settle.py`:

```python
class ResultsSource(Protocol):
    def outcomes_for(self, slips: list[dict]) -> dict[str, MatchOutcome]: ...

class NoResultsSource:                       # placeholder
    def outcomes_for(self, slips): return {}
```

## Goal

An adapter that, given a run's slips, auto-fetches **final + half-time scores AND match/player
stats** for each match, so that (a) the stat families grade, and (b) whole slips become gradeable —
without ever *guessing* a score, a stat, or a name match.

## Provider evaluation (researched 2026-07-29; verify live before committing budget)

The slates actually scraped are worldwide but heavily **South American** — the latest run
(`run_20260728_2035`) is almost entirely Argentine: Tigre, Nacional, Santos, Argentinos Juniors,
Estudiantes Río Cuarto, Banfield, Sarmiento, San Lorenzo, Gimnasia Mendoza, … So the binding
question is **free/cheap coverage of Argentine + South American leagues WITH detailed stats**, not
just top-5 European leagues.

| Provider | Free tier | Covers the scraped leagues? | Detailed stats (corners/cards/shots/players)? | Verdict |
|---|---|---|---|---|
| **football-data.org** | 12 competitions; fixtures/results/tables only; 10 req/min | **No** — the free 12 are mostly top-European + Copa Libertadores + Brazil Série A; **Argentine Primera is not in the free set** | **No** — free tier is scores/tables only | Insufficient: neither the leagues nor the stats. |
| **API-Football (api-sports.io)** | 100 req/day, 10 req/min; **season-restricted on free** (historical seasons only, not the current/live season — confirm exact seasons at signup) | Yes — 1,200+ comps incl. Brazil Série A and (paid) Argentine Primera | Yes — fixture `statistics` + player `statistics` endpoints exist on paid tiers | **Best fit, but not free for current slates.** Free tier is good for *grader validation on historical seasons*, not for settling current runs. |
| Sportmonks / TheSportsDB / others | varies | Sportmonks has an Argentine-Primera product; free tiers are typically limited to a couple of European leagues | varies | Evaluate only if API-Football's paid tier is rejected. |

**Decisive finding:** there is **no free tier that settles a current South-American slate with
stats**. football-data.org free lacks both the leagues and the stats; API-Football free lacks the
current season. Real stat-family settlement of current runs requires a **paid plan** (API-Football's
paid tiers start around a few tens of USD/month and include the current season + full stats — verify
current pricing).

**Free path that still has value:** API-Football's free historical seasons let us **validate
`grade_leg` against real scores at zero cost** (feed known historical final/HT scores through the
grader and confirm verdicts) — a correctness check, not a current-slate settlement.

## Design — extend the data, not `grade_leg`'s contract

`grade_leg(market, selection, outcome)` and its `won|lost|void|unsettleable` contract (invariant #1)
must **not** change. Stats arrive as *more data on the outcome*, and stat-market grading is added as
new dispatch branches + classifier entries **in lockstep** (invariant #7), exactly like every prior
tranche.

1. **`MatchStats` alongside `MatchOutcome`.** Add an optional stats payload rather than bloating
   `MatchOutcome`:

   ```python
   @dataclass
   class MatchStats:
       corners_home: int | None = None
       corners_away: int | None = None
       cards_home: int | None = None      # yellow+red as booking points, per market convention
       cards_away: int | None = None
       # player-keyed maps, names already normalized (see §name-matching):
       shots: dict[str, int] | None = None
       shots_on_target: dict[str, int] | None = None
       # ...extended per stat family, each field independently Optional
   ```

   Any field left `None` means "provider did not supply it" → the dependent leg stays
   `unsettleable` (never a guessed 0). This mirrors how a missing `ht_*` already forces half/HT-FT
   legs to `unsettleable`.

2. **Widen the seam** so a source can return scores and stats together:

   ```python
   class ResultsSource(Protocol):
       def outcomes_for(self, slips) -> dict[str, MatchOutcome]: ...
       def stats_for(self, slips) -> dict[str, MatchStats]: ...   # NEW; NoResultsSource returns {}
   ```

   `grade_leg` gains an optional `stats: MatchStats | None = None` parameter (keyword, defaulted, so
   every existing call site and test is unchanged). Score-only markets ignore it; stat markets read
   it and return `unsettleable` when it's `None` or the needed field is `None`.

3. **Stat-market grading, added family-by-family in lockstep** (each its own audit-gated commit,
   like the score tranches): corners totals/handicap/1x2, cards totals, player shots/SOT/… Each new
   gradeable market MUST also be added to `_market_family` so the drift-guard property test
   (`test_market_family_property.py`) stays green — it will *fail* if a newly-gradeable stat market
   still classifies as `other`.

## Name-matching — the actual hard part (must never fuzzy-guess)

Altenar's `clean()`-collapsed names (e.g. `"Estudiantes Rio Cuarto"`, `"Universidad Central de
Venezuela"`) will not equal a provider's names. Per invariant #1, an **unmatched name → the match's
outcome is simply absent → every leg on it is `unsettleable`** — never fuzzy-matched to the wrong
fixture (a wrong fixture silently mis-grades, the worst outcome).

Design:
- **Normalize** both sides (casefold, strip accents, drop punctuation/legal suffixes like "CF"/"FC",
  collapse whitespace) to a canonical key.
- **Alias table** (committed, human-curated) mapping Altenar names → provider fixture ids/names for
  the leagues actually scraped. Seed it from a first reconciliation pass over the real corpus.
- **Exact/alias match only.** A normalized key or an explicit alias entry matches; anything else is
  **reported as unmatched and left ungraded** (printed as a diagnostic count, so the alias table can
  be grown deliberately). No Levenshtein/token-overlap auto-accept.
- Providers key fixtures by kickoff date+league too; use the run's scrape date to disambiguate
  same-named fixtures.

## Rate limits, caching, politeness

- API-Football free is **100 req/day**; a 30–40-match slate that needs one fixtures-by-date call
  plus one statistics call per match already approaches that. **Cache aggressively**: one
  fixtures-by-date+league call resolves most matches; fetch per-match statistics once and persist
  the raw JSON under the run dir (`output/run_*/provider/`) so re-settlement never re-hits the API.
- Keep the scraper's politeness ethos: single-thread, backoff/retry, partial-save on error.
- Settlement stays **offline-replayable**: once the provider JSON is cached under the run, `settle.py
  --outcomes` can be regenerated from cache with no network.

## Invariants preserved

- #1 never-guess / validate-then-decide: missing stat field or unmatched name → `unsettleable`.
- #7 grader + classifier extended in lockstep; drift-guard test enforces it.
- #11 settlement input remains a `ResultsSource` (scores CSV stays a valid manual source); the
  provider is one more implementation of the seam, not a rewrite.
- Per-family reporting only, never a blended aggregate; new stat families slot into the existing
  per-family + calibration tables with real numbers once wired.

## 7. The decision that needs the user (blocks build)

**Which provider, and what budget?** This is genuinely the user's call and gates implementation:

- **Option A — pay for API-Football (or comparable) paid tier** (~tens of USD/month): the only way
  to settle **current** South-American slates with stats. Unblocks the remaining 27% + slip-level
  grading for real.
- **Option B — free historical validation only** (API-Football free seasons): validate the grader
  on real historical scores at zero cost; does *not* settle current runs' stat legs.
- **Option C — stay score-only**: keep hand-entered/score-CSV settlement, accept that stat families
  remain permanently `gradeable = 0`, and treat the per-family calibration on the ~73% derivable
  legs as the measurement (still meaningful for the score-derivable families).

Recommendation: **B now, A when it's worth paying.** Wire the seam + name-matching against
API-Football's free historical data first (proves coverage, name-matching, and stat-market grading
end-to-end at zero cost), then flip to a paid key for live slates — the adapter is identical, only
the season/plan changes. Option C loses nothing already built and is a fine indefinite resting point
if the stat families aren't worth a subscription.
