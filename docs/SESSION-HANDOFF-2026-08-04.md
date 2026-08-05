# Session Handoff — 2026-08-04

Supersedes `SESSION-HANDOFF-2026-08-01.md`. Read this, then
[`CALIBRATION-LOG.md`](CALIBRATION-LOG.md) for the measurements themselves.

---

## 1. The project's question is ANSWERED

The stated goal — per-family hit% vs the odds' implied% — is achieved, and the answer is negative:

> **−6.6% ROI ± 1.8**, uniform across every slice of the 1.25–1.50 window.
> 481 graded matches, 21 match-days, 8,901 graded observations.
> Six of eight families clear a cluster-robust band; **every one is negative**. Every odds sub-band
> loses. Of 17 markets with ≥150 legs, **none** has an interval above zero.

**That is the bookmaker's margin, measured — not a defect in the families.** `gap = hit% − 1/odd`
is negative by construction for a fairly priced book, because `1/odd` carries the margin; a
zero-edge book converges to `gap = −margin`. Hitting it precisely is evidence the instrument works.

`both halves` was the only edge candidate the project ever had: **+3.2 and +2.1 across the two live
slates, then −3.6 over 374 matches.** It did not survive a 6× larger sample.

### What that means for the money

Three findings compose into one answer:

- **15/25 slips is unreachable at 4 legs** in this window (it needs 88% legs, which price at 1.14),
  and reaching it with 2-leg slips returns 0.996 per unit — break-even by construction.
- **An accumulator amplifies the SIGN of the per-leg edge.** Realised slip ROI was **−47.9%**
  (7/45 slips won, 45 staked, 23.43 returned).
- **Every per-leg edge is measured negative.**

There is no leg selection in 1.25–1.50 on this book that makes the slips profitable.

## 2. What is running now

| task | schedule | state | mints codes? |
|---|---|---|---|
| `Eljam3ia Wide Odds Measurement` | daily **08:00** | Ready | **No** — `--skip-betslips` |
| `Eljam3ia Odds Pipeline` (betting) | daily 09:00 | **Disabled** 2026-08-04 | would, if enabled |

The wide job runs [`tools/wide_scan.cmd`](../tools/wide_scan.cmd) over **1.01–3.00**, feeding the
pre-registered favourite–longshot test. `--skip-betslips` is load-bearing: `--target` is forwarded
to both the scanner and the builder, so a run that built slips would silently widen what gets
staked. A run that builds no slips cannot mint a code.

Re-enable betting with `schtasks /Change /TN "Eljam3ia Odds Pipeline" /ENABLE`.

## 3. The open experiment (PRE-REGISTERED — do not re-cut it)

[`specs/2026-08-03-odds-window-widening-design.md`](superpowers/specs/2026-08-03-odds-window-widening-design.md)
was written **before any wide-window data existed**. Binding:

- **Prediction:** favourite–longshot bias ⇒ margin LOWEST at short odds, rising toward longshots,
  so `roi%` should DECLINE as odds lengthen.
- **Decision rule:** a positive finding needs BOTH a band clearing its interval above zero AND the
  declining pattern, with the clearing band at the SHORT end. A lone clearing band without the
  pattern is a **multiple-comparisons artifact** — with 7 bands at 95%, chance produces one about
  every third run. `calibrate.monotone_verdict` encodes this so it cannot soften.
- **Bands are hard-coded** and must not be re-cut: `1.20–1.30 · 1.30–1.40 · 1.40–1.50 · 1.50–1.75 ·
  1.75–2.00 · 2.00–2.50 · 2.50–3.00`.
- **1.01–1.20 is collected but NOT analysed** (user decision). Re-analysing it later is explicitly
  post-hoc and must be labelled so.
- **Most likely outcome, stated in advance:** flat and negative across bands — the −6.6%
  generalising. Report that as plainly as a positive.

Run it with:
```bash
py calibrate.py --legs output/backtest_pool_legs.csv --by-band --by-run
```

## 4. THE OPERATING LOOP

Scans accumulate unsettled until someone runs this. Settlement is deliberately NOT automated — it
needs the browser score lookup, which cannot run unattended.

1. **Worklist** — what still needs scores:
   `py backlog.py --finished-before <UTC now minus ~2h>`
2. **Bridge + browser** — `preview_start` the `score-bridge`, open worldfootball in a second tab,
   POST the date indexes, then `py tools/retro_join.py`, fetch the reports, `py tools/retro_scores.py --write`.
   **Fetch with 2 paced workers, never 8** (see §6).
3. **Verify** — `py tools/retro_verify.py --compare` (fotmob). 100% of alias joins + seeded 5%.
4. **Preview, then load** — `py tools/retro_settle.py` writes a throwaway preview by default and
   refuses the live log without `--commit`.
5. **Report** — `py calibrate.py --legs output/backtest_pool_legs.csv --by-band --by-run`, then
   append to `CALIBRATION-LOG.md`.

**Never fabricate a score.** No result published → the row is skipped, never guessed.

## 5. Invariants that must not regress

- **Zero duplicate triples** in `backtest_pool_legs.csv`. Dedupe keys on
  (match, market, selection); the **earliest** pre-match scrape wins (latest leaks late
  information; best-odds is selection bias). Pinned by a test AND asserted at write time.
- **Double-count guard**: a triple already carrying a real verdict is dropped; one recorded
  `unsettleable` is a non-measurement and may be replaced, after `purge_unsettleable` removes the
  stale row. `purge_unsettleable` never deletes a real verdict.
- **Join discipline**: unique-exact on both sides, qualifiers (women/U-age/reserve) must AGREE,
  home/away order respected, ambiguity REJECTED. Unmatched is free; wrongly matched is permanent
  and invisible.
- **100% self-consistency** on every fetched report: HT must agree with the goal minutes, FT with
  the goal count, no `pso` headline, no inferred half. Failures rejected, never repaired.
- Floors (`--min-n` 20, `--min-matches` 5) are **never lowered to make numbers appear**.
- Per-family only, no blended aggregate, `implied%` always visible, empty shows `-`.
- Bands cluster on **match-day**, not legs or matches — too narrow is the dangerous direction.

## 6. Traps that are real, each having cost a bug

- **Hollow pages under concurrency.** 8 parallel workers on worldfootball returns HTTP 200 with the
  result elements MISSING. `errs` stays 0 and the rows validate as "not played" — indistinguishable
  from a genuine coverage gap. It shrank a 611-fixture load to 65 while looking like a finding.
  **2 paced workers with backoff return zero hollow pages.** Check a hollow RATE, not an error count.
- **Penalty shootouts.** 13 in one load. The headline score is not the match result.
- **Coverage, not matching, is the constraint.** worldfootball carries ~24% of this backlog; whole
  competitions score zero (U20 Paulista, Kolmonen, Primera C, USL League Two, China League 2).
- **A verification step that verifies nothing reports clean.** `retro_verify` compared the wrong
  field and returned 0/29 checked — which reads exactly like "no coverage". Keys actually matched
  20/29.
- **A guard that is too strict switches itself off.** `sign_history` required EVERY slate to clear
  the floors; at 23 slates every family read `insufficient`, disabling the reversal detector at the
  moment it had enough data.
- **Windows MAX_PATH**: the session scratchpad exceeds 260 chars, so `py <scratchpad script>` fails
  with a bogus "No such file". Copy to a short temp path.

## 7. Known, deliberately not fixed

- ~~Rejected fixtures are re-fetched every run.~~ **FIXED 2026-08-04.** Permanent rejections are
  remembered in `output/scores_rejected/rejected.csv` and skipped by the worklist: the fetch list
  went from 212 to **9**. A rejection is cached only when re-fetching cannot change it (shootout,
  absent goal timeline, self-contradictory report). `not fetched` and `not played` are deliberately
  treated as TRANSIENT — a throttled request returns a page with no result that validates as "not
  played", and caching that would permanently discard a real fixture over one bad request. A
  fixture that later verifies is dropped from the list.
- `output/backtest.csv` header still reads `pred_win_pct` (legacy); the code writes
  `pred_win_pct_floor`. Values aligned; cosmetic.
- `settle.py --pool` does not call `exclude_inplay()` — the graded set is bounded by the scores
  CSV. **If a scores CSV is ever filled for a fixture that kicked off during the scan, this becomes
  a real contamination hole.**
- 142 fixtures rejected for publishing FT and HT but no goal timeline to check HT against. Accepting
  them would add ~33% more matches with HT uncorroborated. Strict rule kept; reversing it is a
  user decision.
- `market_category` (7 families) vs `_market_family` (14) still unreconciled.

## 8. Housekeeping

- **Plaintext secrets on disk**: `~/.bashrc.bak-*` contain old API keys. `rm ~/.bashrc.bak-*` once
  rotated.
- Branches on origin, never delete: `feature/odds-window-widening`,
  `feature/backlog-retro-settlement`, `feature/calibration-log`, `feature/settleable-betslips`,
  plus the older feature line.
- Branch finish = **"both"**: merge to `main` `--no-ff`, verify the suite ON THE MERGED RESULT,
  push `main`, push the branch, keep it.
