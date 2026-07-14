# Eljam3ia Odds Scanner

Scans football matches on [eljam3ia.com/betting](https://www.eljam3ia.com/betting) and collects
every betting selection whose decimal odd falls in the qualifying window (default target range
**1.30..1.45 ± 0.05**, i.e. window **[1.25, 1.50]**).

The betting page is an **Altenar sportsbook widget**, so the script talks directly to the Altenar
JSON API (`sb2frontend-1-altenar2.biahosted.com/api/Widget/`) — no browser automation. One GET per
event returns *all* markets and odds at once.

## Requirements

- Python 3.10+ and `httpx` (`pip install httpx`)

## Automatic mode (one command + daily schedule)

`run_all.py` runs the whole chain — scan all leagues → odds matrix → 20-leg accumulator betslips →
fresh booking codes — into a single dated folder `output/run_YYYYMMDD_HHMM/` (matrix CSV + `_meta`,
`betslips_*.txt`, and a `summary.txt` listing every booking code).

Qualifying window is **[1.25, 1.50]** (target range `1.30..1.45` ± `0.05`). Betslips are **20-leg
accumulators, up to 50 per run**; a match may recur across slips, each time with a **different odd**.

```
py run_all.py                         # full pipeline, project defaults
py run_all.py --size 10               # legs per betslip
py run_all.py --skip-betslips         # matrix only
py run_all.py --hours 0 --scope top   # old behavior: Top Leagues, all upcoming dates
py run_all.py --target 1.3..1.45 --size 20 --slips 50   # defaults, shown explicitly
py run_all.py --target 1.4 --size 10 --slips 7          # old-style single target, 10-leg
py run_all.py --per-category            # 7 category-pure families, up to 25 slips each
py make_betslips.py --per-category      # same, betslips only
```

With `--per-category`, betslips are grouped into 7 market families (main, combo DC, 1st half,
2nd half, corners, carte/cards, multigoals) — up to 25 twenty-leg slips per family, each leg from
that family.

By default every run covers **all football leagues with matches in the next 23 hours**
(`DATE_FILTER = Only Today (23 h)`); use `--hours`/`--scope` to widen.

Booking codes are always minted fresh at run time because they go stale as matches kick off.

**Daily schedule (Windows).** `run_all.cmd` wraps the pipeline for Task Scheduler and logs to
`output/scheduler.log`. A task named **"Eljam3ia Odds Pipeline"** is registered to run daily at
09:00. Manage it with:

```
schtasks /Query  /TN "Eljam3ia Odds Pipeline"      # status + next run
schtasks /Run    /TN "Eljam3ia Odds Pipeline"      # run now
schtasks /Change /TN "Eljam3ia Odds Pipeline" /ST 08:00   # change time
schtasks /Delete /TN "Eljam3ia Odds Pipeline"      # remove
```

The PC must be on at the scheduled time; if it was asleep, the task runs when it next wakes
(`-StartWhenAvailable`). Because booking codes expire as matches start, prefer a schedule shortly
before you use them.

## Usage (individual scripts)

```
py eljam3ia_odds_scanner.py                                # all leagues, today window, range 1.30..1.45
py eljam3ia_odds_scanner.py --league "World Cup 2026"      # one league (repeatable flag)
py eljam3ia_odds_scanner.py --target 2.0 --tolerance 0.1   # different odds window
py eljam3ia_odds_scanner.py --out somewhere                # output folder (default: output/)
```

Defaults live at the top of `eljam3ia_odds_scanner.py` (`TARGET_ODD`, `TOLERANCE`, `TOP_LEAGUES`,
`DELAY_S`, ...). The default league set mirrors the site's "Top Leagues" menu section: World Cup
2026, Euro 2028, UEFA Champions League, UEFA Europa League, Premier League, LaLiga, Serie A,
Bundesliga, Ligue 1, Liga Profesional. Leagues with no current events are skipped with a note,
not an error.

## Output

Two files per run in `output/`:

- `odds_matrix_<tag>_<YYYYMMDD_HHMM>.csv` — the matrix (UTF-8 with BOM, opens cleanly in Excel):
  - lead columns: `League, Match, Kickoff (UTC), Event ID, Scraped At (UTC)`
  - one column per market name (e.g. `1x2`, `Total`, `Handicap`, `Correct score`), ordered by how
    many matches have a qualifying selection in that market
  - cells: qualifying selections as `selection @ odd` (e.g. `Under 2.5 @ 1.4167`), several joined
    by `; `; blank when the match has none in that market
- `..._meta.csv` — run metadata: leagues scanned/skipped, target, tolerance, window, start/end
  time, events scanned/failed, qualifying-cell totals, and whether the run was partial.

Notes on the matrix:

- Market instances with the same name (e.g. `Total` at several goal lines) merge into one column;
  the selection labels carry the line (`Over 2.5`), so nothing is lost.
- Odds move live — `Scraped At (UTC)` records when each match was read.
- A match with zero qualifying selections still gets a row (all market cells blank).

## Behaviour / etiquette

- Single-threaded, ~0.7–1 s between event requests, 3 retries with backoff on transient errors.
- Failed events are logged in the meta file and skipped, never fatal.
- HTTP 403/429 (blocked/rate-limited) or Ctrl-C ⇒ the partial matrix is saved and the meta file
  is flagged `partial_run`.
- Read-only public data at a low rate for personal analysis. Automating a betting site may be
  against its terms of service — keep the request rate polite and don't hammer the endpoints.
