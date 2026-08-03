# Session Handoff — 2026-08-01

Supersedes `SESSION-HANDOFF-2026-07-29.md`. Read this first; then `.superpowers/sdd/progress.md`
(git-ignored, in the main working copy) for per-task detail.

**State: `main` = `9250b29`, clean, pushed, 199 tests green. 24 commits since the last handoff.**

---

## 1. The one-line status

**THE GOAL IS ACHIEVED (2026-08-01).** The project's stated goal — per-family hit% vs the odds'
implied% (calibration) — produces real numbers, and the loop now runs on demand.

**All measurements live in [`docs/CALIBRATION-LOG.md`](CALIBRATION-LOG.md) — read that for results,
not this file.** Two slates settled: `run_20260731_0039` (21 matches, 544 graded pool observations)
and `run_20260801_1007` (41 matches, 931 graded). **62 matches, 1,475 graded observations.**

**Interpretation is binding: nothing is signal yet.** Legs are within-match correlated, so the
effective sample is the MATCH count; at p≈0.72, n=62 the 95% band is ±11pp and every family's gap
sits inside it. Slate 2's real contribution was a **falsification**: `1st half` (+6.4 → −6.0) and
`or-combo` (+1.4 → −4.8) both changed sign, and the project's most attractive raw number ever —
`htft` at +28 gap / +39 roi off 13 legs — went to −0.9. The withholding floors are what stopped +28
being reported as a finding. `calibrate.py --by-run` now makes reversals a first-class output.

**The stated goal "15/25 slips correct" is arithmetically unreachable with 4-leg slips** in the
1.25–1.50 window (it needs 88% legs, which price at 1.14), and reaching it with 2-leg slips returns
0.996 per unit — break-even by construction. Money comes only from a positive `gap`. The derivation
is at the top of the calibration log.

The remaining work is purely mechanical: **accumulate slates** (~41 matches each; 4–5 more brings
the band to ±6.6pp, where a real 8–11pp margin becomes detectable).

## 2. What this session changed (headline)

The previous slate design made calibration **impossible by construction**, and that was fixed:

| | before | after |
|---|---|---|
| per-slip win% | 0.17% (1 in 604) | **27.2%** |
| slips gradeable from a score | **0 / 25** | **25 / 25** |
| observations per slate | ~100 slipped legs | **~1,900** (full gated pool) |
| tests | 126 | **199** |

Root cause of the old 0/25: a slip grades only if EVERY leg does, and SET B mandated
`corners x3 + carte x1` — families that are 0% gradeable from a score. Every slip was ungradeable
before a single match kicked off.

## 3. Architecture added (all merged)

**Build-time settleability gate** (`68c17e5`) — `settle.is_settleable(market, selection)` is True
iff `grade_leg` returns a real verdict (`won|lost|void`) for **every** one of 225 representative
outcomes (FT 0-4 x 0-4 with every valid HT split). Stricter than "gradeable on some scoreline" on
purpose: the builder cannot know the outcome. `Both halves over 2` is excluded (integer line can
push); `Total Over 2` is included (`void` is a real settlement outcome).
**Lives in `settle.py`, beside the grader — drift is structurally impossible, not merely tested.**

**LOAD-BEARING INVARIANT: settlement input always carries half-time scores.** Half / HT-FT /
both-halves markets are `unsettleable` without `ht_*`, so every representative outcome supplies
them. Without HT the eligible pool collapses (1st half 477, 2nd half 314, both halves 160, htft 25
all fall out).

**Settleable builder** (`52bb2a3`) — random, without replacement, reshuffled per slip; each leg on a
DISTINCT match and DISTINCT family; only COMPLETE slips emitted. SET A, `--slips-a`, `--set` and the
superseded `build_diversified_slips` deleted. `--seed` records the real seed in the file header.

**Family-depth ceiling** — `sum(min(depth, R)) >= R * legs`, **not** "the Nth-deepest family". With
more families than legs a family can sit out a slip, so five families of 10 support 12 four-leg
slips, not 10. Measured: 4 legs -> 482, 5 -> 344, 6 -> 187; naive `pool//legs` overstates by **72%**
at 6 legs.

**Full-pool settlement** (`7b7ec6a`) — `read_odds_matrix` + `settle_pool` settle every gate-eligible
selection on a slate, ~19x the slipped legs, same scores CSV. **CONTAMINATION GUARD: a slipped leg
is a BET, a pool leg is an OBSERVATION.** Pool rows go to a SEPARATE file
(`backtest_pool_legs.csv`) with a `source` column the slip schema lacks, so naive concatenation
fails loudly. Both paths build records through one `_leg_record()` helper — verdicts cannot disagree.

**Calibration honesty** (`914d4f8`, `7b7ec6a`) — `calibrate.py` withholds hit%/gap unless
`graded >= --min-n` (20) **AND** `matches >= --min-matches` (5). Legs on one fixture are
**correlated** — they resolve off one scoreline — so MATCH count, not leg count, governs the error
bars. `implied%` stays visible (exact given the odds, not a sample estimate). Empty family shows
`-`, never a fabricated 0%.

**In-play exclusion** (`6afba40`) — odds scraped after kickoff are IN-PLAY prices and are not
pre-match predictions. Audit of all 26 matrices: 0 scraped before their own kickoff, but **556 of
6,180 rows (9%)** had a kickoff inside the scan window — 548 from `run_20260724_1812`, a **26-hour**
scan whose window spans its entire fixture list. `exclude_inplay()` keeps only fixtures kicking off
strictly after the run's recorded finish; conservative (unknown kickoff or missing scrape time ->
excluded). Cost to the tier-1 target: **zero fixtures**.

**Void semantics — verified, not assumed.** Settlement DROPS a void leg and re-prices, so the header
win% is a **FLOOR** (4-leg 26.03% shown vs 36.44% realised when one pushes). `calibrate.py` is
unaffected: implied and hit are computed on the SAME leg set. Proven by trace — implied reads 52.50;
contamination would read 51.67. Renamed `pred_win_pct` -> `pred_win_pct_floor` so the name carries
the semantics.

## 4. THE OPERATING LOOP (P1 complete — this is now the routine)

P1 was completed 2026-08-01: `run_20260731_0039` settled from `scores_20260731.csv` (21 filled
rows; Anzoategui–Tachira omitted, result never published). `scores_template.csv` stays PRISTINE as
the reusable blank. The repeatable daily loop is:

1. **Scan + build (no minting):** `py run_all.py --scope all --skip-betslips`, then build the
   settleable slate OFFLINE from named tier-1 leagues (see the offline-build pattern in the ledger;
   `reserve()` is never called without explicit user approval — codes go stale at kickoff anyway).
2. **Scores via the BROWSER (see §5 — this is the solved part):** worldfootball.net match reports
   give FT + HT + goal minutes on one page. Validate any new source against the golden record first.
3. **Pre-flight, settle, calibrate:**
```
py settle.py <run>/betslips_*_offline.txt --outcomes <run>/scores_<date>.csv --check
py settle.py <run>/betslips_*_offline.txt --outcomes <run>/scores_<date>.csv --pool <run>/odds_matrix_*.csv
py calibrate.py --legs output/backtest_pool_legs.csv --by-run
```
4. **Append the slate to [`docs/CALIBRATION-LOG.md`](CALIBRATION-LOG.md)** — matches scored, matches
   deleted (and why), and the new per-slate row. Append, never rewrite: the log's value is that a
   reversed gap stays visible.

Fill rules (unchanged): NEVER guess a score; no result published -> DELETE the row; FT without HT ->
blank `ht_*` (half legs unsettleable, FT legs still grade). **Cup ties: check the event log for
`pso` markers — a shootout scoreline is NOT the match result** (O'Higgins–Boca showed "3:4"; the
real result was 1:0, González 72′; taking the headline would have mis-graded 6 legs).

## 5. Score lookup — SOLVED (browser), with the traps that remain

**Plain HTTP is not viable; the BROWSER is.** Every failed attempt (WebFetch/httpx/Jina Reader) was
plain HTTP, which Cloudflare rejects — a real browser is served normally. Method, proven end-to-end:

- `worldfootball.net/matches-today/dn<YYYY-MM-DD>/` lists every fixture that date with
  match-report links (also per-country: `/matches-today/cy12/argentina/dn.../`).
- Each `/match-report/...` page: FT = `.match-result-0`, HT = `.match-result-intermediate
  .match-result-1`, goals = `li.event.goal` (with minutes). Batch same-origin `fetch()` from the
  page context — 22 fixtures took 3 JS calls.
- **Every row self-checks**: stated HT must agree with the goal minutes.
- **Golden-record validation first**: worldfootball reproduced Central Córdoba 0–2 / HT 0–0 with
  goals 63′/90+2′, matching the independently-read FOX boxscore, before the other 21 were trusted.

Traps that stay live: penalty-shootout headline scores (`event pso ...` — see §4); timezone (a
00:15Z kickoff files under the previous local date); stale search indexes and wrong-season results
mean **search snippets are never a source** — only a match-report page you actually read.

**P2 provider — withdrawn.** No free or public source covers this dataset. Measured against the real
backlog (2,818 played, in-play-clean fixtures / 39,728 gated selections): Sportmonks free **1.3%**,
public/keyless (openfootball/TheSportsDB/OpenLigaDB) **1.1%**, API-Sports free key rejected (it is a
RapidAPI key on an account without the API-Football subscription). **The binding constraint is the
BACKLOG'S COMPOSITION, not the providers** — 707 of 2,818 fixtures are one unnamed competition
(`League 2932`), the rest skew to U20/regional/3rd-tier. See
`docs/superpowers/specs/2026-07-29-stats-provider-integration-design.md`. The DESIGN stays valid;
only the provider choice is dead.

**Retro-settlement** — 26 matrices hold **246 tier-1 fixtures / 9,607 gate-eligible selections**,
schema-clean and unambiguously identifiable. Blocked solely on score lookup at volume. If a
structured scores API is ever obtained, this is a ~13x multiplier on one slate.

**GOLDEN RECORD** (the project's only hand-verified, independently-sourced result — use it to test
any candidate source, which must reproduce BOTH FT and HT):
> **Central Cordoba 0-2 Atletico Tucuman, HT 0-0** — Argentine Primera, kickoff 2026-07-31T00:15Z.
> FOX Sports boxscore; goals 63' and 90+1', internally consistent with a goalless first half.

## 6. Workflow conventions (unchanged, still binding)

- Verification-gate pattern: audit the REAL data before writing grading code. Gates overturned an
  approved design twice this session (the gated pool does NOT skew low-odd; the feasibility rule is
  not "Nth-deepest").
- Branch finish = **"both"**: merge to `main` `--no-ff`, verify the full suite ON THE MERGED RESULT,
  push `main`, push the feature branch, KEEP it.
- Track progress in `.superpowers/sdd/progress.md`.
- Per-family reporting only; never a blended aggregate; `other` must stay a genuine catch-all.
- **Flag removal needs a grep across `run_all.py` and orchestration wrappers** — the unit suite tests
  the module, not the pipeline that shells into it. Removing `--set`/`--slips-a` broke `run_all.py`
  invisibly, and an argparse `help=` containing `win%` crashed `--help` (needs `%%`).

## 7. Housekeeping

- Branches on origin (never delete): `feature/settleable-betslips` (this session),
  `feature/both-halves-calibration-tooling`, `feature/score-derivable-tranche`,
  `feature/half-combo-grading`, `feature/settlement-core`, `feature/per-category-betslips`.
  `claude/session-handoff-continuation-b4997b` is redundant with `feature/settleable-betslips` but
  kept per the never-delete rule.
- **Plaintext secrets on disk**: `~/.bashrc.bak-20260731-094623` and `~/.bashrc.bak-20260801-082625`
  contain old API keys. Delete once the keys are rotated: `rm ~/.bashrc.bak-*`.
- `~/.bashrc` holds one working `export API_FOOTBALL_KEY=...` line (UTF-8). NOTE: PowerShell's
  `Add-Content` writes **UTF-16**, which bash cannot parse — always append from Git Bash.
- `output/backtest.csv` was created before `pred_win_pct` was renamed, so its HEADER still reads
  `pred_win_pct` while the code writes `pred_win_pct_floor` (header is only written for a NEW file).
  Values are aligned and correct; cosmetic only. A fresh file picks up the right name.
- `settle.py --pool` does NOT call `exclude_inplay()`. It doesn't need to: the graded set is bounded
  by the scores CSV, and a slate is only settled for fixtures kicking off after the scrape. Verified
  for slate 2 (scan ended 10:19Z, earliest scored kickoff 11:00Z). **If a scores CSV is ever filled
  for a fixture that kicked off during the scan, this becomes a real contamination hole.**
- Windows MAX_PATH: the session scratchpad path is >260 chars, so `py <script>` there fails with a
  bogus "No such file or directory". Copy analysis scripts to a short temp path to run them.
- Deferred, named: reconcile `make_betslips.market_category` (7 families) with
  `settle._market_family` (14); the ~30 score-derivable markets still in the `other` bucket
  (`Any team to win`, `1|2 win to nil`, `to win either half`) — deliberately NOT built, because the
  gate means ungraded markets are simply never selected, so rescuing them unblocks nothing.
