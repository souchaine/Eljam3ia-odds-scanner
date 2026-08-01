# Stats-Provider Integration — Design (settle.py `ResultsSource`)

## Status

**BLOCKED — no free or public source covers this dataset (tested 2026-07-31).** The free-tier gate
that earlier versions of this spec proposed is withdrawn: see "Provider evaluation" below for what
was actually tried and measured. The *design* (seam, name-matching, caching, invariants) remains
valid and buildable the day a source with adequate coverage exists — only the provider choice is
dead, not the architecture.

**This does not block the project.** Manual settlement of a daily slate needs no provider and is
what produces the project's first real numbers; the provider only ever unlocked the historical
backlog multiplier.

Plan half of this SDD cycle: `docs/superpowers/plans/2026-07-29-stats-provider-integration.md`.

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

## Provider evaluation — TESTED 2026-07-31, not researched

The free-tier plan in the original version of this spec is **withdrawn**. It was built on an
assumption that did not survive contact with the APIs, and on a second assumption that was simply
wrong. Both are recorded here so they are not re-proposed.

**Withdrawn assumption 1 — "free tier is past-seasons-only, which is fine because our fixtures are
historical."** This conflates *already played* with *in a season the free tier permits*. Every
backlog fixture is from July 2026, which sits in a **currently-running** season for these
competitions (Liga Profesional and Brasileiro Feb-Dec 2026; Eliteserien Mar-Nov; Ekstraklasa and the
UEFA competitions 2026-27, just started). A match played last week is still in the current season.
The restriction is therefore probably fatal, not irrelevant. It could not be confirmed: api-football
pricing and the v3 docs both return HTTP 403 to automated fetches.

**Withdrawn assumption 2 — that a free key was in hand.** Tested directly, two requests:

| endpoint | result |
|---|---|
| `v3.football.api-sports.io` (direct) | HTTP 403 — "Invalid API key" |
| `api-football-v1.p.rapidapi.com` (RapidAPI) | HTTP 403 — "You are not subscribed to this API" |

Those two together are conclusive: RapidAPI returns *not subscribed* only for a VALID key whose
account lacks that API, while an unrecognised key gets *invalid key*. The key is a RapidAPI key on
an account with no API-Football subscription, and is not a direct API-Sports key at all.

### Coverage measured against the REAL backlog, per source

Backlog = played, in-play-clean fixtures across the 26 historical matrices: **2,818 fixtures /
39,728 gate-eligible selections**.

| source | key needed | half-time scores | backlog coverage | verdict |
|---|---|---|---|---|
| API-Sports / API-Football free | yes | yes (`score.halftime`) | all competitions *in principle* | **blocked** — no subscription; season restriction unverified and probably fatal |
| Sportmonks free | yes | yes | **36 fixtures (1.3%)** — Danish Superliga + Scottish Premiership only, and even that is an upper bound on ambiguous league names | no |
| apifootball.com | yes | **yes** — `match_hometeam_halftime_score` / `match_awayteam_halftime_score` confirmed in its docs | free-tier league coverage undocumented; untested | only untested candidate |
| **public / keyless** (openfootball, TheSportsDB, OpenLigaDB) | **no** | openfootball schema shows `ft` only; HT unconfirmed. TheSportsDB is crowd-sourced (accuracy risk). OpenLigaDB is German-only | **32 fixtures (1.1%)** | no |

### Why public APIs cannot serve this backlog

openfootball covers the top divisions of England, Germany, Spain, Italy and France. Our backlog is
not made of those. Its actual composition:

```
 707  League 2932            <- unnamed/obfuscated competition
  69  UEFA Conference League
  49  League Cup
  49  U20 Paulista
  43  Regional Football Leagues
  33  Kolmonen                <- Finnish 3rd tier
  31  Premier League          <- the ONLY openfootball-covered league present
  31  League 11070
```

Even the 32 "covered" fixtures are doubtful: our `Bundesliga` entries are the **Austrian** league
(LASK vs Grazer AK), which openfootball does not carry, and `Premier League` is ambiguous across
countries. Real coverage is at or near zero.

**The binding constraint is the BACKLOG's composition, not the providers.** Free and public sources
cover major leagues; this dataset is dominated by obscure ones because the scanner takes whatever
eljam3ia lists on the day. No amount of provider-shopping fixes that.

### What follows

1. **Retro-settlement of the full 2,818-fixture backlog is not reachable** by any free or public
   source. It would need a paid tier with broad coverage, and even then the 707-fixture `League
   2932` block may be unidentifiable.
2. **The tier-1 subset (246 fixtures / 9,607 selections) remains the only tractable target**, and
   needs a paid tier or patient manual lookup.
3. **apifootball.com is the one untested option.** It publishes half-time fields, which is the
   requirement that matters most (53% of legs need HT). One request against the golden record would
   settle it. Note its auth puts the key in a QUERY STRING, which is weaker than a header.
4. **Nothing here blocks the daily path.** A slate built and settled manually needs no provider at
   all, and is what produces the project's first real numbers.

### Golden record for any future provider test

The one hand-verified, independently-sourced result this project owns:

> **Central Cordoba 0-2 Atletico Tucuman, HT 0-0** — Argentine Primera, kickoff 2026-07-31T00:15Z.
> FOX Sports boxscore; goals at 63' and 90+1', internally consistent with a goalless first half.

Any candidate source must reproduce **both** FT and HT before anything is built on it. This exists
because a lookup for this same fixture returned *Atletico Tucuman 1-1 Central Cordoba, 19 July
**2025*** — a different match from a different season, presented as the fixture. Score lookup at
volume is the hard part of any retro plan, and it fails silently.

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
