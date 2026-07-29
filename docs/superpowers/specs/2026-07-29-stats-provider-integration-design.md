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

**But coverage ≠ stat depth, and the free tier is the gate (see §7).** API-Football's coverage is
per-league AND per-season and is **uneven for South America** — "missing coverage can still return a
successful `200` with an empty array" (their own docs), and lower divisions / smaller confederations
"often return incomplete data — missing lineups, absent player-level stats." Our slates are NOT only
top-flight Argentine Primera; the latest run includes **lower divisions and Venezuelan sides**
(Estudiantes Río Cuarto, Gimnasia Mendoza, Universidad Central de Venezuela) where corner/card/shot
depth is exactly where API-Football is thinnest. Whether the paid tier is worth anything for THIS
project therefore cannot be answered from a coverage page — it must be **probed on the free tier
first** (§7).

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

## 7. Decision gate — the free tier decides whether the spend is worth it

**Do not frame this as "pick a provider now."** The real question a paid stats tier has to answer is
**not** "does it cover the slate" but: *once corners/cards/shots legs actually become gradeable, do
their per-family calibration gaps (hit% − implied%) differ enough from the goals-derived families to
justify paying?* If the stat families calibrate the same as the goals families (the odds are equally
(in)efficient), there is nothing to buy — the ~73% score-derivable measurement already tells the
story. That question is **unanswerable until some real stat legs are graded**, and grading real stat
legs at zero cost is *exactly* what API-Football's free past-seasons tier is for. So the free tier is
the **decision gate**, not one option among three. "Pay live" and "stay score-only" are the two
**post-gate** outcomes.

### Gate step 0 — STAT-DEPTH PROBE (zero cost, blocks everything; a verification gate like the score tranches)

Before endorsing any signup, **prove the free tier actually has the stats for THESE leagues** — not
just that the leagues are listed. With a free key (the user creates it; this design never requests or
enters credentials):
1. Call `/leagues` for each league the corpus actually scrapes and read the per-season **coverage
   flags** (`fixtures.statistics_fixtures`, `fixtures.statistics_players`, `fixtures.events`,
   `lineups`) for the free-accessible past season(s).
2. For a handful of real fixtures in those leagues+season, call `/fixtures/statistics` and
   `/fixtures/players` and **inspect the payload**: are `Corner Kicks`, `Yellow/Red Cards`, `Total
   Shots`, and per-player fields actually **present and non-empty**?

Because a "covered" league can return a `200` with an empty array, the flag alone is not proof — the
sample payload is. **If the target leagues' stat fields are empty/absent on the free tier, the gate
FAILS and the finding is decisive: don't pay** — you can't even validate stat grading here, and the
paid tier for these specific (often lower-division South-American) leagues is the same data source.
Fall through to score-only. Record which leagues passed/failed; coverage is per-league, so a mixed
result means "stats only for the top-flight subset."

### Gate step 1 — validate the grader on free historical stat data

If step 0 passes for a workable set of leagues: build the adapter (plan Tasks 1–4) against the free
historical season, settle a historical stat slate through `settle.py`, and let it write graded stat
legs into `output/backtest_legs.csv`. This exercises name-matching + stat-market grading end-to-end
at zero cost.

### Gate step 2 — read the per-family gaps

Run `calibrate.py` on that historical `backtest_legs.csv`. Now the `corners`, `cards`, `player`
families show **real** hit% vs implied% vs gap alongside the goals families. This is the number the
whole spend decision hinges on.

### Gate step 3 — THEN decide (post-validation branches)

- **Pay for a live tier** *iff* step 2 shows the stat families' gaps are materially different from the
  goals families (there is edge/signal specific to stat markets worth settling on live slates). The
  adapter is identical; only the season/plan key changes.
- **Stay score-only** if step 0 fails (no stat depth for these leagues) OR step 2 shows stat-family
  gaps track the goals families (nothing to buy). This loses nothing already built — the per-family
  calibration on the ~73% score-derivable legs remains the project's measurement, and the stat
  families simply stay `gradeable = 0`.

The only thing that needs the user right now is **a free API-Football key to run gate step 0** (and
the willingness to run the probe). Everything downstream follows from what the probe returns.
