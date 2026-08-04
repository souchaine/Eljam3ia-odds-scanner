# Widening the odds window — design and PRE-REGISTRATION

**Status:** approved 2026-08-03, written BEFORE any wide-window data exists. That ordering is the
point: the prediction, the band edges and the decision rule are all fixed here so they cannot be
chosen after seeing the result.

## 1. Why

Every number the project has produced comes from one fixed window, **1.25–1.50**, set on day one
and never questioned. Within it the answer is now settled and uniform:

> **−6.6% ROI ± 1.8** across 8,829 graded legs / 21 match-days. Every family negative, every odds
> band negative, no market of ≥150 legs with an interval above zero.
> See [`CALIBRATION-LOG.md`](../../CALIBRATION-LOG.md).

That is the signature of an efficiently priced book taking a normal margin, **not** a defect in the
families. `gap = hit% − 1/odd` is negative by construction for any fair book, because `1/odd`
carries the margin; a zero-edge book converges to `gap = −margin`, and that is what was measured.

The existing matrices contain nothing outside 1.25–1.50, so no amount of further analysis of them
can speak to other odds. Favourite–longshot bias — the best-documented inefficiency in betting
markets — lives at the *ends* of the range, and this project has never looked there.

## 2. THE PREDICTION BEING TESTED (pre-registered)

**Favourite–longshot bias predicts that the bookmaker's effective margin is LOWEST at short odds
and RISES monotonically toward longshots.** Bettors systematically over-back longshots and
under-back heavy favourites, so books shade their prices accordingly.

Concretely, over the pre-specified bands below, the hypothesis predicts `roi%` **decreasing**
(becoming more negative) as odds lengthen, with the shortest bands closest to — or above — zero.

### Decision rule, fixed in advance

A positive finding requires **BOTH**:

1. at least one band whose cluster-robust ROI interval sits entirely **above zero**; and
2. the **monotone pattern** — ROI broadly declining as odds lengthen, with the clearing band(s) at
   the SHORT end, not scattered.

**A single band clearing its interval without the pattern is a multiple-comparisons artifact and
must be reported as such, not as an edge.** With 7 bands tested at 95% confidence, roughly one
false positive in three runs is expected by chance alone. This rule is what makes the test survive
that, and it is recorded here so it cannot be relaxed once a tempting band appears.

### What the null looks like

Margin roughly **flat** across all bands — the book is efficiently priced everywhere, and the
1.25–1.50 result generalises. Given what has already been measured, this remains the most likely
outcome and gets reported as plainly as a positive one would.

### Pre-specified bands

Fixed now so they cannot be tuned post hoc:

`1.20–1.30 · 1.30–1.40 · 1.40–1.50 · 1.50–1.75 · 1.75–2.00 · 2.00–2.50 · 2.50–3.00`

Wider at the long end deliberately: a 3.00 shot hits ~33% of the time and needs far more data than
a 1.25 favourite at ~80% to pin its rate to the same precision. Expect the short end to reach a
verdict months before the longshot end.

**The 1.01–1.20 bands were deliberately excluded (user decision, 2026-08-03), and the cost is
recorded here rather than discovered later.** That is the range where favourite–longshot bias
predicts the effect is STRONGEST, and where precision arrives fastest — ROI variance per unit is
`p(1−p)·o²`, roughly 0.10 at odds 1.10 against 2.0 at 3.00, so the short end pins its interval
about 20× faster. Excluding it means the test now looks hardest where the answer is slowest, and a
true short-odds edge would go undetected by construction. This is a limitation of the test, not a
finding about the market.

**The SCAN nevertheless runs from 1.01.** Rows below 1.20 are collected and settled but not
analysed under the pre-registered bands. Collecting them is free inside the same scan, and this
entire project spent a session retro-settling a backlog precisely because past odds cannot be
backfilled. If the short end is ever revisited, the data will already exist — and re-analysing it
then is an explicitly post-hoc test, which must be labelled as such.

## 3. Approach: a measurement-only scan, structurally isolated from betting

`--target` and `--tolerance` already exist end to end and are forwarded by `run_all.py` to **both**
the scanner and the betslip builder. Widening the shared flag would therefore silently change what
gets staked. It is not done.

Instead the wide scan is a **separate, betslip-free run**:

```bash
py run_all.py --skip-betslips --target 1.01..3.00 --tolerance 0
```

- **No pipeline code changes.** Every flag already exists.
- **The isolation is structural, not a promise**: a run that builds no slips cannot alter a bet.
- The 09:00 cron keeps its own narrow window untouched — changing what is staked is a separate
  piece of work (approach B) that still waits on these numbers.

Rejected: adding a `--matrix-target` distinct from the builder's `--target`. It saves one scan a
day at the cost of new coupling inside `run_all.py` — the exact file where removing `--set` /
`--slips-a` once broke the pipeline invisibly.

## 4. What gets built: `calibrate.py --by-band`

The only new code. Band-level reporting is now the primary analysis, and the throwaway script that
produced the section-1 numbers had no tests.

- Bands are the pre-specified list above, **hard-coded** so the analysis cannot be re-cut until it
  passes.
- Same floors as `--by-run`: a band reports a rate only with **≥20 graded legs AND ≥5 matches**.
  Below that it shows counts and `-`.
- Same **cluster-robust interval, clustering on match-day**, as the retro-load analysis — legs
  cluster in matches and matches cluster in dates.
- Reports **n_legs, n_matches and n_dates** per band.
- Prints the pre-registered prediction alongside the table, and states explicitly when the monotone
  pattern is absent, so a lone clearing band cannot be read as an edge.

Unchanged and still binding: per-family reporting only, no blended aggregate, `implied%` always
visible, an empty band shows `-`, and the floors are never lowered to make numbers appear.

## 5. Volume — MEASURED, and the estimate was wrong

The estimate above was 5–10× the rows per scan. **The measured figure is ~1.4× on the rows that
matter.** First wide scan, `run_20260803_1504`, 128 events:

| | narrow 1.25–1.50 | wide 1.01–3.00 |
|---|---|---|
| qualifying cells | 2,435 | 8,325 (3.4×) |
| **gate-eligible legs** | ~1,200 | **1,630 (1.4×)** |

The settleability gate is the binding filter — only **20%** of wide-window cells are gate-eligible,
because the extra selections at long odds sit disproportionately in markets the grader cannot
settle from a scoreline. Widening the window therefore costs far less than the raw cell count
suggests, and `backtest_pool_legs.csv` will grow at roughly the current rate, not explosively.

**All seven bands populate, and evenly**, which is what makes the test runnable at all:

| band | gated legs | fixtures |
|---|---|---|
| 1.20–1.30 | 198 | 66 |
| 1.30–1.40 | 147 | 51 |
| 1.40–1.50 | 119 | 52 |
| 1.50–1.75 | 226 | 78 |
| 1.75–2.00 | 152 | 79 |
| 2.00–2.50 | 267 | 100 |
| 2.50–3.00 | 249 | 87 |
| *(outside — collected, not analysed)* | 272 | — |

~13 gate-eligible legs per fixture. Every band clears the 20-leg floor from a single scan; the
binding constraint is the **5-match floor and the number of match-days**, since the cluster-robust
interval needs at least two days and is only meaningful across many. Expect useful intervals in
weeks, not days — and only for fixtures worldfootball actually covers (~24% of the backlog).

## 6. The daily job (registered 2026-08-04)

| | |
|---|---|
| task | `Eljam3ia Wide Odds Measurement` |
| schedule | daily 08:00 local — deliberately an hour before the 09:00 betting job, so the two cannot collide whichever is enabled |
| runs | `tools/wide_scan.cmd` (in the repo, so the command is reviewable in version control) |
| log | `output/wide_scan.log`, overwritten each run; the durable artifacts are the per-run directories |

Verified end to end by running the registered task, not just the command by hand:
144 events, 7,973 qualifying cells, `window: 1.01 .. 3`, **`BETSLIPS: none`**. The no-minting
property holds through the scheduled path.

**`Eljam3ia Odds Pipeline` (the 09:00 betting job) was disabled by the user on 2026-08-04.** It last
ran 2026-08-03 and mints nothing while disabled. Re-enable with
`schtasks /Change /TN "Eljam3ia Odds Pipeline" /ENABLE`.

Settlement is NOT scheduled and is not automated. It requires the browser score lookup, so it stays
a deliberate, human-initiated step — which also means the wide scans accumulate unsettled until
someone runs the loop. That is the same backlog dynamic this project has already had to dig itself
out of once; see the retro-settlement spec.

## 7. Out of scope

- Any change to `run_all.py`, the cron, or slip building.
- Minting booking codes or placing bets.
- Re-cutting the 1.25–1.50 result. It is settled and stays in the log as measured.
