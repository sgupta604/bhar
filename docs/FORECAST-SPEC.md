# FORECAST-SPEC — Forward Forecast Page for KOMA (v1)

**Written:** 2026-09-04, after the site-tuned-blend backtest shipped green (all six tickets, STATUS.md).
**Status of this document:** every decision below is SETTLED. This is the contract for the forecast page.
**Branch:** `feat/forecast-page`, cut from `develop`, batched into `main`.
**Remote:** `https://github.com/sgupta604/bhar.git`. **Pushing IS permitted** (unlike the backtest run).

> **Precedence.** This file governs **the forecast page only**. `docs/SPEC.md` is the contract for
> work that is already complete and **must not be edited** — where the two conflict about anything
> already built, SPEC wins; where they conflict about the forecast page, this file wins.
> `.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md` holds **verified facts** and
> overrides both. `docs/BRIEF.md` remains business context only.
>
> **Do not re-open settled questions.** Q12a, Q13, Q14, Q16 and Q17 are answered in §21's decision
> log with rationale. If something genuinely new arises, apply the blocked-ticket rule in §14.

---

## 1. Cold-start handoff — read this first

You are a fresh session with no memory of the conversation that produced this document. You do not
need it. Everything settled there is written down here. **Read in this order:**

1. **`docs/FORECAST-SPEC.md` (this file)** — every settled decision, the contract, the ticket
   backlog, the operating rules. §3 (hard boundaries) and §6 (what "confidence" means) are the two
   sections that, if skipped, produce a page that has to be thrown away.
2. **`docs/SPEC.md`** — the completed backtest. Read §3 (data), §4 (the join), §5 (method), §7 (the
   `results.json` contract), §10 (integrity rules). **Do not edit it.** It is why `data/results.json`
   is trustworthy, and this page is downstream of it.
3. **`.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md`** — verified GRIB and METAR
   facts. **F2, F4, F5, F9, F10 still apply verbatim** to the live fetch path. Do not re-probe them.
4. **`README.md`** — especially §8 (known caveats) and §9 ("how many variations did you try?").
   The caveats are the source material for the trust panel (§6). C2 in particular — ~30 independent
   days, not 120 — must survive onto the page.
5. **`backend/contract.py`** — the pattern for a locked, executable JSON contract. §9 of this file
   is written to be enforced the same way, by the same technique (exact key sets, named JSON paths,
   no bare `assert`).
6. **`.claude/features/demo-shell/design-target.md`** — the written `/design` output from T3, and
   the cheaper precedent for ticket F1 (§12). `.claude/features/site-tuned-blend/clarity-design-tokens.md`
   is the token source; read it before writing any CSS.
7. **`.claude/pipeline/STATUS.md`** and `.claude/active-work/forecast-page/session-log.md` — where
   the run currently is and what has been tried.
8. **`.claude/pipeline/WORKFLOW.md`** and `CLAUDE.md` — the pipeline and the orchestrator rules.
   `CLAUDE.md`'s Commands block is where test-agent reads its commands.

**F9 (`forecast-scorecard`) was added after F1-F8 were settled and is purely additive.** It depends
on F3 and F4, changes nothing about any other ticket, and records what the page predicted each cycle
then grades it as observations arrive — the live, forward-validated track record, and the instrument
that detects the August-fitted weights failing in December (§12, §13). If the clock is tight it can
land after F8 without disturbing anything.

**Before the first ticket**, confirm the environment still works — the venv is provisioned and must
not be rebuilt (SPEC §17):

```bash
uv run python -c "import cfgrib, xarray, pandas, pyarrow, fastapi; print('ok')"
uv run pytest -q          # MUST exit 0 before you change anything, and after every ticket
```

**The demo of the existing page happens at 16:00 and its path is off-limits.** Read §3 before you
open any file.

---

## 2. Purpose

A **forward temperature forecast for KOMA**, built by applying the site-tuned blend weights that
were fitted on 30 days of history, shown **alongside the evidence a viewer needs to judge how much
to trust it**.

The page answers two questions and no others:

1. **What is the temperature going to be at KOMA?** One number per forecast step, out to 48 hours.
2. **How much should I trust that?** Answered with **history** — how this blend has actually
   performed at this site, at this lead time, over the last 30 days — and never with a probability.

**Audience (Q14, SETTLED):** an **end customer** who wants one number plus "how much should I trust
it". Designed so it doubles as a **showcase for the API**. It is **not a forecaster's console**:
no model-soup panels, no synoptic charts, no ensemble plumes, no "expert mode".

**Direction (Q13, SETTLED):** **forward** by default, with a **back-arrow** that steps into past
days already scored by the existing pipeline — *"here is what we said, here is what happened."*
The back-arrow is what turns a claim into evidence, which is why it is a v1 ticket and not a v2 wish.

---

## 3. Hard boundaries — read before opening any file

**The forecast page must NOT touch the demo path.** The 16:00 demo depends on it, it is green, and
it is committed. The following are **off-limits** except where a ticket in §12 explicitly says
otherwise, and each exception is a single named line:

| Path | Status |
|---|---|
| `frontend/index.html`, `app.js`, `app.css`, `chart.js`, `models.js`, `format.js`, `theme.js`, `tokens.css`, `vendor/` | **OFF-LIMITS.** Do not edit, do not "refactor while I'm here". |
| `frontend/overview.html` and its assets | **OFF-LIMITS.** In flight on `feat/demo-overview`; `index.html` already links to it. |
| `backend/main.py` — existing endpoints, the app title, the CORS block | **OFF-LIMITS.** The FastAPI title `"Bhar - Site-Tuned Model Blend"` is the identity discriminator against the port-8000 squatter. Renaming it breaks `demo.sh`. |
| `backend/contract.py` | **OFF-LIMITS.** It locks the SPEC §7 shape and `/api/results` validates against it on every request. |
| `score/` (`join.py`, `metrics.py`, `blend.py`, `split.py`, `build.py`, `run.py`) | **OFF-LIMITS.** Read it, import from it if useful, never modify it. |
| `data/results.json`, `data/coverage.json`, `data/results.synthetic.json` | **READ-ONLY inputs.** The forecast page consumes `results.json`; it never rewrites it. |
| `docs/SPEC.md`, `docs/BRIEF.md` | **OFF-LIMITS.** |
| `run.sh`, `demo.sh` | **OFF-LIMITS** except the one line named in F8. |

**The only permitted edits outside brand-new files, and the only ticket allowed to make each:**

| File | Edit | Ticket |
|---|---|---|
| `backend/main.py` | **exactly one import + one `app.include_router(...)` line.** Nothing else. | **F4 only** |
| `.gitignore` | add `data/live/` and `data/forecast.json` | **F2 only** |
| `README.md` | one new section for the forecast page and its API | **F8 only** |
| `CLAUDE.md` | Commands block: add the refresh and forecast-serve commands | **F8 only** |
| `run.sh` / `demo.sh` | at most one added `echo` naming the forecast page URL | **F8 only** |
| `.claude/pipeline/STATUS.md`, `.claude/active-work/forecast-page/session-log.md`, plan checkboxes | pipeline state | orchestrator, always |

**Everything else the forecast page needs is a NEW file**, in one of three places:

- **`forecast/`** — a new top-level Python package. All new backend logic lives here. It may
  *import* from `fetch/` and read `data/`, and it must not modify either.
- **`backend/forecast_api.py`** — a FastAPI `APIRouter`, mounted by F4's one line in `main.py`.
- **`frontend/forecast.html`, `frontend/forecast.js`, `frontend/forecast.css`** — plus any new
  files they need. They may `<link>` the existing `vendor/clarity-tokens.css`, `vendor/fonts.css`
  and `tokens.css` (read-only reuse), and must not edit them.

**The regression gate, checked at the end of every ticket:** `uv run pytest -q` exits 0, `uv run
ruff check .` is clean, `git diff --stat` against the branch point shows **no changes to any
off-limits path**, and the existing demo page still loads and renders its leaderboard. A ticket that
breaks the demo path is not "mostly done"; it is reverted.

### Reuse, do not rewrite

`fetch/idx.py`, `fetch/grib.py` (`fetch_point`, `build_urls`, `decode_point`, `nearest_cell`,
`kelvin_to_f`, `ArchiveMissing`) and `fetch/schema.py` are **green and proven** — validated live
against all four models. The live-cycle fetcher **calls them**. It does not reimplement them, and it
does not "improve" them.

The following still apply and are not negotiable (spike F2, F9, F10):

- **Never hardcode a GRIB message index. Parse the `.idx` every time.** NBM's 2 m temperature
  message moves with lead time (187 / 192 / 195 at f006 / f012 / f024).
- **The needle is anchored: `":TMP:2 m above ground:"`**, with the leading colon. The unanchored
  form is a substring of `APTMP:2 m above ground` — apparent temperature, message 1 in NBM — and it
  was hit for real during validation.
- **Reject any index line containing `ens std dev`.**
- **Assert the decoded *data variable* is `t2m` and `GRIB_cfVarName` is `t2m`, and reject `aptmp`
  explicitly.** *(Corrected 2026-09-04: **`GRIB_shortName` is `"2t"` on valid data** and must NOT be
  compared to `"t2m"` — doing so fails on good data. This is what `fetch/grib.py` already does, and
  `tests/test_grib.py` has a regression test forbidding the `GRIB_shortName == "t2m"` form. Do not
  "fix" the working code to match an older wording of this rule; that error cost a hard failure on
  the first run of T2. `docs/SPEC.md` and the spike carry the same wrong literal and are off-limits
  to edit — this file wins on it.)*
- **NBM CONUS is the `.co` key.** `ak`/`hi`/`pr`/`gu` exist and are wrong for KOMA.
- **UTC everywhere.** Kelvin only inside the decoder; degrees F at every boundary.

---

## 4. Scope

**In:** one site (KOMA), 2 m temperature, the four models already in the blend, a forward forecast to
48 h, a 30-day back-arrow into already-scored history, a historical-skill trust panel, a live-cycle
fetch with a disk cache and staleness labelling, a locked JSON contract, three new read-only API
endpoints, a design pass, and documentation.

**Out, explicitly:**
- **Probabilistic output of any kind** — percentiles, confidence intervals, probability of
  exceedance, error bars around the forecast value. See §6. NOAA's NBM already publishes
  percentiles; competing there is out of scope and would be worse than what NOAA ships free.
- **Refitting the weights.** v1 applies the weights already in `data/results.json`. Refit cadence is
  §22's leading open question.
- More sites, more variables, precipitation, wind, bias correction / MOS, alerts, user accounts,
  a write API, a scheduler or cron, containers, and any change to the backtest pipeline.
- **Live fetch on the request path.** The page serves from cache. Always. §5.

---

## 5. Data and the live cycle

| Dimension | Value |
|---|---|
| Site | KOMA, 41.3032, -95.8941. Same site object as `results.json` `meta.site` — copy it, do not retype it. |
| Variable | 2 m temperature, **degrees F** at every boundary |
| Models | **HRRR, GFS, NAM, NBM** — exactly `meta.models_included` from `data/results.json`, in that order |
| Forward range (Q17, SETTLED) | **48 h** |
| Backward range (Q17, SETTLED) | **30 days** |
| Forward step | **3 h** (f003 … f048, 16 steps), subject to the F2 probe below. Hourly is v2. |
| Init runs | the four synoptic runs, 00z / 06z / 12z / 18z — the same set the weights were fitted on |
| Source | NOAA AWS S3 + `.idx` byte-range subsetting (spike F2). No other source. |

### 5.1 A live NOAA fetch is genuinely new

**Everything built so far reads the archive.** SPEC §6 bans live fetches from the demo path, and
`backend/main.py` deliberately has no refetch route ("an unpressed route is dead code"). The
forecast page therefore needs **its own fetch path**, and that path has one shape:

```
forecast.refresh (offline CLI)  ──> NOAA S3 ──> data/live/<cycle>/ (cache)
                                                data/forecast.json (built payload)
                                                        │
                              backend/forecast_api.py ──┘   (reads cache; never fetches)
                                                        │
                                            frontend/forecast.html
```

**The page NEVER blocks on NOAA.** `/api/forecast` reads a file off disk and returns it. If the file
is absent or fails the contract, it returns **503 with a reason** — never an empty-but-well-formed
payload, never a silent fallback to the fixture. That is the same rule `/api/results` already
follows, and for the same reason.

Refresh is invoked by a human or a future scheduler:
`uv run python -m forecast.refresh`. **No cron, no scheduler, no background thread in v1.**

### 5.2 Cycle selection, and the staleness rule (Q16, SETTLED)

- **Target cycle** = the most recent synoptic init at or before `now_utc − 4 h`. Four hours is the
  archive-latency margin; f003 of a cycle is not on S3 the instant the cycle starts.
- **If any included model 404s for the target cycle, fall back to the previous cycle** and try
  again. **Maximum 3 cycles back (18 h).** Beyond that, serve nothing and render the empty state
  with the reason. Never fabricate, never mix cycles.
- **Every forecast is labelled with its run time, always — not only when it is stale.**
  `Run 2026-09-04 12:00Z · 5 h old` is permanent page chrome, in the header, near the headline
  number. A run label that only appears when something is wrong trains the viewer to ignore it.
- `meta.cycle.is_stale` is `true` when the served cycle is **not** the target cycle (a fallback
  fired) **or** the cycle is more than **9 h** old. When `is_stale` is true the page shows a visible
  stale treatment in addition to the always-present run label, and names the reason.
- **Never mix models across cycles.** All four members of a blend come from the same init time, or
  that step is a gap. A blend whose members are from different runs is not the blend that was fitted.

> **Why this is a rule and not a preference.** Silently serving a stale forecast as current is the
> **forward-looking twin of the fake-green failure this project already hit once**: SPEC §4's empty
> join scored beautifully and was completely fake, and spike F1 found folkweather returning
> HTTP 200 with a plausible temperature for any date you asked for, clamped to its window edge and
> relabelled with your timestamp. A page that shows yesterday's 12z run as "now" fails in exactly
> that shape — confident, plausible, wrong, and undetectable from the outside. The run label is the
> guard, and it is why the label is unconditional.

### 5.3 The forward step grid — probe first

**F2's first task is a probe** (the verification-first rule that made T2 work): for one recent
synoptic cycle, list which forecast hours in 0–48 each of the four models actually publishes.

- The page's step grid is the **intersection** across all four models, recorded in the payload as
  `meta.horizon_h` and `meta.step_h`, with the probe's findings written into the F2 findings note.
- **Acceptance floor: 3-hourly to 48 h must work for all four models.** If a model's horizon ends
  earlier (HRRR's sub-hourly cycles and NAM's `awphys` files are the likely constraints), the page
  **truncates its horizon to what all four cover and labels it.** Steps beyond that are rendered as
  a **gap**, listed in the payload's `gaps` array with the missing models named.
- **Never renormalize the weights over a subset of models to fill a gap.** A three-model
  renormalization is a *different blend* than the one that was fitted, and the skill numbers on the
  page do not apply to it. A gap is honest; a substituted blend is not.

---

## 6. Confidence means HISTORICAL SKILL ONLY — integrity rule (Q12a, SETTLED)

**This is the single most important section in this document.**

The trust panel shows **how this blend has performed at this site, at this lead time, over the
scored 30-day window**. It is **history**. It is stated in the **past tense**. It is **never** a
promise, a probability, or an interval around tomorrow's number.

**Why this is an integrity rule and not a style preference.** Rendering past MAE as a confidence
band around a future number claims that **past skill transfers to this particular forecast**. It
does not, and it fails *hardest during exactly the extreme events people care about* — the heat
wave, the ice storm, the frost that decides whether you cover the crop. A ±2 °F band drawn from a
placid August is at its most confident and its most wrong on the day the customer most needs it.
NOAA's NBM already publishes calibrated percentiles; a hand-rolled interval fitted on ~30
independent days would be worse than the free thing and would misrepresent it as better.

### 6.1 Required framing

Every skill statement on the page must be:

- **Past tense**, and must name its window: *"Over the last 30 days at KOMA…"*.
- **Attached to a lead time**: skill at 6 h and skill at 42 h are different claims.
- **Attached to a sample size**, and that sample size is **~30 independent days, not 120** —
  README C2. Four runs a day share a weather regime.
- **Out of sample**, from the 20/10 chronological split. The in-sample number may appear beside it,
  labelled, never alone.

Acceptable phrasing: *"Over the last 30 days, this blend's typical miss at a 6-hour lead was
1.92 °F — better than the best single model (HRRR, 2.11 °F) over the same period. That is history,
not a promise about this forecast."*

### 6.2 Banned outright

These must not appear in the payload, in the UI, or in the API docs:

- Any field named or rendered as `confidence`, `confidence_pct`, `probability`, `p10`, `p50`, `p90`,
  `percentile`, `ci_low`, `ci_high`, `error_bar`, `uncertainty`.
- The character `±` attached to a forecast value.
- "We are N% confident", "there is an N% chance", "expected error of ±X", "accurate to within X".
- Any visual that renders a band, ribbon, shaded envelope, or whisker **around the forecast line**.

**The contract validator enforces this** (§9): `forecast/contract.py` rejects unexpected keys with
the same exact-key-set technique `backend/contract.py` already uses, and a unit test asserts each
banned key name is rejected.

### 6.3 Model spread is allowed, with one rule

`members` (each model's own forecast at that step) and a derived `member_spread_f` (max − min) may
be shown, because **they are facts about the models, not a probability**. They may be rendered as a
"how much the models disagree right now" indicator — a small figure, a strip, a sparkline of the
four member values.

**They must never be drawn as an error bar around the blend value, and never converted into a
percentage.** Disagreement is not calibrated uncertainty and the page must not imply it is.

---

## 7. Applying the fitted weights forward

**The weights come from `data/results.json`** — read-only, contract-validated on load with
`backend.contract.load_and_validate`. For each lead, the fitted vector is
`results["<lead>"].winner`'s weight vector, found by matching `winner.label` against `blends[].label`
(the label identifies exactly one blend — `backend/contract.py` guarantees it; **never use
`blends[0]`**, which is the out-of-sample leader, not the fitted choice).

The backtest fitted weights at **three leads only: 6, 12, 24 h**. The page forecasts out to 48 h.
The mapping is fixed, banded, and visible in the payload:

| Forecast lead | Weight vector used | `is_extrapolated_lead` |
|---|---|---|
| 3 – 9 h | the **6 h** fitted vector | `false` |
| 12 – 18 h | the **12 h** fitted vector | `false` |
| 21 – 24 h | the **24 h** fitted vector | `false` |
| **27 – 48 h** | the **24 h** fitted vector | **`true`** |

Rule: **nearest fitted lead by absolute difference, ties to the shorter lead.** Every forecast row
carries `weights_fitted_at_lead_h` so the mapping is inspectable, and `is_extrapolated_lead` is
`true` for any lead **beyond 24 h** — outside the range where any weight was ever fitted or verified.

**The UI must visibly mark the 24–48 h region as beyond the fitted range**, and the trust panel must
not quote a skill number for a lead the backtest never measured. For extrapolated leads the panel
says so: *"No skill measurement exists beyond a 24-hour lead. These hours use the 24-hour weights
and are unverified."* Inventing an interpolated MAE for a 42 h lead is exactly the tuning §15 bans.

### 7.1 Weight staleness

`meta.weights_source` carries `results.json`'s `generated_at`, its `window`, its `split` and a
derived `weights_age_days`.

**Say plainly, on the page and in the API docs: weights fitted on 30 days of August do not
necessarily hold in December.** The atmosphere's regime changes; a blend tuned on summer convection
has no claim on winter inversions, and KOMA has both. When `weights_age_days > 45` the page shows a
visible note that the weights are stale and names the window they were fitted on.

**Refit cadence is an open v2 question (§22).** v1 does not refit, does not schedule a refit, and
does not pretend to know the right interval.

---

## 8. Architecture

```
data/results.json (READ-ONLY) ──> forecast/weights.py ─┐
                                                       │
NOAA S3 (.idx + range, via fetch/) ──> forecast/live.py├─> forecast/build.py ─> data/forecast.json
                                       forecast/cycle.py                             │
                                       data/live/<cycle>/ (cache, gitignored)        │
                                                                                     │
data/forecasts.parquet + obs.parquet ─> forecast/history.py ─> data/forecast_history.json
                                                                                     │
                                    forecast/contract.py  (validates both)           │
                                                                                     v
                                    backend/forecast_api.py (APIRouter, read-only) <─┘
                                                       │  mounted by ONE line in backend/main.py
                                                       v
                                    frontend/forecast.html  (Clarity-styled)
```

**New modules, all under `forecast/`:**

| Module | Job |
|---|---|
| `forecast/cycle.py` | target-cycle selection, the ≤3-cycle fallback, staleness computation |
| `forecast/live.py` | fetch one whole cycle for all models × steps via `fetch.grib.fetch_point`; write and read the `data/live/<init>/` cache |
| `forecast/weights.py` | load `results.json`, extract the fitted vector per lead, implement §7's banding |
| `forecast/build.py` | assemble the §9 payload |
| `forecast/history.py` | build the §10 history payload from `data/forecasts.parquet` + `data/obs.parquet` |
| `forecast/contract.py` | the locked validators for both payloads |
| `forecast/make_fixture.py` | a synthetic, banner-flagged fixture of both payloads |
| `forecast/refresh.py` | the CLI: `uv run python -m forecast.refresh` |

**Caching.** `data/live/<YYYYMMDDHH>/` holds the raw decoded points as JSON, one file per
(model, lead), so a re-run of `refresh` for the same cycle costs no network. `data/live/` and
`data/forecast.json` are **gitignored** — `forecast.json` goes stale by definition, and committing a
stale forecast into the repo is the §5.2 failure with a version number on it.

`data/forecast_history.json` **is committed**: history does not go stale, the parquets that produce
it are gitignored, and without it a fresh clone cannot render the back-arrow at all.

---

## 9. `forecast.json` contract — LOCKED FIRST, before the fetcher or the page

Contract-first, exactly as T3 did it. `forecast/contract.py` enforces this shape; `make_fixture.py`,
`build.py` and the API all validate against the same function.

```jsonc
{
  "meta": {
    "site": { /* copied verbatim from results.json meta.site */ },
    "variable": "2m_temperature",
    "units": "degF",
    "cycle": {
      "init_time": "2026-09-04T12:00:00Z",
      "run_label": "12z",
      "target_init_time": "2026-09-04T12:00:00Z",  // what we WANTED; differs if a fallback fired
      "fetched_at": "2026-09-04T17:04:00Z",
      "age_minutes": 304,
      "is_stale": false,
      "stale_reason": null,          // e.g. "fell back 1 cycle: HRRR f021 absent from archive"
      "cycles_fallen_back": 0
    },
    "weights_source": {
      "path": "data/results.json",
      "generated_at": "2026-09-04T12:53:01Z",
      "weights_age_days": 0,
      "window": {"start": "...", "end": "...", "days": 30},
      "split": {"method": "chronological", "train_days": 20, "test_days": 10},
      "fitted_leads": [6, 12, 24]
    },
    "models_included": ["HRRR", "GFS", "NAM", "NBM"],
    "horizon_h": 48,
    "step_h": 3,
    "source": "noaa_s3_grib",
    "generated_at": "2026-09-04T17:04:12Z",
    "is_synthetic": false            // TRUE for the fixture. The page MUST show a banner.
  },
  "forecast": [
    {
      "valid_time": "2026-09-04T15:00:00Z",
      "lead_h": 3,
      "blend_f": 78.41,
      "weights": {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.4},
      "weights_fitted_at_lead_h": 6,
      "is_extrapolated_lead": false,
      "members": {"HRRR": 78.20, "GFS": 79.90, "NAM": 78.05, "NBM": 78.71},
      "member_spread_f": 1.85
    }
  ],
  "gaps": [
    {"valid_time": "2026-09-06T12:00:00Z", "lead_h": 48,
     "missing_models": ["NAM"], "reason": "beyond model horizon"}
  ],
  "skill": {
    "basis": "historical_out_of_sample",
    "window": {"start": "...", "end": "...", "days": 30},
    "note": "Measured over the 30-day backtest window. History, not a prediction about this forecast.",
    "by_lead": [
      {"lead_h": 6, "blend_mae": 1.9173, "blend_mae_in_sample": 1.7793,
       "best_single_model": "HRRR", "best_single_mae": 2.1075,
       "improvement_pct": 9.0249, "n_test": 40, "independent_days_approx": 30}
    ]
  }
}
```

**Contract rules, all enforced in `forecast/contract.py` and all unit-tested:**

1. **Exact key sets at every level.** An unexpected key is an error, naming its JSON path. This is
   what makes §6.2's ban executable — a `p90` or a `confidence_pct` anywhere fails validation.
2. `forecast` is sorted by `valid_time` ascending, strictly increasing, no duplicates.
3. Every row's `lead_h` equals `(valid_time − meta.cycle.init_time)` in whole hours.
4. `weights` keys are exactly `meta.models_included`; values are multiples of 0.1 in [0,1] summing
   to 1.0 within 1e-9 (the fitted grid is step 0.1 — SPEC §5).
5. `weights_fitted_at_lead_h` ∈ `meta.weights_source.fitted_leads`, and matches §7's banding table
   for that `lead_h`. `is_extrapolated_lead` is `true` **iff** `lead_h > max(fitted_leads)`.
6. **`blend_f` must equal `sum(weights[m] * members[m])`** within 1e-6. *This is the forward twin of
   T5's one-hot identity test and is **NON-NEGOTIABLE**: if the displayed number is not the weighted
   sum of its members, the page is showing a number with no provenance.*
7. `members` keys are exactly `meta.models_included`; no member is null. A step missing any member
   belongs in `gaps`, not in `forecast`.
8. A `valid_time` appears in `forecast` **or** in `gaps`, never both, never neither — the union
   covers the whole step grid to `horizon_h`.
9. `is_synthetic` must be a JSON boolean. The string `"true"` is not a boolean and would defeat the
   banner (the exact check `backend/contract.py` already makes).
10. `skill.by_lead` covers exactly `meta.weights_source.fitted_leads`. **No entry may be synthesized
    for an unfitted lead.**
11. `cycle.is_stale` is `true` **iff** `cycles_fallen_back > 0` or `age_minutes > 540`, and
    `stale_reason` is non-null exactly when `is_stale` is true.

---

## 10. History payload contract — the back-arrow

`data/forecast_history.json`, built offline by `forecast/history.py` from `data/forecasts.parquet`
and `data/obs.parquet`, using the same fitted weights. **Committed to the repo.**

```jsonc
{
  "meta": {
    "site": { /* verbatim from results.json */ },
    "variable": "2m_temperature", "units": "degF",
    "window": {"start": "...", "end": "...", "days": 30},
    "leads_available": [6, 12, 24],
    "weights_source": { /* same shape as §9 */ },
    "generated_at": "...", "is_synthetic": false
  },
  "days": [
    {
      "date": "2026-09-02",
      "entries": [
        {"valid_time": "2026-09-02T18:00:00Z", "lead_h": 6,
         "init_time": "2026-09-02T12:00:00Z",
         "blend_f": 81.24, "observed_f": 80.00,
         "error_f": 1.24, "obs_offset_min": -8,
         "members": {"HRRR": 81.0, "GFS": 82.4, "NAM": 80.9, "NBM": 81.3},
         "best_single_model_f": 81.0}
      ],
      "mae_f": {"6": 1.31, "12": 1.88, "24": 2.40}
    }
  ]
}
```

**Rules:**

- **Only leads 6, 12 and 24 h appear.** They are the only leads the archive was fetched at.
  The forward page is 3-hourly; the back-arrow is three leads. **Say this on the page** rather than
  letting a viewer assume the past view is a downsampled version of the future one. A 3-hourly past
  curve means refetching the archive at every step — that is v2.
- **`observed_f` comes from the same ±30-minute nearest-observation join the backtest used**
  (SPEC §4, spike F5) — METAR is not on the hour, `OMA` reports near `:53`. **`obs_offset_min` is
  recorded on every row**, as the backtest does. **Observations are never interpolated; a missing
  observation drops the row.**
- **Assert on match counts.** A day with zero matched entries is omitted from `days` with the reason
  recorded, not emitted as a day with a perfect score. An empty join scores perfectly and is fake.
- `error_f` is signed (`blend_f − observed_f`) so bias is visible, and the UI labels the sign.

---

## 11. API surface

Three **read-only GET** endpoints, on an `APIRouter` in `backend/forecast_api.py`, mounted by F4's
single line in `backend/main.py`. **No live fetch on any request path. No POST, no write, no
refetch route** — an unpressed route is dead code, and this one would also be a way to make the page
block on NOAA.

| Endpoint | Returns | On failure |
|---|---|---|
| `GET /api/forecast` | `data/forecast.json` whole, contract-validated on every request | **503** naming the reason: no cache, or the contract path that failed |
| `GET /api/forecast/history` | `data/forecast_history.json` whole, contract-validated | **503** with the reason |
| `GET /api/forecast/skill` | the `skill` block alone — the "sell it as an API" demo call | **503** with the reason |

- Validated per request, as `/api/results` already is, so a rebuilt file is picked up without a
  restart.
- **Never return an empty-but-well-formed payload. Never silently fall back to the synthetic
  fixture.** Both render a page that looks fine and is wrong.
- CORS is already configured app-wide in `main.py` for `localhost`/`127.0.0.1` on any port. F4 must
  not touch it.
- Each endpoint gets a real FastAPI `summary` and `description`, because `/openapi.json` and
  `/docs` are part of the API story F8 documents.

---

## 12. Ticket backlog

Nine tickets, each through the full pipeline `/research → /plan → /implement → /test → /finalize`.
`/finalize` = commit + `SUMMARY.md` + **push to `origin`** (a remote exists now).
Branch: `feat/forecast-page` off `develop`.

> **Who writes acceptance criteria.** What follows is an **acceptance FLOOR**, not the finished
> list. `plan-agent` writes the full criteria when the ticket reaches `/plan`, in its own format,
> with whatever the architecture implies. The floor is the **minimum that must be present** —
> plan-agent **may add to it and must never drop from it.** Items marked NON-NEGOTIABLE exist
> because without them the page can produce a confident, fake number.

---

### F1 — `forecast-design` · the visual target
Produce the visual target for the forecast page **before any UI is built**, mirroring the SPEC §12
precedent that made T3's frontend land in one pass.

**Two acceptable forms — the implementer chooses based on the clock:**
- The **`design` skill**, which produces a multi-artboard canvas published as an Artifact. Richer,
  and better if the page's layout is genuinely uncertain. Costs more wall time.
- A **written `design-target.md`**, as T3 did — see `.claude/features/demo-shell/design-target.md`
  (450 lines: per-region specs, literal CSS for the two Clarity gaps, numeric formatting rules).
  **This is the cheaper precedent and it is known to work.** If the clock is tight, write the doc.

**Scope:** headline number + run label; the 48 h forward strip with the 24 h fitted-range boundary
marked; the gap treatment; the trust panel; the back-arrow control and the past-day view; the stale
treatment; the synthetic banner; the empty state.
**Non-goals:** writing any HTML/CSS/JS; redesigning `index.html`; new design tokens.
**Depends on:** nothing.
**Acceptance floor:** an artefact at `.claude/features/forecast-page/design-target.md` (or a canvas
URL recorded in that file). It specifies, concretely: the run-label treatment (§5.2, always visible);
the visual boundary at the 24 h fitted-range edge (§7); the gap rendering (§5.3); the trust panel's
exact past-tense copy (§6.1); the stale treatment; the synthetic banner. **It states which Clarity
tokens are used for each and names any gap Clarity does not cover, with literal CSS for it** —
Clarity has no slider, no chart-axis and no timeline/strip tokens. **No `±`, no band, no ribbon
around the forecast line anywhere in the design (§6.2).**

### F2 — `forecast-live-fetch` · live cycle, disk cache, staleness — HIGHEST RISK, do early
The first genuinely new capability in the project: fetch a *current* cycle rather than the archive.

**First task is a probe** (the verification-first rule): for one recent synoptic cycle, determine
which forecast hours in 0–48 each of the four models publishes, and record it in the findings.
**Do not build the cache on an assumed step grid.**

**Scope:** `forecast/cycle.py`, `forecast/live.py`, the `data/live/<init>/` cache, `.gitignore`.
Reuses `fetch.grib.fetch_point` and `fetch.idx` unchanged.
**Non-goals:** building the payload (F3); any endpoint (F4); any UI; a scheduler; touching `fetch/`.
**Depends on:** nothing.
**Acceptance floor:**
- The probe's findings are written down, and `meta.horizon_h`/`step_h` are **derived from them**,
  never hardcoded from this document.
- A real fetch of one cycle for all four models across the step grid succeeds and caches to
  `data/live/<init>/`; a second run of the same cycle **makes zero network requests** (proven by a
  test with a fetch stub that raises).
- **`.idx` parsed every time; no message index hardcoded anywhere** (spike F2/F10) — NON-NEGOTIABLE.
- **Unit test that the anchored needle rejects `APTMP:2 m above ground` and `ens std dev`**, and
  that a decoded **data variable / `GRIB_cfVarName`** other than `t2m` raises, and that `aptmp` is
  rejected explicitly (spike F9) — NON-NEGOTIABLE. *(Assert on the data variable and
  `GRIB_cfVarName`, **never** on `GRIB_shortName`, which is `"2t"` on valid data — §3.)*
- Cycle selection, the ≤3-cycle fallback and `is_stale`/`stale_reason` are unit-tested against a
  frozen clock, including: target available (no fallback), one model 404 (fall back one, reason
  recorded), three consecutive cycles unavailable (**serve nothing**, do not fabricate).
- **`ArchiveMissing` (404/403) is a fallback trigger, never a crash; every other non-200 raises.**
- No live-network test in the suite (SPEC §13). The live run is manual, its output recorded.

### F3 — `forecast-payload` · forward blend + the locked contract
Apply the fitted weights forward and lock the §9 contract.

**Scope:** `forecast/weights.py`, `forecast/build.py`, `forecast/contract.py`,
`forecast/make_fixture.py`, `forecast/refresh.py`.
**Non-goals:** the endpoint (F4); any UI; refitting weights; touching `score/` or `results.json`.
**Depends on:** F2 (for real data — but the **fixture path must work without F2**, so F5 is never
blocked on the network; this is T3's insurance repeated deliberately).
**Acceptance floor:**
- `forecast/contract.py` validates the §9 shape with **exact key sets** and error messages naming
  the JSON path, in the style of `backend/contract.py`. **No bare `assert`** — assertions vanish
  under `python -O` and this file is the only thing between the page and a fabricated number.
- **NON-NEGOTIABLE: a test proving `blend_f == sum(weights[m] * members[m])` for every row**, and a
  test that a row where it does not hold is **rejected**. This is the forward twin of T5's one-hot
  identity test.
- **NON-NEGOTIABLE: tests that each banned field name from §6.2** (`confidence_pct`, `p10`, `p90`,
  `percentile`, `ci_low`, `ci_high`, `error_bar`, `uncertainty`, `probability`) **is rejected by the
  validator.**
- Weights are read from `data/results.json` via `backend.contract.load_and_validate`, matched by
  `winner.label`, **never by `blends[0]`**. A missing or contract-failing `results.json` **raises
  with a reason** — there is no default weight vector and no silent equal-weight substitute.
- §7's banding table is unit-tested at each boundary (3, 9, 12, 18, 21, 24, 27, 48 h), and
  `is_extrapolated_lead` is `true` **iff** `lead_h > 24`.
- `gaps` ∪ `forecast` covers the full step grid exactly once; a step missing any member lands in
  `gaps` and **the weights are not renormalized**.
- `make_fixture.py` writes a payload with `is_synthetic: true` that **passes the same validator**.
- `uv run python -m forecast.refresh` writes `data/forecast.json` atomically (temp file + rename,
  as `score/run.py` does) and refuses to write a document that fails validation.

### F4 — `forecast-api` · the three endpoints
**Scope:** `backend/forecast_api.py` (an `APIRouter`), plus **exactly one import + one
`app.include_router(...)` line** in `backend/main.py`.
**Non-goals:** any other change to `main.py` — not the title, not CORS, not `/health`, not
`/api/results`. No live fetch on any request path. No POST.
**Depends on:** F3.
**Acceptance floor:**
- The three §11 endpoints return validated payloads and **503 with a named reason** when the file is
  absent or fails the contract. Tested: missing file, malformed JSON, contract violation.
- **A test asserting `/api/results` and `/health` still behave exactly as before**, and that
  `/openapi.json`'s `title` is still `"Bhar - Site-Tuned Model Blend"` (the squatter discriminator
  `demo.sh` depends on).
- `git diff backend/main.py` shows **exactly two added lines**. Verified, not assumed.
- Each endpoint carries a real `summary`/`description` — they are the API showcase.

### F5 — `forecast-page` · the UI
**Scope:** `frontend/forecast.html`, `forecast.js`, `forecast.css`. Reuses `vendor/clarity-tokens.css`,
`vendor/fonts.css`, `tokens.css` read-only, and mirrors `theme.js`'s pre-hydration inline theme
script and the `internal-portal:theme` localStorage key so the two pages agree in dark mode.
**Non-goals:** editing any existing frontend file; the back-arrow (F6); the trust panel's deep
content (F7 — F5 leaves a placeholder region); any charting library.
**Depends on:** F1, F3 (renders against the fixture; does not need F2).
**Acceptance floor:**
- Page loads, renders the headline number, the forward strip to `horizon_h`, and the **run label
  visible without scrolling** (§5.2).
- **The 24 h fitted-range boundary is visually marked** and extrapolated hours are labelled (§7).
- **Gaps render as gaps** — visibly absent, never interpolated across, never back-filled.
- `is_stale: true` produces the stale treatment **and** names the reason.
- `is_synthetic: true` produces a visible banner and a `[SYNTHETIC]` title prefix, gated on the
  single boolean (the `data-synthetic` attribute pattern `app.js` already uses).
- The 503 empty state shows the server's reason. It never renders a blank-but-styled page.
- **NON-NEGOTIABLE: no `±`, no band, no ribbon, no whisker around the forecast value anywhere**, and
  a grep of `forecast.html`/`.js`/`.css` for the §6.2 banned strings returns nothing.
- **`frontend/index.html` and every existing frontend file are byte-identical to the branch point**,
  and the existing demo page still loads and renders its leaderboard.
- agent-browser smoke check passes and a screenshot lands in
  `.claude/active-work/forecast-page/screenshots/`. Droppable per SPEC §11 R5 — it must never block
  the ticket.

### F6 — `forecast-history` · the back-arrow into scored history
*"Here is what we said, here is what happened."*

**Scope:** `forecast/history.py`, the §10 validator additions in `forecast/contract.py`,
`data/forecast_history.json` (committed), and the back-arrow UI in `frontend/forecast.*`.
**Non-goals:** rescoring anything; touching `score/`; extending the archive to new leads; a
3-hourly past curve (v2).
**Depends on:** F4, F5.
**Acceptance floor:**
- 30 days of past days, each with what the blend said and what was observed, at leads 6/12/24.
- **The ±30-minute nearest-observation join is used and `obs_offset_min` is recorded on every row**
  (SPEC §4, spike F5) — NON-NEGOTIABLE. **Observations are never interpolated.**
- **Assert on match counts**: a day with no matched entries is omitted **with a recorded reason**,
  never emitted as a scored day. An empty join scores perfectly and is fake — NON-NEGOTIABLE.
- The UI states plainly that the past view shows three leads because those are the leads the
  archive was fetched at, and that this is not a downsample of the forward view.
- Signed error is shown with its sign labelled, so a warm bias reads as a warm bias.
- `data/forecast_history.json` is committed and a fresh clone renders the back-arrow with no
  parquet files present.

### F7 — `forecast-skill-panel` · the trust panel
**Scope:** the trust panel in `frontend/forecast.*`, driven by `skill` from `/api/forecast` and the
realized errors from `/api/forecast/history`.
**Non-goals:** computing new metrics; any probabilistic output; anything that implies past skill
transfers to this forecast.
**Depends on:** F4, F5 (and F6 for the realized-error strip).
**Acceptance floor:**
- Every skill statement is **past tense**, names its **window**, names its **lead time**, and is the
  **out-of-sample** number, with the in-sample number beside it, labelled (§6.1).
- **Sample size is stated as ~30 independent days, not 120**, with README C2's reason in one
  sentence — NON-NEGOTIABLE.
- The blend's historical MAE is shown **against the best single model's**, at the same lead. A zero
  or negative improvement renders honestly (SPEC §10 — `improvement_pct` may legitimately be ≤ 0).
- **For extrapolated leads (>24 h) the panel says no skill measurement exists**, and quotes no
  number — NON-NEGOTIABLE.
- **The weights-fitted-on-August caveat appears in the panel**, in the customer's language, with the
  fitted window's dates (§7.1).
- **NON-NEGOTIABLE: nothing in the panel is phrased as a probability or a promise.** A reviewer
  reading only the panel must be unable to conclude "there is an N% chance" or "±X °F".

### F8 — `forecast-docs` · README, API docs, commands
**Scope:** a new `README.md` section; the `CLAUDE.md` Commands block; at most one added `echo` in
`run.sh`/`demo.sh`; the API reference for the "sell it as an API" story.
**Non-goals:** rewriting any existing README section; editing `docs/SPEC.md`; marketing copy.
**Depends on:** everything; do it last.
**Acceptance floor:** a reader who was not here can, from the README alone: refresh a cycle, start
the server, open the forecast page, and call all three endpoints with `curl` and understand the
response. It states in plain language: **what "confidence" means here and what it deliberately is
not** (§6); that weights fitted in August may not hold in December and that refit cadence is
unresolved; the 24 h fitted-range boundary; the staleness/fallback rule and how to read the run
label; and that the forward page and the back-arrow use different lead grids and why. The
`CLAUDE.md` Commands block gains the refresh and forecast-serve commands — **test-agent reads its
commands from there and cannot run what is not listed.**

### F9 — `forecast-scorecard` · the live, forward-validated track record
*"Here is what we said yesterday, here is what happened, and here is the running score."*

The 30-day study is a **backtest**. F6's back-arrow replays days that were already in the archive
when the weights were fitted. F9 is different in kind: from the day it lands, every cycle **records
what was predicted before the outcome exists**, and grades itself as observations arrive. After a
few weeks that is dramatically stronger evidence than any backtest, because **nobody can claim it
was fitted** — the predictions were written down first, in an append-only ledger, and the grading
is arithmetic.

It also closes a limitation this document already concedes. §7.1 and §22.1 admit the weights were
fitted on **30 days of August and nothing proves they survive December**. F9 is the instrument that
detects exactly that: a model whose realized error at this site is drifting shows up in the record
long before anyone would think to re-run the backtest, and the answer to "when should we refit?"
becomes an observation instead of a guess.

**Scope:** `forecast/scorecard.py` (record, grade, and the pure scorecard function), the append-only
JSONL ledger `data/forecast_ledger.jsonl` (**committed**, see below), a `GET
/api/forecast/scorecard` endpoint added to the **existing** `backend/forecast_api.py` router, and a
scorecard region in `frontend/forecast.html` / `forecast.js` / `forecast.css`.

**Non-goals:** refitting weights (F9 *detects* drift; it never acts on it); changing the blend, the
weights, or `data/results.json`; rescoring the backtest or touching `score/`; a cron job, a daemon,
a launchd plist or any background process; a second router or a second mount line in
`backend/main.py`; any new probabilistic output (§6.2 applies here verbatim).

**Hard boundaries:**
- **Zero lines added to `backend/main.py`.** F9's endpoint lives on the `APIRouter` F4 already
  mounted. If F4 has not landed, F9 is blocked — it does not mount its own router.
- **The 16:00 demo path is untouched:** `frontend/index.html`, `frontend/overview.html`, `app.js`,
  `app.css`, `models.js`, `theme.js`, `tokens.css`, `backend/contract.py`, `score/`,
  `data/results.json`. Verified by `git diff --stat`, not assumed (§3).
- **No `.gitignore` edit** (that is F2's single permitted line). The ledger is **committed**, for
  the same reason `data/forecast_history.json` is (decision 14): a track record that a fresh clone
  cannot see is not a track record, and a gitignored one is one `git clean` away from being erased —
  which is also the one way this ticket could be made to look better than it was.
- The README section and the `CLAUDE.md` Commands-block entry for F9's commands are written by
  **F8**, under F8's existing permission. F9 does not edit either file.

**Depends on:** F3 (it records from the validated `forecast.json` payload) and F4 (its endpoint
joins the existing router). It does **not** depend on F5, F6 or F7 — the ledger and the scorecard
JSON are useful with no UI at all, and grading works against F3's fixture path.

**Design, settled — write these as decisions, not options:**

1. **Record all four models AND the blend, every cycle.** Not the blend alone. The marginal cost is
   a few numbers per row; the payoff is seeing **which model is drifting at this site**, which is
   the refit signal, and a standing per-model track record at one site is independently sellable.
2. **Grading is LAZY, never scheduled.** Whenever the page or the endpoint loads, grade everything
   now gradeable. A scheduled job on a laptop stops silently and you find out mid-demo; lazy grading
   has nothing to die, self-heals after arbitrary downtime, and makes the page true whenever it is
   opened. **A manual command forces a pass** for when you want it graded now.
3. **When the blend LOSES, show it plainly, at the same visual weight as a win.** No de-emphasis, no
   rolling average smoothing a bad week away, no restarting the record. This is the entire
   credibility argument: a scorecard that only looks good when it is winning is marketing, and the
   room will assume it is. Losing streaks are recorded and shown explicitly, because that is the
   signal that answers "when should we refit?".

**Acceptance floor:**
- **Every cycle recorded writes one prediction row per lead for each of the four models *and* the
  blend** — a test asserts the row count equals `(len(models_included) + 1) x len(steps)` for a
  recorded payload, so the blend-only shortcut fails the suite.
- **NON-NEGOTIABLE: the ledger is append-only and a past record is never overwritten or re-graded.**
  A test proves that re-running record on an already-recorded `init_time` appends nothing and
  mutates nothing, that grading an already-graded row appends nothing and leaves the first grade
  byte-identical, and that no code path opens the ledger in a truncating mode. Following
  `fetch/backfill.py`'s proven precedent: **one JSON object per line, every key present every time,
  latest-wins on read, a missing file is an empty ledger rather than an error.**
- **NON-NEGOTIABLE: the scorecard is a pure function of the ledger.** Same ledger in, same JSON out,
  computed **offline with no network and no clock dependency beyond an injected `now`**, tested
  against a committed fixture ledger. Nothing is carried in memory between calls; the ledger on disk
  is the only state (`.claude/features/data-backfill/SUMMARY.md`).
- **NON-NEGOTIABLE: observations come from IEM ASOS `OMA` via the existing path, joined with the
  ±30-minute nearest-observation rule, and `obs_offset_min` is recorded on every graded row**
  (SPEC §4, spike F5). **An exact-timestamp join matches zero rows and scores perfectly, which is
  fake** — a test asserts a non-zero match count, and a grading pass that matches nothing raises
  rather than reporting a clean sheet. **Observations are never interpolated.**
- **A day, lead or model with a missing forecast or a missing observation is recorded as a gap with
  a stated reason — never imputed, never interpolated, never renormalized around.** Gaps appear in
  the scorecard as gaps and are excluded from every mean, and the denominator each statistic used is
  stated beside it.
- **Lazy grading, proven twice:** a test that loading the endpoint grades every row that became
  gradeable since the last load; and a test with an observation-fetch stub that raises, proving the
  endpoint still returns the scorecard built from the rows already graded, marks the rest `pending`,
  and **never 503s and never blocks on the network** — the pass runs under a hard wall-clock
  deadline and a timeout is an ungraded row, not an error page. `/api/forecast`,
  `/api/forecast/history`, `/api/forecast/skill` and `/api/results` gain **no** network dependency;
  a test asserts their behaviour is unchanged.
- **A manual command forces a grading pass** (`uv run python -m forecast.scorecard --grade`, with
  `--record` for the recording pass) and prints what it graded, what it skipped, and why. It is the
  same code path the endpoint uses, not a parallel implementation.
- **NON-NEGOTIABLE: losses render at the same visual weight as wins.** The acceptance check is run
  against a **losing fixture ledger** as well as a winning one: the losing case uses the same type
  scale and the same colour role, no muted or de-emphasised token, no smoothing, and the page shows
  **the current and longest streaks in which the blend was beaten by the best single model**. A
  scorecard that has only ever been checked while winning does not pass this ticket.
- **Per-model realized MAE over the live record is reported next to the blend's**, so the drifting
  model at this site is visible; the panel states, in the customer's language, that the weights were
  fitted on August days (§7.1) and that a sustained divergence here is the refit signal — while
  **naming no refit cadence**, which is still open (§22.1).
- Every statement is **past tense, realized error only, with its window and lead named** (§6.1).
  **No `±`, no band, no probability, and a grep for the §6.2 banned strings in the new files returns
  nothing** — a live track record is the easiest place in the project to accidentally start
  promising something.
- `data/forecast_ledger.jsonl` is committed and a **fresh clone renders the scorecard** with no
  parquet files and no network. An empty or too-short record renders an honest "not enough days yet,
  N recorded" state — never a blank-but-styled panel and never an extrapolated score.
- The regression gate of §3 passes: `uv run pytest -q` exits 0, `uv run ruff check .` is clean,
  `git diff --stat` shows no off-limits path touched, and the existing demo page still loads and
  renders its leaderboard.

---

## 13. Dependency graph

```
F1 (design) ──────────────┐
                          ├──> F5 (page UI) ──┬──> F6 (back-arrow) ──┐
F2 (live fetch) ─> F3 (payload) ─> F4 (API) ──┴──> F7 (skill panel) ─┤
                          │            │                             ├──> F8 (docs)
                          │            └──> F9 (scorecard) ──────────┘
                          └── F3's fixture unblocks F5 without F2 ───┘
```

- **F1 and F2 are independent and can run in either order** — F1 needs no code, F2 needs no design.
- **F5 depends on F3's *fixture*, not on F2's network.** If F2 blocks, F3's fixture path still lands
  and F5, F6 and F7 still build against synthetic data with the banner showing — the morning brings
  a working page plus one labelled blocker, exactly as T3 did for the backtest.
- **F6 and F7 are parallel** after F5.
- **F9 depends on F3 and F4 only** — it records from the validated payload and joins the router F4
  already mounted. It is **parallel to F5, F6 and F7** and needs none of them: the ledger and the
  scorecard JSON are useful with no UI, and it grades against F3's fixture path. F9 is **purely
  additive** — it changes the scope, acceptance floor or dependencies of no earlier ticket.
- **F8 is last.** Its dependency line is unchanged — it already reads *everything*, and F9 is part
  of everything once it has landed. **F9 does not gate F8:** F8 documents what exists when it runs,
  and if F9 lands after F8 the README and Commands entries for it are a follow-up, not a rewrite.

---

## 14. Loop operating rules

- **Work tickets in order.** Each goes through the full pipeline and ends on a **green, committed,
  pushed** state.
- **Never leave the tree broken to start the next thing.** A forecast page with no trust panel is a
  page; a half-wired trust panel that quotes an invented number is a liability.
- **Blocked ticket → log it, mark BLOCKED, move to the next ticket that does not depend on it.**
  Do not halt the run. Do not retry indefinitely (max 2 genuine attempts per task, per WORKFLOW).
- **Halt only when nothing remains that is not blocked.**
- **Update `.claude/pipeline/STATUS.md` at every phase transition.**
- **Maintain `.claude/active-work/forecast-page/session-log.md`**: what is done, what is in progress,
  what is blocked and what was tried for each blocker.
- **The §3 regression gate runs at the end of every ticket.** `uv run pytest -q` exits 0,
  `uv run ruff check .` is clean, no off-limits path is modified, the existing demo page still works.

**Permitted without asking:** installing into the project-local venv; network fetches to NOAA and
IEM; commits to `feat/forecast-page`; **pushing `feat/forecast-page` to `origin`**; writes to
`STATUS.md`, the session log and plan checkboxes.

**Forbidden:** editing `docs/SPEC.md`, `docs/BRIEF.md` or this file; editing anything in §3's
off-limits table; force-pushing; pushing to `main` or `develop` directly; merging without the
regression gate green; installing into system Python.

**Hard stop and wait (do not work around these):**
1. NOAA returns empty or 404 for **all four models across three consecutive cycles** — that is an
   outage, not a bug, and the fallback has been exhausted.
2. `data/results.json` is absent or fails `backend/contract.py`. There is no default weight vector.
3. **Any impulse to add a probability, a band, or a `±` because the page "looks uncertain without
   one."** That is the decision this document exists to hold. See §6.
4. **Any impulse to change the horizon, the step grid, the weights, or the site in order to make the
   forecast look better.** See §15.

**Stop condition:** all eight tickets green → write the session log, update STATUS.md, push, **stop.**
Do not start stretch goals. Do not refactor working code. Do not "polish". An autonomous agent with
green tests and no stop condition will break something that worked.

---

## 15. Integrity rules — non-negotiable

Carried forward from SPEC §10 and adapted to a forward-looking page.

- **Report what the data says.** If the blend's historical skill at a lead is no better than the
  best single model, the page says so. `improvement_pct` may be zero or negative and must render
  honestly.
- **Never tune to produce a better-looking forecast.** No swapping the horizon, the step grid, the
  weight vector, the skill window or the site because the first output was unimpressive. The whole
  value of this page is that the number is trustworthy.
- **Label stale data.** The run time is always visible; a fallback is always named; a stale cycle
  gets a visible treatment and a stated reason (§5.2).
- **A page that looks confident and is wrong is worse than one that shows a gap.** Gaps render as
  gaps. Missing members are never substituted, never renormalized around, never interpolated across.
- **Any synthetic or fixture data must be unmistakably banner-flagged** — `is_synthetic: true`
  renders a visible banner and a title prefix. A fixture that could be mistaken for a real forecast
  is the worst possible failure of this page.
- **Never interpolate observations** in the history view. Drop missing. Record the offset.
- **Assert on join match counts.** An empty join scores perfectly and is fake.
- **Historical skill is never rendered as a prediction about tomorrow** (§6). This one is the reason
  the page exists in the shape it does.
- **The scorecard reports what happened, including the losses.** Smoothing the record, cherry-picking
  a favourable window, hiding a bad stretch behind a rolling average, or restarting the record after
  one are all **prohibited**. A losing week renders at the same visual weight as a winning one, and
  losing streaks are stated explicitly — they are the refit signal, not an embarrassment. **A past
  record is never overwritten or re-graded to look better: the ledger is append-only** (§12, F9). A
  scorecard that only looks good when it is winning is marketing, and the room will assume it is.

---

## 16. Risk register with named fallbacks

**R1 — the four models do not all publish a 3-hourly grid to f048 for a synoptic run.**
Likely constraints: HRRR's extended runs, and NAM's `awphys` vs `awip` file split.
**Fallback:** F2's probe determines the true intersection; the horizon truncates to it and the page
labels it. **Never renormalize the weights over a subset of models** — that is a different blend and
the skill numbers do not apply to it. A 24 h page that is honest beats a 48 h page that is invented.

**R2 — NOAA is slow, rate-limiting, or the target cycle is not yet published.**
**Fallback:** the §5.2 cycle fallback, up to 3 cycles back, labelled with the run time and the
reason. Beyond that: serve nothing and show the reason. **The page never blocks on NOAA** — it reads
a cached file.

**R3 — `data/results.json` is absent or fails the SPEC §7 contract.**
**Fallback: none, deliberately.** F3 raises with a reason and the API returns 503. There is no
hardcoded default vector and no silent equal-weight substitute. A forecast whose weights came from
nowhere has no track record and cannot honestly be shown.

**R4 — a change leaks onto the demo path and breaks the 16:00 page.**
**Mitigation:** the `forecast/` package boundary, separate frontend files, **exactly two added lines
in `backend/main.py`**, and the §3 regression gate at every ticket end. **Fallback:** revert the
ticket. The demo page outranks the forecast page in v1.

**R5 — scope creep into probabilistic forecasting**, because a forecast without an interval "feels
incomplete".
**Mitigation:** §6.2's banned field names, enforced executably by `forecast/contract.py` and unit
tests, plus F5's and F7's grep-for-banned-strings acceptance items. This is the risk most likely to
arrive as a well-intentioned improvement.

**R6 — a fresh clone cannot build the back-arrow**, because `data/*.parquet` is gitignored.
**Mitigation:** `data/forecast_history.json` is committed, and F8 documents how to regenerate it.

**R7 — the weights are stale by the time anyone looks at the page** (fitted on August, viewed in
December).
**Mitigation:** `weights_age_days` in the payload, a visible note past 45 days, and the caveat in
the trust panel. **Not solved in v1** — refit cadence is §22's open question, and saying so is more
honest than picking an interval with no evidence behind it.

---

## 17. Design and frontend

**Styling: Shyft "Clarity" (v0.2).** Tokens are extracted to
`.claude/features/site-tuned-blend/clarity-design-tokens.md` — **read it before writing any CSS.**
Reuse the vendored `frontend/vendor/clarity-tokens.css` and `vendor/fonts.css` unchanged.

Core: accent `#329af0` (hover `#1c7cd6`); text `#212529`; page bg `#f8f9fa`; surface `#ffffff`;
border `#e9ecef`; muted `#5c636a`. Semantic: success `#37b24d`, warn `#ff922b`, **danger is pink
`#de0f80`**. Fonts: `Sora` (display/stat values — the headline temperature), `Inter` (UI),
**`JetBrains Mono` for every numeric temperature and error value** (tabular numerals).
Dark mode: `<html data-theme="dark">`, localStorage key `internal-portal:theme`. **Mirror
`theme.js`'s inline pre-hydration script** or the presenter sees a light-theme flash.

**Model → colour must match the existing page exactly.** The map is stated once in
`.claude/features/demo-shell/design-target.md` §0; reuse it so HRRR is the same colour on both pages.
Data-viz palette, charts only, never UI chrome: green `#51cf66`, orange `#ff922b`, purple `#a551cf`,
pink `#f0329a`, yellow `#f7be1e`.

**Clarity gaps to design rather than hunt for** — it has no slider tokens (already solved with
literal CSS in T3's design target, §2 — reuse it), **no chart/axis tokens** (T3's §5 — reuse it), and
**no timeline or forecast-strip component at all**. The forward strip is new and F1 must specify it.

**Must render honestly:** the run label (always), the stale treatment, gaps, the 24 h fitted-range
boundary, the synthetic banner, the 503 empty state with its reason, and a zero-or-negative
historical improvement.

---

## 18. Testing

Command surface lives in `CLAUDE.md`'s Commands block; F8 extends it. `uv run pytest -q` must exit 0.

- **`pytest` on pure logic:** cycle selection and the fallback ladder against a frozen clock; the
  §7 banding table at every boundary; the `blend_f == Σ w·m` identity; contract validation, positive
  and negative, **including one test per banned field name (§6.2)**; the ±30-minute history join;
  the gap/renormalization rule; staleness computation.
- **Cache behaviour is tested with a fetch stub that raises** — proving the second run touches no
  network is a test, not a claim.
- **Data guards are assertions in the pipeline**, not tests (SPEC §13), and they use real
  exceptions, never bare `assert`.
- **No live-network test in the suite.** A test that hits NOAA and fails at 04:00 halts a ticket over
  NOAA having a bad minute. The live run is manual and its output is recorded in the ticket.
- **UI: agent-browser**, pinned `0.36.0`. The checks worth having: the page loads → the headline and
  run label render → the back-arrow steps to a past day and shows both what was said and what
  happened → no console errors → screenshot to
  `.claude/active-work/forecast-page/screenshots/`. Droppable per SPEC §11 R5.
- **The regression gate (§3) is part of every ticket's test pass**, not a separate exercise.

---

## 19. Commercial framing — honestly

State this plainly in the README and never oversell it.

**The blending maths is not a moat.** It is kin to MOS, which is decades old, and **NOAA's NBM is
itself a blend** — it is a member of our own blend and a strong baseline precisely because of that.
Anyone with the archive and a weekend can grid-search a simplex. README §9 already says this to the
room; the forecast page must not quietly un-say it.

**What may actually be defensible:**

1. **Per-site tuning at customer sites NOAA will never tune.** NBM is tuned for a national grid.
   A grower's field, a substation, a rail siding, a rooftop sensor — NOAA has no station there and
   never will. Reweighting against *the customer's own sensor* is a thing only the customer's data
   makes possible.
2. **Explainability.** A number **plus its track record at that exact location** is a different
   product from a number. "This blend's typical miss here at 6 hours was 1.9 °F over the last 30
   days, and here are those 30 days" is a claim a buyer can audit. Most forecast APIs return a
   number and nothing else.
3. **The out-of-sample verification harness itself.** The 20/10 chronological split, the paired
   comparison, the one-hot identity test, the ±30-minute join with its match assert, the coverage
   floor, the contract validators. **The discipline is the asset** — it is what makes claim (2)
   believable, and it is the part that is genuinely hard to reproduce in a weekend.

**A colleague — a meteorologist who codes — is independently building a forecast-grading tool.**
**Grading is the natural input layer to this**: grading tells you which model was right where and
when; site-tuned blending is what you *do* with that. The two compose cleanly and there is an
obvious version of this where his grader feeds this blender. **The user has chosen to build
independently for now.** That is a recorded decision, not an oversight, and it does not need
revisiting inside this build.

**What this page is not:** a product, a validated result, or a claim of general skill. It is a
feasibility demo at **one site** over **30 days**, forecasting **one variable**, with weights fitted
in **one month**. Every one of those is a limit, and the page names them.

---

## 20. What must exist when the run ends

1. `.claude/pipeline/STATUS.md` — one line: what is done, what is next, what is blocked.
2. `.claude/active-work/forecast-page/session-log.md` — done / in progress / blocked, with what was
   tried for each blocker.
3. **One command that produces a forecast and one that serves it**, documented at the top of the
   README's new section.
4. A screenshot of the working forecast page.
5. Green tests, clean tree, **the existing demo page still working**, all work committed to
   `feat/forecast-page` and **pushed to `origin`**.

---

## 21. Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | **Confidence = historical skill only (Q12a)** | A band drawn from past MAE claims past skill transfers to *this* forecast. It does not, and it fails hardest during the extreme events people care about — precisely when the customer is looking. NBM already publishes calibrated percentiles; a hand-rolled interval fitted on ~30 independent days would be worse than the free thing. |
| 2 | **Framed as history, in past tense, always** | The difference between "this blend's typical miss here was 1.9 °F" and "this forecast is accurate to ±1.9 °F" is the difference between an auditable claim and a false one. Tense is the guard, so it is written into the acceptance floors. |
| 3 | **Explicitly not probabilistic; banned field names enforced by the validator** | Scope creep into intervals will arrive as a well-intentioned improvement. A rule that lives only in prose gets rediscussed; a rule that fails a unit test does not. |
| 4 | **Forward, with a back-arrow into scored history (Q13)** | The forward number is the product; the back-arrow is the evidence. "Here is what we said, here is what happened" is the only cheap way to make a trust claim checkable, and the pipeline already scored those days. |
| 5 | **Audience is the end customer, doubling as an API showcase (Q14)** | One number plus "how much should I trust it". A forecaster's console would need model soup, synoptic context and ensemble plumes — a different product, and not what is being sold. |
| 6 | **Missing/late cycle → previous cycle, labelled with run time (Q16)** | Silently serving a stale forecast as current is the forward twin of SPEC §4's fake-green empty join and of spike F1's folkweather clamp — confident, plausible, wrong, undetectable from outside. The run label is unconditional so it is never a warning badge nobody has learned to read. |
| 7 | **48 h forward, 30 days back (Q17)** | 48 h is where a deterministic single-site temperature forecast is still worth something and where all four models are plausibly available. 30 days back is exactly what the backtest scored — no new fetching, no new claims. |
| 8 | **3-hourly forward step, probed not assumed** | Hourly is not uniformly available across HRRR/GFS/NAM/NBM out to 48 h. Probing first is what made T2 land in one pass; assuming a grid and discovering it at integration time is what T2 avoided. |
| 9 | **Weights come from `data/results.json`, never refitted here** | The whole trust story rests on weights fitted out of sample on days 1–20 and verified on 21–30. Refitting inside the forecast page would silently break that provenance and there would be no split to point at. |
| 10 | **Nearest fitted lead, banded; >24 h flagged extrapolated** | Interpolating a weight vector between 12 h and 24 h invents a blend no one measured. Banding is crude, visible and honest, and the flag makes the unverified region unmissable. |
| 11 | **Gaps render as gaps; never renormalize over a subset** | A three-model renormalization is a different blend than the fitted one, so its skill numbers do not apply. §15: a page that looks confident and is wrong is worse than one that shows a gap. |
| 12 | **All new code in `forecast/` + new frontend files + exactly two lines in `main.py`** | The 16:00 demo depends on the existing path. A crisp package boundary makes "did this ticket touch the demo path?" a `git diff --stat` question rather than a judgement call. |
| 13 | **Live fetch is an offline CLI; the page serves from cache** | SPEC §6's rule that the demo path never fetches live exists because a demo that blocks on NOAA is a demo that fails at 16:00. A forward page has the same exposure and gets the same answer. |
| 14 | **`data/forecast.json` gitignored; `data/forecast_history.json` committed** | A forecast goes stale by definition — committing one puts a stale forecast in the repo, which is §5.2's failure with a version number. History does not go stale, and the parquets that build it are gitignored, so it must be committed or the back-arrow dies on a fresh clone. |
| 15 | **`/design` is ticket 1, in either of two forms** | SPEC §12's precedent: a design pass before T3 is why the frontend landed in one pass. The `design` skill's multi-artboard canvas is richer; T3's written `design-target.md` is cheaper and proven. The implementer picks on the clock — the *output* is required, not the tool. |
| 16 | **Model spread allowed as disagreement, banned as an error bar** | Spread is a fact about the models. Rendered as a band around the blend it becomes a probability claim, which is decision 1 arriving through the back door. |
| 17 | **F5 depends on F3's fixture, not F2's network** | T3's insurance, repeated: if the new live-fetch capability blocks, the morning still brings a working page with an unmistakable synthetic banner and one labelled blocker. |
| 18 | **Push permitted; `feat/forecast-page` off `develop`** | A remote exists now (`github.com/sgupta604/bhar`), unlike the overnight backtest run. Batching to `main` via `develop` keeps `main` demo-clean. |
| 19 | **Commercial framing stated honestly in the README** | README §9 already concedes "isn't this just MOS?" to the room. A forecast page that quietly walks that back would undo the credibility the backtest bought. |
| 20 | **Build independently of the colleague's grading tool for now** | The user's explicit call. Grading and blending compose, and this is recorded so a future session finds a decision rather than an oversight. |

---

## 22. Open questions — deferred to v2, deliberately not answered here

These are **not** blockers and must **not** be resolved by an implementing agent inventing an answer.
Log them, build v1 as specified, and leave them for the user.

1. **Refit cadence — the leading question.** How often should weights be refitted, on what window,
   and does a rolling 30-day fit beat a fixed seasonal one? Weights fitted on August may not hold in
   December (§7.1). v1 applies fixed weights and says so.
2. **Hourly forward steps** instead of 3-hourly, if the archive supports it uniformly.
3. **A 3-hourly past curve** in the back-arrow, which requires refetching the archive at leads the
   backtest never fetched.
4. **Scheduling.** v1 has no cron and no background refresh; a human or a future scheduler runs
   `forecast.refresh`.
5. **Multiple sites**, which is the only way to learn whether per-site weights generalise or whether
   KOMA is a special case.
6. **Whether to integrate the colleague's forecast-grading tool as the input layer** (§19).
7. **Bias correction / MOS on top of the blend**, with the increment reported separately — already
   named in SPEC §5 and README §10 as v2 work.
