# Session Handoff — 2026-08-01

Supersedes `SESSION-HANDOFF-2026-07-29.md`. Read this first; then `.superpowers/sdd/progress.md`
(git-ignored, in the main working copy) for per-task detail.

**State: `main` = `9250b29`, clean, pushed, 199 tests green. 24 commits since the last handoff.**

---

## 1. The one-line status

The project's goal — **per-family hit% vs the odds' implied% (calibration)** — has still produced
**zero real numbers**. Everything needed to produce them now exists and is verified. The only
missing input is 22 hand-entered scores. That is the whole critical path.

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

## 4. THE IMMEDIATE NEXT ACTION (P1)

Everything is staged in `output/run_20260731_0039/`:

- `betslips_20260731_0039_offline.txt` — 25 slips x 4 legs, **verified 25/25 gradeable**, built
  OFFLINE (`reserve()` never called, no booking codes minted)
- `scores_template.csv` — **PRISTINE, sha `476CB50E3704DB4F`**, 22 blank rows
- `SCORE-ENTRY-GUIDE.txt` — per-match kickoff, league, leg count, **which need HT**, sources

**All 22 fixtures are played.** Fill the template, then:

```
py settle.py output/run_20260731_0039/betslips_20260731_0039_offline.txt --outcomes output/run_20260731_0039/scores_template.csv
py calibrate.py
```

Rules for the fill: **21 of 22 matches need HT** (53% of legs). NEVER guess a score. Cannot find a
result -> delete the row. Cannot find HT but have FT -> leave `ht_home`/`ht_away` blank; those legs
go unsettleable, every full-time leg still grades. The four Welsh fixtures are **Cymru South (tier
2) cup ties** — search by TEAM, not league.

Expect most families to show `-` for hit%/gap on run one (~12 legs/family, below the floors). That
is correct behaviour. Do NOT lower `--min-n` to make numbers appear.

## 5. Blocked, with reasons (do not re-litigate)

**Automated score lookup is NOT VIABLE.** Four attempts, three distinct failure modes:
1. Direct fetch blocked — worldfootball.net, api-football docs/pricing, ESPN/FOX pages all 403.
2. Stale index — a search reported Bodo/Glimt "not completed yet" ~12h after full time.
3. **Wrong fixture** — a lookup for Central Cordoba vs Atletico Tucuman returned a 1-1 from July
   **2025**, a different match from a different season, presented as the fixture. Undetectable at
   scale precisely because (1) blocks the cross-check that would catch it.
Jina Reader (`r.jina.ai`, what Agent Reach's web channel uses) hits the same Cloudflare/CAPTCHA
wall. **The human fill is the reliable path, not a fallback.**

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
- Deferred, named: reconcile `make_betslips.market_category` (7 families) with
  `settle._market_family` (14); the ~30 score-derivable markets still in the `other` bucket
  (`Any team to win`, `1|2 win to nil`, `to win either half`) — deliberately NOT built, because the
  gate means ungraded markets are simply never selected, so rescuing them unblocks nothing.
