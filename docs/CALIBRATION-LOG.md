# Calibration log

The project's measurement record: one entry per settled slate, plus the running combined table.
This is the only place per-family numbers are quoted as results. Append, never rewrite — the point
of the log is that you can see a gap reverse.

Source of truth is `output/backtest_pool_legs.csv` (git-ignored). Reproduce any row with:

```bash
py calibrate.py --legs output/backtest_pool_legs.csv --by-run
```

`--by-run` is the important half. The combined table averages slates together, which is exactly
where a fluke hides; the per-slate columns are what make a **reversal** visible.

---

## The arithmetic of the stated goal ("15/25 slips correct")

Settled before reading any table, because it bounds what the data could ever deliver.

A 4-leg slip whose legs each hit with probability `p` wins with probability `p⁴`. For 15/25 = 60%:

| legs | required per-leg hit | fair odds for that leg | inside the 1.25–1.50 window? |
|---|---|---|---|
| 4 | 88.0% | 1.14 | **no** |
| 3 | 84.3% | 1.19 | **no** |
| 2 | 77.5% | 1.29 | yes |
| 1 | 60.0% | 1.67 | no (too long) |

**15/25 is unreachable with 4-leg slips in this odds window** — it needs 88% legs, and an 88% leg
prices at 1.14, far below 1.25. It IS reachable with **2-leg** slips at ~1.29 a leg.

But reaching it wins nothing. Two 1.29 legs combine to 1.66; hitting 60% of them returns
`0.60 × 1.66 = 0.996` per unit staked — **break-even by construction**, because a correctly priced
1.29 leg hits 77.5% by definition. Raising the hit rate by shortening the odds cannot make money;
it just moves the same expectation into a different shape.

**Money comes only from `gap = hit% − implied%` being positive**, which is what this log tracks.
`roi%` is that gap expressed as profit per unit staked. Hit-rate targets and money targets are
different targets, and only one of them is achievable by choosing slip structure.

---

## Slate 1 — `run_20260731_0039`, settled 2026-08-01

21 of 22 fixtures scored (Anzoategui–Tachira: no result published, row deleted).
544 graded pool observations. Slips: 2/24 gradeable won.

## Slate 2 — `run_20260801_1007`, settled 2026-08-03

41 of 42 fixtures scored (**Deportes Limache–Ñublense postponed**, row deleted — confirmed
independently by ESPN's `chi.1` scoreboard, status `Postponed`).
931 graded pool observations. Slips: 5/21 gradeable won.

Scores read from worldfootball.net match reports via the browser (§5 of the handoff). Every row
self-checked: stated HT agrees with the goal minutes. No `pso` markers on any fixture. Eight rows
spot-verified against ESPN's API (FT **and** goal minutes, so HT was independently re-derived),
including the full 7-goal sequence of Everton 3–4 Colo Colo — the shape that produced the shootout
trap on slate 1.

---

## Backlog retro-settlement — loaded 2026-08-03

**This is the entry that answers the project's question.**

432 fixtures retro-settled from 21 match-days across the previously unsettled backlog, taking the
pool from **62 → 481 graded matches** and 1,475 → **8,901 graded observations**. Design and method:
[`2026-08-03-backlog-retro-settlement-design.md`](superpowers/specs/2026-08-03-backlog-retro-settlement-design.md).

Provenance, stated plainly:

- 2,508 finished backlog fixtures; **611 joined (24.4%)** — 602 unique-exact, 9 orthographic
  aliases, 1 ambiguous **rejected**, 1,896 unmatched **skipped**. The low rate is worldfootball's
  coverage, not a matching failure: whole competitions score zero (U20 Paulista, Kolmonen, Primera
  C, USL League Two, China League 2, Calcutta Premier).
- 100% of fetched reports validated for internal consistency; **432 verified, 178 rejected** —
  including **13 penalty shootouts** (the headline score is not the result) and 13 fixtures whose
  own published FT or HT contradicts their goal timeline.
- Independent cross-check against fotmob: 29 sampled (8 aliases = 100%, 21 random = 5.0%),
  **20 checked, 20/20 agreement**, 9 not carried by the second source and recorded as NOT CHECKED.
  Full-time only — half-time is corroborated by the internal goal-minute check, not re-read.
- **Zero duplicate triples** across all 14,363 rows, verified on the loaded file. 1,846 stale
  `unsettleable` rows were purged and replaced by real measurements.

### Cluster-robust result (clustering on match-day)

Legs cluster in matches and matches cluster in dates, so the band is computed between match-days —
the conservative reading, not the flattering one.

| family | legs | dates | gap | ±band | roi% | ±band | verdict |
|---|---|---|---|---|---|---|---|
| 1st half | 2140 | 22 | −3.6 | 2.9 | −5.1 | 4.1 | **clears** |
| or-combo | 1973 | 21 | −4.0 | 1.4 | −5.6 | 1.9 | **clears** |
| main | 1580 | 22 | −6.0 | 2.5 | −8.4 | 3.5 | **clears** |
| 2nd half | 1377 | 22 | −4.9 | 2.9 | −6.7 | 4.1 | **clears** |
| combo | 753 | 22 | −7.4 | 3.5 | −10.6 | 4.9 | **clears** |
| both halves | 725 | 22 | −3.6 | 3.3 | −5.0 | 4.6 | **clears** |
| htft | 170 | 22 | −6.3 | 8.7 | −8.2 | 11.9 | noise |
| multigoals | 111 | 20 | −5.6 | 9.3 | −7.3 | 12.3 | noise |

**Six of eight families now clear their band, and every single one is negative.** No family is
positive at any sample size. The measured loss of −5% to −11% per unit staked is the bookmaker's
margin, intact and now visible.

This is exactly the outcome §9 of the design committed to in advance, written before the data
existed: *"the most likely honest result is that every family converges near zero, because
eljam3ia prices these markets roughly correctly."*

### `both halves` — the edge that wasn't

The only family positive in both live slates (+3.2, +2.1) reads **−3.6 / roi −5.0 over 374
matches**, and clears its band on the negative side. Per-slate it is negative in 8 of the 12 slates
that qualify. The project's single edge candidate did not survive a 6× larger sample.

Per-slate signs across every qualifying slate (`--by-run`):

| family | qualifying slates | gap > 0 | gap < 0 | history |
|---|---|---|---|---|
| 1st half | 16 | 5 | 11 | reversed |
| or-combo | 15 | 3 | 12 | reversed |
| main | 15 | 2 | 13 | reversed |
| 2nd half | 14 | 3 | 11 | reversed |
| combo | 12 | **0** | 12 | stable − |
| both halves | 12 | 4 | 8 | reversed |

## Running table

`gap` = hit% − implied% (points). `roi` = flat-stake profit per unit. `m` = distinct matches.
The 95% band is computed on **matches**, not legs: legs on one fixture resolve off one scoreline.

Reproduce with `py calibrate.py --legs output/backtest_pool_legs.csv --by-run`.

| family | slate 1 (m=21) | slate 2 (m=41) | combined | 95% band | history |
|---|---|---|---|---|---|
| main | −6.1 / roi −8.7 | −8.8 / roi −12.6 | **−7.7 / roi −11.1** (m 62) | ±11.8 | stable − |
| 1st half | +6.4 / roi +8.5 | −6.0 / roi −8.6 | −1.2 / roi −2.0 (m 62) | ±11.4 | **reversed** |
| or-combo | +1.4 / roi +1.5 | −4.8 / roi −6.6 | −2.5 / roi −3.6 (m 57) | ±11.9 | **reversed** |
| 2nd half | −7.4 / roi −10.3 | −0.4 / roi −0.7 | −2.7 / roi −3.9 (m 55) | ±12.0 | stable − |
| combo | −3.9 / roi −6.7 | −5.3 / roi −7.8 | −4.8 / roi −7.4 (m 57) | ±12.3 | stable − |
| both halves | +3.2 / roi +3.2 | +2.1 / roi +3.1 | **+2.5 / roi +3.1** (m 58) | ±11.2 | **stable +** |
| htft | *withheld* (m 12) | *withheld* (m 16) | +11.0 / roi +15.7 (m 28) | ±14.0 | insufficient |
| multigoals | *withheld* (m 6) | *withheld* (m 7) | −15.7 / roi −20.1 (m 13) | ±26.4 | insufficient |

**Nothing is significant. Every gap sits inside its own noise band.** That is the correct result at
62 matches and was predicted in advance.

Per-slate cells are floored independently (20 graded legs AND 5 matches), which is why `htft` and
`multigoals` print `-` in both columns even though they clear the floors once pooled. A slate under
the floor is not evidence, so it cannot be used to say a gap held *or* broke.

### What slate 2 actually bought

Not a signal — a **falsification**. Two families changed sign:

- `1st half` **+6.4 → −6.0** — slate 1's best *reportable* family, gone.
- `or-combo` **+1.4 → −4.8**.

And the most attractive number the project has ever produced was never reportable at all: `htft`
sat at **+28.0 gap / +38.9 roi** on slate 1 off just 13 graded legs across 12 matches, then **−0.9**
on slate 2. The floors withheld it both times. Its combined **+11.0 / roi +15.7** is the average of
a fluke and a nothing, and `history: insufficient` is the tool refusing to dress that up as an edge.

Had the floors not existed, `htft +28 / roi +39` would have been reported as a finding on 2026-08-01
and this slate would have been spent chasing it.

### The two things worth watching

- `main` — negative in both slates and the largest negative (−7.7 / roi −11.1 over 62 matches), at
  two-thirds of its band. Most likely to clear first, in the unprofitable direction.
- `both halves` — the **only** family positive in both slates (+3.2, +2.1), and the only candidate
  for a real edge. Combined +2.5 / roi +3.1 — under a third of its own error bar, so nothing yet.

Note `2nd half` moved −7.4 → −0.4: the magnitude collapsed but the sign held, so it reads
`stable −`. Direction stability is a weak signal; it is not significance.

### Sample runway

| after | matches | 95% band |
|---|---|---|
| slate 1 | 21 | ±19pp |
| **slate 2 (now)** | **62** | **±11pp** |
| ~4 more slates | ~180 | ±6.6pp |
| ~10 more slates | ~370 | ±4.6pp |

A real bookmaker margin of 8–11pp becomes detectable somewhere around 180–250 matches. At the
current rate (~41 matches per slate) that is **4–5 more slates**. Nothing in the code needs to
change to get there; the work is mechanical.
