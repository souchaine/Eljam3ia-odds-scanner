# Sub-project 2 (settlement + trackers + backtest) — Feasibility Findings

Investigation done 2026-07-15 to unblock the deferred Sub-project 2 (auto-scoring the two trackers —
0..50 for SET A, 0..25 for SET B — and a backtest log toward a target win rate).

## The blocker, now confirmed: the site API has no results

- **No results endpoints.** `GetResults`, `GetResultsBySport`, `GetLiveScore`, `GetEventResult`,
  `GetSportResults`, `GetResultsMenu`, `GetResultGames`, `GetEventStatistics` all return 404. Only
  `GetLiveOverview` responds (live/in-play structure). Alternate hosts (`sb2results-*`,
  `sb2statistics-*`) do not respond for this integration.
- **Finished matches disappear.** `GetEvents` returns only upcoming events, so a played match cannot
  be re-queried for its score afterwards.
- **Live scores are in-play only.** `GetLivenow`/`GetLiveOverview` carry a live `sc` score while a
  match is running; it vanishes at full-time. The site has no Results/history UI.

## What settlement actually requires

Booking codes are not bets, so nothing gets "graded" for us — we must grade each leg ourselves from
match outcomes. Our qualifying markets span: goals (1x2, totals, BTTS, double chance, correct score,
multigoals, HT/FT) **and** detailed stats (corners, cards/bookings, shots, shots on target, offsides,
tackles, fouls), plus many 1st-half / 2nd-half splits. Grading the stat families needs per-match
statistics, not just the final score.

## Two viable paths (decide first when we design Sub-project 2)

1. **External results + stats API (recommended, required for full coverage).** Pull final scores AND
   per-match stats from a football data provider (e.g. football-data.org — free tier, scores +
   basic; API-Football/API-Sports — richer stats incl. corners/cards/shots, free tier with limits).
   Build: (a) a fixture-matching layer mapping our event (team names + kickoff UTC) to the provider's
   fixture; (b) per-market grading rules; (c) a settle step that reads a run's `betslips_*.txt`, grades
   each leg, marks each slip win/loss, updates the two tracker scores, and appends to a backtest CSV.
   Cost: an API key + a real dependency + name-matching fuzz (team-name normalization across sources).
2. **Live-score poller (limited).** Snapshot `GetLivenow` through match windows to record final goals.
   Grades only score-derived markets (1x2, totals, BTTS, DC, correct score, multigoals, HT/FT if half
   scores captured); **cannot** grade corners/cards/shots/tackles/offsides — which are much of SET B.
   Also fragile: the machine must poll continuously across every match.

## Recommendation

Path 1. Score-only grading (path 2) would leave a large share of legs — especially the corners/carte
and other stat families that SET B deliberately diversifies into — permanently ungradeable, so the
trackers/backtest would be biased and incomplete. When Sub-project 2 is brainstormed, the first
decision is choosing the external provider (coverage vs free-tier limits vs stat depth), then the
fixture-matching approach.

Also keep the win-rate reality in view (already established): 20-leg accumulators at 1.25–1.50 have
~0.0001%–2e-9 model win probability, so both trackers will sit near zero regardless of the settlement
source. The backtest's real value is empirical: showing how win rate rises only as slip length falls.
