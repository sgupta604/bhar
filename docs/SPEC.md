# SPEC — Site-Tuned Model Blend (MVP)

**Written:** 2026-09-04 ~02:15 local, from a full requirements grilling session with Sanjay.
**Demo:** 2026-09-04 **16:00**. Unattended build window ~02:30–07:30. Office day 08:15–15:00.
**Status of this document:** every decision below is SETTLED. This is the contract.

> **Precedence.** This SPEC overrides `docs/BRIEF.md` wherever they conflict.
> `.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md` contains VERIFIED FACTS and
> overrides both. `docs/BRIEF.md` remains the source of business context and the demo page design
> (§8), but several of its technical assumptions were tested and found wrong — see the spike doc.
>
> **The user is asleep.** Do not ask questions. Every open question from BRIEF §10 and §11 has
> been answered here. If something genuinely new arises, follow the blocked-ticket rule in §9.

---

## 1. Hypothesis under test

At one site, does a weighted blend of NOAA models, tuned against that site's own observations,
beat the best single model **out of sample**?

Expected honest outcomes, all of which ship as-is:
- NBM (already NOAA's blend) wins outright. **This is a likely and acceptable result.**
- The blend ties the best single model. **Also a real finding** — you did not need to know in
  advance which model to trust.
- A blend including NBM edges out NBM alone. The strongest result, but not required.

**The page reports what the data says.** See §10.

## 2. Scope

**In:** one site (KOMA), 2 m temperature, four models, three lead times, 30 days, MAE headline,
weight grid search, FastAPI backend, web frontend with live weight sliders, README.

**Out, explicitly:** yay/nay feedback UI; multiple sites; commercial providers; precipitation or
probabilistic variables; live serving to external consumers; anything in Rust; the S3 snapshot
cron (post-demo); bias correction / MOS (see §5).

## 3. Data

| Dimension | Value |
|---|---|
| Site | Omaha Eppley Airfield **KOMA**, 41.3032, -95.8941. IEM station `OMA`. Station elev 295.7 m. |
| Variable | 2 m temperature, reported in **degrees F** |
| Models | **HRRR, GFS, NAM, NBM** |
| Source | **NOAA AWS S3 + `.idx` byte-range subsetting** (spike F2) |
| Init runs | **All four synoptic runs: 00z, 06z, 12z, 18z** |
| Lead times | **6 h, 12 h, 24 h** |
| Window | Last **30 days** |
| Observations | IEM ASOS `OMA`, hourly (spike F4) |
| Sample size | ~120 valid times per lead time per model (30 days x 4 inits) |

**Timezone: UTC everywhere.** Convert Kelvin to F: `F = (K - 273.15) * 9/5 + 32`.

**Do NOT use folkweather** — it does not archive and it lies convincingly (spike F1).
**Do NOT use Herbie** (spike F8). **Parse the `.idx` every time; NBM's message index moves** (F2).

## 4. The join — highest-risk correctness issue

Model output is on the exact hour. **METAR is not** (spike F5).

- Join model rows to observations by **nearest valid non-`M` observation within +/-30 minutes**
  of the model's valid time.
- **Record the actual time offset in minutes as a column on every matched row.**
- **Hard assert** on matched row count per (model, lead_h). If matched rows fall below
  **80% of expected**, the pipeline RAISES. It does not proceed.
- Drop missing observations. **Never interpolate observations.**

An empty or near-empty join scores beautifully and is completely fake. The assert is the guard.

## 5. Method

- Join on **valid time** (`init_time + lead_h`), never on init time.
- **Paired comparison.** A valid time enters scoring only if **every included model** has it.
- **Coverage floor: 90%.** Any model with under 90% of expected runs available is **dropped from
  the study entirely** and named on the page with its coverage percentage. Three models on 120
  well-paired samples beats four models on 40.
- Metrics per model per lead time: **MAE (headline), RMSE, bias.** Report all three.
- **Nearest grid cell. No interpolation.** Note the grid-cell vs station elevation delta.
- **Blend search:** weight vectors on the simplex summing to 1.0, **step 0.1**, over the included
  models. Four models -> 286 vectors. Pure models are the one-hot corners and are ranked for free.
  Weights are optimized **per lead time, independently**.
- **Train/test: chronological split. Fit on days 1–20, evaluate on days 21–30.**
  Report **both** in-sample and out-of-sample error. **The out-of-sample number is the headline.**
  The gap between them is a displayed result, not a hidden detail.
- **NO bias correction / MOS in this MVP.** Deliberate. Two reasons, both stated in the README:
  it confounds the hypothesis (you could not tell whether blending or the correction produced the
  win), and it hands the "isn't this just MOS?" objection to the room. v2 adds it and shows the
  increment.

## 6. Architecture

```
NOAA S3 (.idx + byte range) ──┐
                              ├─> fetch/ ──> data/forecasts.parquet ──┐
IEM ASOS CSV ─────────────────┘             data/obs.parquet ─────────┤
                                                                      v
                                                          score/ (join, metrics, blend grid)
                                                                      │
                                                                      v
                                                          data/results.json
                                                                      │
                                            FastAPI backend ──────────┘
                                                      │  (serves precomputed results from disk)
                                                      v
                                            Frontend (Clarity-styled)
```

**Language:** Python 3.12, pinned via `uv`, venv in-repo (`.venv/`).
**Backend:** FastAPI. Built clean and portable — **no coupling to wxchange**; the wxchange stack
is unknown and was deliberately not investigated. The documented JSON contract (§7) is the
portable artifact; any stack can serve it later.
**Frontend:** separate from the backend, calls it over HTTP.
**Demo path never hits NOAA live.** The backend serves precomputed results from disk. A refetch
endpoint may exist but is described, never pressed, during the demo.

Parquet columns:
- `forecasts.parquet`: `model, init_time, lead_h, valid_time, temp_f`
- `obs.parquet`: `valid_time, temp_f`

## 7. `results.json` contract — LOCKED FIRST, before backend or frontend

This is the contract-first foundation. Both the backend and the frontend code against it.
`demo-shell` (ticket 3) generates a **synthetic fixture** in this exact shape.

```jsonc
{
  "meta": {
    "site": {"id": "KOMA", "iem_station": "OMA", "name": "Omaha Eppley Airfield",
             "lat": 41.3032, "lon": -95.8941, "station_elev_m": 295.7},
    "variable": "2m_temperature", "units": "degF",
    "window": {"start": "2026-08-05T00:00:00Z", "end": "2026-09-04T00:00:00Z", "days": 30},
    "init_runs": ["00z", "06z", "12z", "18z"],
    "source": "noaa_s3_grib",           // or "open_meteo_previous_runs" if the fallback fired
    "generated_at": "2026-09-04T04:00:00Z",
    "is_synthetic": false,               // TRUE for the fixture. Frontend MUST display a banner.
    "models_included": ["HRRR", "GFS", "NAM", "NBM"],
    "models_excluded": [{"model": "NAM", "coverage_pct": 71.2, "reason": "below 90% floor"}],
    "split": {"method": "chronological", "train_days": 20, "test_days": 10}
  },
  "lead_times": [6, 12, 24],
  "results": {
    "6": {
      "n_samples": {"train": 80, "test": 40},
      "join_diagnostics": {"matched_pct": 98.3, "mean_abs_offset_min": 6.4},
      "models": [
        {"model": "HRRR", "mae": 2.14, "rmse": 2.81, "bias": -0.32, "coverage_pct": 99.1}
      ],
      "blends": [
        {"rank": 1, "weights": {"HRRR": 0.7, "GFS": 0.3, "NAM": 0.0, "NBM": 0.0},
         "label": "70 / 30", "is_pure": false,
         "mae_in_sample": 1.91, "mae_out_of_sample": 2.02,
         "rmse_out_of_sample": 2.55, "bias_out_of_sample": -0.11}
      ],
      "best_single_model": {"model": "NBM", "mae_out_of_sample": 2.09},
      "winner": {"label": "70 / 30", "mae_out_of_sample": 2.02,
                 "improvement_pct_vs_best_single": 3.3}
    }
  }
}
```

Rules: `blends` is sorted by `mae_out_of_sample` ascending and includes **every** pure model
regardless of rank. `improvement_pct_vs_best_single` **may be zero or negative** — the frontend
must render that honestly (see §10).

## 8. Ticket backlog

Six features, each through the full pipeline `/research -> /plan -> /implement -> /test ->
/finalize`. `/finalize` = commit + `SUMMARY.md`, **no PR** (there is no git remote).
Branch: `feat/site-tuned-blend`.

> **Who writes acceptance criteria.** What follows is an **acceptance FLOOR**, not the finished
> list. `plan-agent` writes the full acceptance criteria for each feature when that feature reaches
> `/plan`, in its own format, with whatever additional criteria the architecture implies. The floor
> below is the minimum that must be present — `plan-agent` may add to it and must not drop from it.
> Two items are marked NON-NEGOTIABLE (the one-hot identity test in T5 and the join assert in §4);
> those exist because without them the project can produce confident, fake numbers.


### T1 `project-scaffold`
Set up `uv` with pinned Python 3.12, `pyproject.toml`, dependencies, `pytest` wired, repo layout,
and fill the empty **Commands** block in `CLAUDE.md` (the test-agent reads its commands from there
and currently has none).
**Acceptance floor:** `uv run pytest` exits 0. `uv run python -c "import cfgrib, xarray, pandas, pyarrow, fastapi"` succeeds. `CLAUDE.md` Commands block is populated. Committed.

### T2 `grib-point-fetch` — HIGHEST RISK, do early
Parse a NOAA `.idx`, issue an HTTP range request for the `TMP:2 m above ground` message, decode it,
extract the nearest grid cell to KOMA, convert to degrees F.
**First task is a probe** (plan-agent's verification-first rule): fetch one real message before
building anything on top.
**Acceptance floor:** returns a plausible temperature (say -40 to 130 F) for HRRR, GFS, NAM and NBM at
2026-08-05 12z f006. Unit test for `.idx` parsing against a fixture. **NBM message index is read
from the `.idx`, never hardcoded** — test this explicitly at f006, f012 and f024.
**Named fallback:** see §11 R1.

### T3 `demo-shell` — the "never stare at nothing at midnight" insurance
Lock the §7 contract. Generate a synthetic `results.json` fixture. Build the FastAPI backend
serving it, and the frontend against it, styled per §12.
**Acceptance floor:** backend starts, endpoints return the fixture. Frontend loads, renders the
leaderboard, the lead-time toggle switches data, model checkboxes filter, **the weight slider moves
and the displayed error changes and agrees with the underlying data**. `is_synthetic: true` shows a
visible banner. agent-browser smoke check passes (§13). After T3 there is a demoable artifact even
if everything downstream fails.

### T4 `data-backfill`
Fetch observations from IEM into `obs.parquet`. Backfill 30 days x 4 inits x 3 leads x 4 models
into `forecasts.parquet`, parallelized. Emit a per-model coverage report.
**Acceptance floor:** both parquet files exist with the §6 columns. Coverage report printed and stored.
Obs cover ~720 hours. Any model under the 90% floor is flagged. Fetch completes in under 15 min.

### T5 `score-and-blend`
The §4 join with its guards, the §5 metrics, the simplex grid search, the 20/10 chronological
split. Writes the real `results.json`, replacing the fixture.
**Acceptance floor — the single most important test in the project (NON-NEGOTIABLE):** a one-hot weight vector
(e.g. `HRRR: 1.0`) **must reproduce pure HRRR's own MAE to the decimal**. If it does not, the
blending is wrong and every number on the page is fiction. Also: the join assert fires on
synthetic sparse input; `n_samples` and `join_diagnostics` are populated; frontend renders real
results with `is_synthetic: false` and no banner.

### T6 `readme-and-caveats`
`README.md` per BRIEF §13: how to run, what the numbers mean, known caveats, what's next.
**Acceptance floor:** a reader who was not here can run the pipeline end to end from the README alone.
Must state, in plain language: the 20/10 split and why; that samples within a day share a weather
regime so 120 samples are not 120 independent observations; that no bias correction was applied
and why; nearest-grid-cell and the elevation delta; any excluded model and its coverage; and the
data source actually used.

**Dependency graph:** T1 -> T2 -> T4 -> T5. **T3 depends only on T1** and is independent of the
data path. T6 last.

## 9. Loop operating rules

**The user is asleep and has explicitly said the loop must not need them.**

- Work tickets in order. Each ticket goes through the full pipeline and ends on a **green,
  committed state**.
- **Never leave the tree broken to start the next thing.** A working leaderboard with no slider is
  a demo; a half-wired slider is not.
- **Blocked ticket -> log it, mark BLOCKED, move to the next ticket that does not depend on it.**
  Do not halt the run. Do not retry indefinitely. If T2 blocks, T3 still runs and the morning
  brings a working app with fake numbers plus one clearly-labelled blocker.
- Halt only when nothing remains that is not blocked.
- Update `.claude/pipeline/STATUS.md` at every phase transition.
- Maintain `.claude/active-work/site-tuned-blend/session-log.md`: what is done, what is in
  progress, what is blocked and what was tried.

**Permitted without asking:** install into the project-local venv; `brew install uv`,
`agent-browser`; network fetches to NOAA, IEM, Open-Meteo; commits to `feat/site-tuned-blend`;
writes to `STATUS.md`, the session log, and plan checkboxes.

**Forbidden:** `git push`; opening a PR; installing into system Python; editing `docs/BRIEF.md`;
editing anything in `.claude/` beyond `STATUS.md`, the session log and plan checkboxes; editing
this SPEC.

**Hard stop and wait (do not work around these):**
1. A data source returns empty or all-null for the entire window.
2. A dependency will not install after two genuine attempts **and** the §11 fallback also fails.
3. Any impulse to change the metric, the window, the split, or the site **in order to improve the
   result.** This is the one that ends the demo's credibility. See §10.

**Stop condition:** all six tickets green -> write the session log, update STATUS.md, **stop.**
Do not start stretch goals. Do not refactor working code. Do not "polish." An autonomous agent
with green tests and no stop condition will break something that worked.

## 10. Integrity rules — non-negotiable

The MVP's value is that the number is trustworthy. Therefore:

- **Report what the data says.** If no blend beats the best single model, the page says so.
- **Never tune the experiment to produce a win.** Do not try more lead times, extra windows, other
  splits, or a different site because the first result was unexciting. That is p-hacking, and the
  first question from the room ("how many variations did you try?") ends the demo.
- **The headline is the out-of-sample number.** In-sample is shown beside it, labelled.
- **The synthetic fixture must be unmistakable.** `is_synthetic: true` renders a visible banner.
  A fixture that could be mistaken for real data at 4pm is the worst possible failure.
- **Excluded models and join diagnostics are displayed, not buried.**
- If the fallback source fired, **the page says which source produced the numbers.**

## 11. Risk register with named fallbacks

**R1 — `cfgrib`/`eccodes` will not install or will not decode. (Top risk.)**
Mitigation: pinned Python 3.12, not the host's 3.14; smoke-tested while the user is awake.
**Named fallback, after two genuine failures:** Open-Meteo previous-runs API.
Cost: **24 h lead only** — the 6 h and 12 h columns are lost and the lead-time toggle collapses to
one value. Use `gfs_global`, **never `gfs_seamless`** (spike F3). Set `meta.source` to
`"open_meteo_previous_runs"` and state it on the page. A one-lead demo beats no demo.

**R2 — NOAA archive gaps.** HRRR's archive is known to have holes.
Mitigation: the 90% coverage floor (§5) turns this into a named, displayed model exclusion rather
than a dead run.

**R3 — the join matches too few rows.** Mitigation: the §4 hard assert. Fails loudly rather than
producing a chart of nothing.

**R4 — six pipeline passes may not fit in ~5 hours.** Mitigation: ticket order. T3 lands third, so
a demoable app exists before the data work begins. Blocked tickets are skipped, not retried.

**R5 — agent-browser is pre-1.0** (692 open issues). Mitigation: pinned at 0.36.0, smoke-tested
while the user is awake, and **droppable** — if it misbehaves, drop it and note it in the session
log. It must never block a ticket.

## 12. Frontend design

Structure per **BRIEF §8**: header (`Omaha Eppley (KOMA)` / `Last 30 days` / `2m temperature, N
candidate blends scored vs METAR`); lead-time toggle `6h | 12h | 24h`; leaderboard rows of
rank / weight label / stacked weight bar / error in F, winner highlighted; footer stating the
margin over the best single model; chart of error vs weight.

**Beyond §8, this MVP adds:** model include/exclude checkboxes, and **live weight sliders** — move
a slider, the error recomputes immediately. The slider is the thesis made physical: the audience
watches the dip get found.

**Resolving BRIEF §8's chart for four models.** §8 specifies "error (y) vs HRRR weight 0→100% (x),
both ends are pure models, the dip in the middle is the value." That picture assumes **two**
models — with four, the weight space is a 3-simplex and there is no single x-axis.
**Resolution:** the chart plots a **two-model slice**. Default to the two best single models by
out-of-sample MAE, with the other two held at zero; x is the weight of model A from 0 to 100%.
This reproduces §8's intended picture exactly — both ends really are pure models, and a dip in
the middle really is the value — while staying honest about what is being shown. Add a small
pair selector so the presenter can switch which two models the slice runs between. Label the
chart with the pair being shown and note that the leaderboard above it searches the full
4-model space, not just this slice.

**Styling: Shyft "Clarity" design system** (v0.2). Full tokens extracted to
`.claude/features/site-tuned-blend/clarity-design-tokens.md` — read that file before styling.

Fetchable stylesheet (no auth, light mode only):
`https://portal.internal.shyftsolutions.io/api/v1/dev-guide/tokens.css`
**There is no npm package** — Clarity ships no component library. Dark-mode values are NOT in the
CSS file; copy them from the extracted tokens doc if dark mode is implemented.

Core: accent `#329af0` (hover `#1c7cd6`); text `#212529`; page bg `#f8f9fa`; surface `#ffffff`;
border `#e9ecef`; muted text `#5c636a`. Semantic: success `#37b24d`, warn `#ff922b`,
**danger is pink `#de0f80`**. Fonts: `Sora` (display/stat values), `Inter` (UI),
`JetBrains Mono` (tabular numerals — use it for every error value in the leaderboard).
Data-viz palette, explicitly reserved for charts and never for UI chrome: green `#51cf66`,
orange `#ff922b`, purple `#a551cf`, pink `#f0329a`, yellow `#f7be1e`.
Dark mode exists: `<html data-theme="dark">`, localStorage key `internal-portal:theme`.

**Two gaps Clarity does not cover — design these, do not hunt for tokens that aren't there:**
1. **No slider/range styling exists anywhere in Clarity.** The weight sliders must be built from
   the primitives (accent, border, radius, spacing).
2. **No chart-series or axis tokens.** Use the data-viz palette above for model series, and assign
   model colors consistently across the stacked weight bars and the error-vs-weight chart.

A `/design` pass produces the visual target before T3 builds the frontend.

Must render honestly: zero or negative improvement, excluded models, the synthetic banner, and the
data source.

## 13. Testing

**Command surface goes in `CLAUDE.md`'s Commands block during T1.** It is currently empty, which
means `/test` has nothing to run.

- **`pytest` on pure logic**: `.idx` parsing; the +/-30 min join against a synthetic fixture;
  blend math (**the one-hot identity test from T5**); MAE/RMSE/bias arithmetic; unit conversion.
- **Data guards are assertions in the pipeline**, not tests.
- **No live-network integration test.** A test that hits NOAA and fails at 04:00 halts a ticket
  over NOAA having a bad minute, not over our code.
- **UI: agent-browser**, pinned `0.36.0`, native, no container. The one check worth having:
  page loads -> leaderboard renders N rows -> **moving the weight slider changes the displayed
  error** -> the value agrees with the API -> no console errors. Capture a screenshot to
  `.claude/active-work/site-tuned-blend/screenshots/` so the morning starts with a picture.

## 14. What must exist at 07:30

The user wakes at 07:30 and leaves at 08:15. **45 minutes: verification, not debugging.**

1. `.claude/pipeline/STATUS.md` — one line: what is done, what is next.
2. `.claude/active-work/site-tuned-blend/session-log.md` — done / in progress / blocked, with what
   was tried for each blocker.
3. **One command that starts the demo**, documented at the top of `README.md`.
4. A screenshot of the working page.
5. Green tests, clean tree, all work committed to `feat/site-tuned-blend`.

## 15. Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | NOAA S3 byte-range, not folkweather, not Open-Meteo | Folkweather does not archive (F1). Open-Meteo has no 6h/12h lead and is non-commercial-only (F3). S3 is the only sellable path with all three leads. |
| 2 | No Herbie | Direct `.idx` + range is short and removes a dependency that fights eccodes (F8). Moots BRIEF §10 Q7 and §11's `pick_points` concern. |
| 3 | Python 3.12 via `uv`, not host 3.14 | GRIB stack wheel availability is the top risk; 3.14 is where it breaks. `uv` also gives a clean room without Docker. |
| 4 | All four synoptic inits, not 12z only | 120 samples instead of 30, for ~4 minutes of extra download. Makes the train/test split meaningful and blunts BRIEF §12's "30 points is nothing." |
| 5 | 20/10 chronological split, out-of-sample headline | Fitting and reporting on the same 30 days guarantees a win by arithmetic. "Fit on the first 20 days, still won on the last 10" is the only version that survives a hostile question. |
| 6 | No bias correction in the MVP | Confounds the hypothesis, and hands the room the "isn't this just MOS?" objection (BRIEF §12). v2 adds it and shows the increment. |
| 7 | Blend grid step 0.1, not 0.05 | Compute is free; readability is the constraint. BRIEF §8 wants labels like "70 / 30". At 0.05 rows differ by hundredths of a degree — noise dressed as precision — and the fit has more room to overfit. |
| 8 | Nearest ob within +/-30 min, with a hard assert | BRIEF §10 Q8 was wrong: METAR is not on the hour (F5). An exact join matches zero rows and produces a perfect-looking fake. |
| 9 | Paired comparison + 90% coverage floor | Three models on 120 well-paired samples beats four on 40. The exclusion is displayed, which builds trust in the rest. |
| 10 | FastAPI backend + separate frontend, not a static page | User's goal is eventual integration into wxchange. A static file is a dead end. Condition: the demo path never fetches live. |
| 11 | Not coupled to wxchange conventions | wxchange's stack is unknown and was deliberately not investigated at 02:00. The documented JSON contract is the portable artifact. |
| 12 | Six tickets, `demo-shell` third | Every ticket ends green and committed. T3 before the data work means a demoable app exists early — BRIEF §8's own "never stare at nothing at midnight." |
| 13 | Blocked ticket -> log and skip, do not halt | Halting hands the user a dead repo and a paragraph. Skipping hands them a running app and one labelled blocker. |
| 14 | No container | Both motives dissolved: `uv` is the clean room, and agent-browser runs natively on macOS ARM64 (F7). Docker would add five failure modes on the night it has to work. |
| 15 | agent-browser over Playwright | One install, no second browser toolchain, no blind selector authoring, and it leaves screenshots for the 07:30 window. Playwright regression tests are an office-day task. |
| 16 | No plan review before sleep | User's explicit call. Consequence: acceptance criteria are written into every ticket here rather than left for plan-agent to invent. |

## 16. Cold-start handoff — read this first if you are a fresh session

You have no memory of the requirements session that produced this document. You do not need it.
Everything settled there is written down. **Read in this order:**

1. `docs/SPEC.md` (this file) — every settled decision, the ticket backlog, the operating rules.
2. `.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md` — **verified facts** that
   override `docs/BRIEF.md`. Four of the BRIEF's technical assumptions were tested and found
   wrong. Do not re-probe these.
3. `.claude/features/site-tuned-blend/clarity-design-tokens.md` — design tokens, needed at T3.
4. `docs/BRIEF.md` — business context, the pitch, and the demo page structure (§8). Its §10 open
   questions and §11 uncertainties are **all resolved**; see §15 of this file. Do not re-open them.
5. `.claude/pipeline/STATUS.md` — where the run currently is.
6. `.claude/active-work/site-tuned-blend/session-log.md` — what has been tried.

**The user is asleep and has explicitly said the loop must not need them.** There is no plan review
step. Do not ask questions. Do not wait for confirmation between phases. If something genuinely new
arises, apply §9's blocked-ticket rule: log it, skip it, keep going.

**Before the first ticket**, verify the environment is provisioned (§17). If it is not, T1 does it.

## 17. Provisioning (done while the user was awake, or by T1 if not)

```bash
brew install uv
uv python install 3.12
uv venv --python 3.12
uv pip install pandas pyarrow numpy requests xarray cfgrib eccodes fastapi uvicorn pytest httpx
brew install agent-browser || npm install -g agent-browser@0.36.0
agent-browser install
```

Smoke tests that must pass before relying on either:
```bash
uv run python -c "import cfgrib, xarray, pandas, pyarrow, fastapi; print('ok')"
agent-browser open https://example.com && agent-browser snapshot -i && agent-browser close
```

If the first fails after two genuine attempts, trigger the §11 R1 fallback.
If the second fails, drop agent-browser, note it in the session log, and continue. It must never
block a ticket.

**Keep the Mac awake for the duration:** `caffeinate -dimsu` in a separate terminal.
