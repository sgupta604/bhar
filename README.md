# Bhar — Site-Tuned Model Blend

Bhar backtests four NOAA forecast models against observed temperature at a single
airport, then searches for the weighted blend of those models that would have had the
lowest error *at that site*. The demo page shows the search, the winner, and the
evidence that the numbers are real.

**This is a feasibility demo at one site over 30 days. It is not a result.** One
station (Omaha Eppley, KOMA), one variable (2 m temperature), one month, three lead
times. Nothing here generalises to another site, another season, or another variable,
and nothing in this README should be read as claiming it does.

---

## 1. What this is

The hypothesis under test: *does reweighting several public forecast models against a
site's own observation history beat simply picking the single best model there?* The
maths is old — this is ensemble weighting, and it is close kin to MOS. The part worth
testing is whether it still helps when the weights are fitted per site, per lead time,
against the customer's own sensor, and whether the size of the help is worth selling.

The answer this repo produces may be "no". That is a legitimate outcome and the page
renders it plainly rather than hiding it. See §5.

**The short version of what was found, stated up front so nobody has to dig for it.** A
blend did beat the best single model at all three lead times, by 9.02% / 13.82% / 16.51%
out-of-sample. But **most of that gain comes from excluding GFS, not from the fitted
weights**: an un-fitted blend that simply drops GFS and averages the other three models
scores as well or better at 12 h and 24 h. The honest headline is closer to *"one of these
four models is bad at this site, and not using it helps"* than to *"site-tuned weighting
works"*. §5.1 gives the numbers behind that, and it is the part of this README to read
first.

---

## 2. Run the demo

**Easiest path:** `./demo.sh` — picks free ports itself and opens the right URL. Or explicitly:

```
BHAR_BACKEND_PORT=8011 BHAR_FRONTEND_PORT=5184 ./run.sh
```

Then **open the `Frontend:` URL that the script prints.** Do not hand-type a frontend
URL, and do not use bare `./run.sh` on this machine. Both of those fail, for two
separate and unrelated reasons:

**Why the ports are overridden.** Port 8000 on this machine is held by a VS Code helper
process (`Code Helper`, PID 1163 at the time of writing). That process also answers
`/health` with a byte-identical `{"status":"ok"}`, so a health check against `:8000`
passes while this app is not running at all — it already fooled one smoke check during
T1. `run.sh` lines 14-25 preflight both ports and refuse to start on a busy one, so
bare `./run.sh` exits with an error here rather than starting anything.

**Why you must open the printed URL.** `run.sh` lines 65-71 print the frontend URL with
an `?api=http://localhost:8011` query string appended, and it does that *only* when the
backend port is not 8000. The page defaults its API base to `:8000`. A hand-typed
`http://localhost:5184/` therefore renders the full page chrome with no data in it,
which looks like a bug in the app and is not.

**Identity check.** To confirm you are talking to *this* backend and not the squatter,
open `http://localhost:8011/openapi.json` and look for the title
`"Bhar - Site-Tuned Model Blend"` — note the plain ASCII hyphen, which is what
`backend/main.py` actually sets and therefore what to match on. Never check `/health` —
that is precisely the
endpoint the squatter forges.

**Stopping.** Ctrl-C stops both processes cleanly. `run.sh` sweeps both ports before it
calls `wait`, because a `uv run` child can otherwise survive the signal, keep the port,
and make the next start fail the preflight.

**Screenshot.** The page rendered against the **real backtest** — the numbers in §5, with
no synthetic banner — is at
`.claude/active-work/site-tuned-blend/screenshots/t5-real-results.png`.

The other captures in that directory (`demo-shell.png`, `demo-shell-full.png`,
`demo-shell-24h-negative.png`, `test-agent-24h.png`) predate the real run and were
rendered against the **synthetic fixture**. They carry the synthetic banner and are
labelled as fixture renders on the page itself; `demo-shell-24h-negative.png` in
particular shows the fixture's fabricated negative-improvement case, which is a UI state
check and **not** a result of this study.

The same directory also holds `real-6h.png`, `real-24h.png`, and `real-full.png` —
additional real-backtest captures at each lead time, taken alongside `t5-real-results.png`.

---

## 3. What you are looking at

The page has five parts, plus a banner.

**The lead-time toggle** (6h | 12h | 24h) at the top right. Everything below it is
recomputed per lead time. Weights are fitted independently at each lead, so the winner
at 6 h and the winner at 24 h are separate answers to separate questions.

**The leaderboard.** One row per candidate blend: rank, a weight label, a stacked bar
showing the weight split across models, and the error in degrees F. The winning row is
highlighted. Pure single models appear here too — they are the corners of the weight
space and are ranked for free (§4).

**"Try your own blend".** A live slider panel. Move the weights and the displayed error
updates immediately from the precomputed grid. This exists so a sceptic in the room can
drive it themselves rather than trusting a static chart.

**The error-vs-weight chart** with a two-model pair selector. See below for what it is
and is not.

**The honesty panel** (join diagnostics, model exclusions, data source, and the
improvement line). It is not decoration. SPEC §10 requires that the join match rate,
the mean absolute join offset, any excluded model with its coverage percentage, and the
name of the data source are all *displayed*, not buried in a log. The panel renders
those live from the same document the leaderboard uses, so it cannot drift out of sync
with the numbers above it. Read it there rather than trusting this README's copy.

**The model include/exclude bar** shows which models are in the study for the
current view.

### The chart is a two-model slice, not the whole search

With four models the weight space is a 3-simplex: three free dimensions, no single
x-axis to plot error against. The chart therefore holds two of the four models at zero
weight and sweeps x from 0% to 100% weight on model A, with model B taking the
remainder. Both ends of the curve are genuinely pure single models. The pair selector
picks which two.

**The leaderboard above it searches the full four-model space, not the slice.** The
chart is there to show the *shape* of the trade-off — whether the error curve has a
real interior minimum or is monotone toward one corner — and nothing more. If the
chart's best point disagrees with the leaderboard's winner, the leaderboard is right;
it searched more.

### The synthetic banner

If the page is displaying the labelled fixture instead of a real backtest, it says so
in large type across the top, draws an inset frame around the whole shell, and prefixes
the browser tab title with `[SYNTHETIC]`. All three signals come from the single
boolean `meta.is_synthetic`. A fixture that could be mistaken for real data is the worst
failure this project can produce (SPEC §10), so `is_synthetic: true` is unmissable by
design.

### There is no refetch button

Deliberately. A live-fetch HTTP route that is never pressed on the demo path is dead
code that can only fail in front of an audience. The refresh path is the offline CLI in
§7. There is no refetch endpoint and no refetch button — do not go looking for one.

---

## 4. What the numbers mean

**Three metrics, all in degrees F, all per lead time.** MAE is the headline. RMSE is
shown beside it because it punishes large misses harder than MAE does, and bias is shown
because a systematic offset is a different failure from noise and is fixable in a way
noise is not (see caveat C4). Kelvin exists only inside the GRIB decoder; every number
that crosses a module boundary is already in °F.

**Reading a blend row.** A weight label like `70 / 30` means 70% of one model and 30%
of another, in the order the label names them. The search grid step is 0.1, so weights
move in tenths. Over four models that is **286 weight vectors**, enumerated
exhaustively — this is a small enough space that there is no optimiser and no local
minimum to worry about; every vector is evaluated. The four pure models are the one-hot
corners of that same grid, so they are scored by exactly the same code path as every
blend and appear in the same ranking.

**In-sample and out-of-sample are both shown.** The headline number is out-of-sample.
The in-sample number sits beside it, labelled. The gap between them is a displayed
result rather than a hidden detail: it is the honest measure of how much of the fit was
the site and how much was the fitting.

### The winner rule, and why it is deliberately unfair to the blend

Two different selections happen, on purpose, in two different directions:

- The **winner** is the blend with the lowest **in-sample** MAE — chosen on the first
  20 days, without seeing the last 10 — and it is then **reported out-of-sample**.
- The **`best_single_model` baseline** is the corner with the lowest **out-of-sample**
  MAE — chosen with hindsight, on the very data it is scored on.

So the baseline gets to cheat and the blend does not. That is the conservative
direction, and it is the only reason a positive `improvement_pct_vs_best_single` means
anything at all: it says the blend beat a baseline that was handed the answer key.

**A consequence worth stating outright: the winner is not necessarily `blends[0]`.**
The `blends` array is sorted by out-of-sample MAE, but the winner was picked in-sample.
Those are different orderings and they routinely disagree. **On this run the winner's
out-of-sample rank was 5th, 23rd and 5th of 286** at 6 h / 12 h / 24 h — so at every lead
there were blends that scored better out-of-sample than the one the training window
selected, and at 12 h there were twenty-two of them. Never describe the winner as "the
best blend"; it is the blend that a forecaster restricted to the training window would
have chosen, which is the only kind of blend anyone could actually have used in advance.

**`improvement_pct_vs_best_single` may be zero or negative.** No part of the pipeline
requires it to be positive — the results contract validator explicitly refuses to check
its sign — and the page renders a zero or negative value honestly, without the winner
styling, stating in words that there was no improvement.

---

## 5. The result

Read this section knowing that a negative change is a possible and acceptable outcome.
The best single model at a given lead time may simply be better than every blend that
the training window would have selected, and NBM in particular is itself a blend of
other models and is a strong baseline. **If no blend beats the best single model at a
lead time, that is the reported result. It is not a failure of the run**, and it is not
something this README will soften.

### Per-model out-of-sample error

| Lead | Model | MAE (°F) | RMSE (°F) | Bias (°F) |
|------|-------|----------|-----------|-----------|
| 6 h  | HRRR  | 2.1075 | 2.6482 | -0.0631 |
| 6 h  | GFS   | 5.1549 | 6.3880 | +2.9485 |
| 6 h  | NAM   | 2.5405 | 3.1160 | +0.9489 |
| 6 h  | NBM   | 2.2835 | 2.7651 | +1.1535 |
| 12 h | HRRR  | 2.2814 | 2.7778 | +0.0769 |
| 12 h | GFS   | 5.6780 | 6.8999 | +3.4184 |
| 12 h | NAM   | 2.3003 | 2.8449 | +1.0869 |
| 12 h | NBM   | 2.4725 | 3.0017 | +1.4010 |
| 24 h | HRRR  | 2.5231 | 3.1852 | +0.3304 |
| 24 h | GFS   | 5.9967 | 7.3618 | +3.8132 |
| 24 h | NAM   | 2.6524 | 3.4212 | +1.4344 |
| 24 h | NBM   | 2.5935 | 3.0889 | +1.5490 |

**HRRR is the best single model at all three lead times — not NBM.** SPEC §1 anticipated
that NBM might win outright, since NBM is itself a multi-model blend and was the obvious
favourite. At this site over this month it did not: HRRR beat it at 6 h and 24 h, and NAM
beat it at 12 h. This is reported because it is what the data says, not because it was
expected.

**GFS is an outlier by a wide margin** — 2.03× the MAE of the next worst model at 6 h,
2.30× at 12 h and 2.26× at 24 h, with a warm bias climbing from +2.95 °F at 6 h to
+3.81 °F at 24 h. See §5.1.

### The winning vector at each lead, against the hindsight baseline

| Lead | Winning weight vector | Winner OOS MAE (°F) | Best single model | Its OOS MAE (°F) | Change vs best single (%) | Winner's OOS rank among blends |
|------|-----------------------|---------------------|-------------------|------------------|---------------------------|--------------------------------|
| 6 h  | HRRR 50 / NAM 10 / NBM 40 | 1.9173 | HRRR | 2.1075 | +9.02% | 5 of 286 |
| 12 h | HRRR 60 / NAM 10 / NBM 30 | 1.9661 | HRRR | 2.2814 | +13.82% | 23 of 286 |
| 24 h | HRRR 50 / NAM 10 / NBM 40 | 2.1066 | HRRR | 2.5231 | +16.51% | 5 of 286 |

In words, so the table is not the only reading of it: the winning vector at 6 h was
HRRR 0.5 / GFS 0.0 / NAM 0.1 / NBM 0.4; its out-of-sample MAE was 1.9173 °F against the
best single model's 2.1075 °F, a change of +9.02%. The same three quantities at 12 h were
HRRR 0.6 / GFS 0.0 / NAM 0.1 / NBM 0.3, 1.9661 °F and +13.82%, and at 24 h
HRRR 0.5 / GFS 0.0 / NAM 0.1 / NBM 0.4, 2.1066 °F and +16.51%. The "change" column is
signed, and a negative entry would mean the blend selected on the training window did
worse out-of-sample than the hindsight-selected single model at that lead. On this run
all three are positive.

**GFS receives weight 0.0 in all three winning vectors.** That is the single most
important fact in this section, and §5.1 is about what it means.

These numbers were produced at **2026-09-04T12:53:01Z** (`meta.generated_at`), from
`data/results.json` with `is_synthetic: false`.

Whichever way the signs fall, the honesty panel on the page carries the same figures
live from the same file, so the page and this README cannot disagree without one of them
being stale.

---

### 5.1 Most of the gain is from dropping GFS, not from the fitted weights

This is the section to read before quoting any number above.

The obvious hostile question is *"did you just discover that GFS is bad at this site?"*
**Largely, yes.** That was tested directly rather than left to argument. Take an
**un-fitted** blend — no optimisation, no training window, no search — that simply drops
GFS and averages the other three models roughly equally (HRRR 0.4 / NAM 0.3 / NBM 0.3,
the nearest point on the 0.1 grid to equal thirds). Score it out-of-sample:

| Lead | Un-fitted "drop GFS, average the rest" | Fitted winner | Best single model (HRRR) |
|------|----------------------------------------|---------------|--------------------------|
| 6 h  | **1.9865** (+5.74% vs HRRR) | 1.9173 (+9.02%) | 2.1075 |
| 12 h | **1.8879** (+17.25% vs HRRR) | 1.9661 (+13.82%) | 2.2814 |
| 24 h | **2.0886** (+17.22% vs HRRR) | 2.1066 (+16.51%) | 2.5231 |

Read that table honestly and it says three things:

1. **The un-fitted blend captures most of the improvement at every lead**, and at **12 h
   and 24 h it actually beats the fitted winner** out-of-sample. At 24 h its 2.0886 °F is
   the **lowest out-of-sample MAE of all 286 vectors** — the un-fitted blend *is* the
   floor. Only at 6 h does fitting buy anything real (1.9173 against 1.9865).
2. Therefore **the headline improvements above should not be attributed to the precise
   fitted tenths.** The weight search is not what produced most of the gain. Excluding a
   badly-behaved model and averaging the rest produced most of the gain, and that requires
   no fitting, no training window, and no per-site service.
3. The narrower claim that survives this — *does per-site reweighting add value **on top
   of** a naive drop-the-worst-model average?* — is answered here as: **a little at 6 h,
   and nothing measurable at 12 h or 24 h.** That is a much smaller claim than "+16.51%",
   and it is the one the data supports.

None of this makes the headline numbers wrong. They are what the specified procedure
produced, computed exactly as SPEC §7 defines them. But a reader who takes "+16.51% from
site-tuned blending" away from this page has taken away more than the experiment showed.

**Why GFS is bad here, and why it is not a bug.** GFS's error at this site is a **diurnal
amplitude error**: at the 24 h lead its mean error by valid hour is **+3.77 °F at 00z,
−1.58 °F at 06z, −2.20 °F at 12z, +5.14 °F at 18z**. It runs warm in the local
afternoon and evening and cold overnight — it over-amplifies the daily temperature swing.
This was checked against the alternative explanation, a decode fault, and rejected: spike
F11 confirmed GFS decodes correctly at the acceptance anchor (71.65 °F, a physically sane
value), and GFS's full range over the window is 58.4-108.5 °F against observed 59-98 °F.
The values are real; they are a coarse 0.25° grid cell 13 km from the station behaving
like a coarse grid cell 13 km from the station (C4).

**GFS was included in the study and simply earned zero weight.** It was not excluded, not
dropped for coverage, and not filtered out. Its coverage was 100.00% like every other
model, it was scored at every lead, and its numbers are in the table above. Receiving
weight 0.0 from the search is a **result**, not an exclusion — see C5 for the exclusion
rule, which did not fire for any model.

### 5.2 The improvement is a broad plateau, not one lucky cell

Two of the three improvements exceeded SPEC §10's ">10%, investigate rather than
celebrate" tripwire, so they were investigated before shipping. The most useful check:
**47, 116 and 105 of the 286 blends beat the best single model** at 6 h, 12 h and 24 h
respectively — 16%, 41% and 37% of the whole weight space. A fluke would be one cell, or
a handful clustered around one. A plateau that wide means the result does not depend on
having found a particular vector, which is both reassuring about the finding and further
evidence for §5.1: if a third of the space beats HRRR, the specific winner is not doing
much work.

Three other checks were run and are recorded in
`.claude/active-work/site-tuned-blend/session-log.md`: a hand re-derivation of all twelve
model × lead metric triples using a brute-force join that does not import `score/` (all
matched to 4 dp), a confirmation that the in-sample winner lands near the out-of-sample
optimum at each lead, and the un-fitted comparison of §5.1. **Nothing about the experiment
was changed as a result of any of them** — see §9.

---

## 6. How it was built

Five stages, each writing a file the next one reads. Nothing is held in memory across
stages, which is what makes any single stage re-runnable and inspectable.

1. **Fetch forecasts.** For each model run, download that run's GRIB `.idx` index,
   find the line for the 2 m temperature message, and issue an HTTP byte-range GET for
   exactly that message — a few kilobytes instead of a multi-hundred-megabyte file.
   Decode, take the nearest grid cell to the station, convert to °F. Result:
   `data/forecasts.parquet` with columns `model, init_time, lead_h, valid_time, temp_f`.
2. **Fetch observations.** IEM ASOS station `OMA`, hourly, into `data/obs.parquet` with
   columns `valid_time, temp_f`.
3. **Join and score.** Match each forecast to an observation (see below), compute
   per-model MAE / RMSE / bias, then evaluate all 286 weight vectors on the 0.1 simplex
   grid, per lead time, with a chronological train/test split. Result:
   `data/results.json`.
4. **Serve.** FastAPI reads that file from disk on `GET /api/results`, re-validates it
   against the locked SPEC §7 contract on every request, and returns 503 if validation
   fails rather than serving a document it cannot vouch for.
5. **Render.** The static frontend fetches that one endpoint and draws the page.

### Site and variable

Omaha Eppley Airfield, **KOMA**, 41.3032, -95.8941; IEM station `OMA`; station
elevation 295.7 m. Variable: 2 m temperature, reported in degrees F
(`F = (K - 273.15) * 9/5 + 32`, applied inside the decoder and nowhere else). Models:
**HRRR, GFS, NAM, NBM**. Initialisations: 00z / 06z / 12z / 18z. Lead times: 6 h, 12 h,
24 h. Window: 30 days. **Every timestamp in this system is UTC**, with no local time
anywhere including the site's own.

The window actually scored ran from **2026-08-04T12:00:00Z** to **2026-09-04T00:00:00Z**
(30 days). This run's
initialisation bounds are also recorded in the committed `data/coverage.json` under
`window.start_init` / `window.end_init`.

### The demo path never touches the network

The backend serves precomputed results from a file on disk. The frontend vendors its
own stylesheet (Clarity design tokens) and all three font faces (Inter, Sora, JetBrains
Mono) as local WOFF2 files. Rendering the page makes **zero external requests**, so the
demo cannot be broken by a conference wifi captive portal or by NOAA having a bad
minute.

### The ±30 minute join, and why it has to exist

This is the highest-risk correctness issue in the project, so it gets stated in full.

METAR observations are not reported on the hour. `OMA` reports at roughly `:52`. A model
valid time of `18:00Z` therefore has **no observation at `18:00Z`** — an exact-timestamp
join between forecasts and observations matches **zero rows**. And a zero-row join does
not error; it scores *perfectly*, because the mean of an empty set of errors is
vacuously excellent. A silent, confident, entirely fake result is the failure mode here.

The join is therefore: for each model valid time, take the **nearest valid non-`M`
observation within ±30 minutes**, record the **signed offset in minutes as a column on
every matched row**, and **raise hard** if the matched row count falls below 80% of
expected. Observations are **never interpolated** — a missing observation is dropped,
never invented, because an invented observation is indistinguishable from a real one
downstream.

The resulting match rate was **100.00%** at every lead time — 480 of 480 forecast rows
matched — with a mean absolute offset of **7.925 minutes** at 6 h and **7.9167 minutes**
at 12 h and 24 h. 120 of 120 valid times survived pairing, with none dropped. Both
figures are displayed live in the honesty panel. That the mean offset is ~7.9 minutes
rather than 0.0 is itself the evidence the join is doing real work: it is the `OMA` `:52`
reporting pattern showing up as data.

**Comparison is paired.** A valid time enters scoring only if *every* included model has
a forecast for it. Otherwise a model with patchier coverage would be scored on an easier
subset of hours than its competitors, and the leaderboard would be measuring coverage
rather than skill.

---

## 7. Reproduce it from a fresh clone

**Read this before step 3.** `data/coverage.json`, `data/results.json` and
`data/results.synthetic.json` **are committed** to the repository. The parquet files are
**not**: `.gitignore` lines 21-24 exclude `data/raw/`, `data/*.parquet` and `*.grib2`,
because they are large and regenerable. A fresh clone therefore has *no* parquet files,
and running the scoring step before the backfill will fail with a confusing
missing-file error. Run the backfill first, or just run the demo (§2) against the
committed results and skip steps 3 and 4 entirely.

**Also read this before step 3.** The study window is a function of the wall clock.
`fetch/window.py` lines 87-93 — `default_window()` — calls
`datetime.now(timezone.utc)` when no explicit `now_utc` is passed. Re-running the
backfill tomorrow fetches and scores **a different 30 days**, and **you will not
reproduce the exact numbers in §5**. That is intended behaviour and not a bug: the tool
is meant to answer "what does the last 30 days say", not "what did one frozen month
say". The bounds of *this* run are pinned in the committed `data/coverage.json`
(`window.start_init` / `window.end_init`) and in `meta.window` of `data/results.json`.

**1. Provision.** Python 3.12, pinned via `uv`, with the virtualenv in-repo at `.venv/`.
No separate install step is needed: `uv run` syncs the environment from the pinned
`pyproject.toml` and `uv.lock` on first use.

**2. Verify the checkout.**

```
uv run pytest -q
uv run ruff check .
```

Both must exit 0. There is **no build step and no type checker**, by design (SPEC §13):
the Python runs from source and the frontend is static files with no bundler. Neither is
missing — neither exists, deliberately. There is also no live-network integration test,
so the suite cannot fail because NOAA had a bad minute.

**3. Fetch the data — one command.**

```
uv run python -m fetch.backfill
```

This is the **single data command**. It fetches the forecasts *and* runs the observation
step (`fetch/backfill.py` lines 669-671, `run_obs_step`), then writes
`data/coverage.json`. One command is less to get wrong at 04:00 than two.
`uv run python -m fetch.obs` exists as an observations-only escape hatch if you need to
refresh just the ASOS side, and `--forecasts-only` is the flag that suppresses the
observation step.

**4. Score.**

```
uv run python -m score.run
```

Writes `data/results.json`.

**5. Run the demo.** The command in §2.

**Optional: check the UI.** `scripts/smoke_ui.sh` drives the running page with
agent-browser and captures a screenshot into
`.claude/active-work/site-tuned-blend/screenshots/`.

---

## 8. Known caveats

These are the things a hostile question would find. They are listed here rather than
softened, and several of them are the reason numbers in §5 are smaller than they could
have been made to look.

**C1 — The 20/10 chronological split, and why it is not optional.**
Weights are fitted on days 1-20 and evaluated on days 21-30. Fitting and reporting on
the same 30 days would guarantee an improvement *by arithmetic alone*: with 286 vectors
searched and only one metric, the best in-sample blend is at worst equal to the best
in-sample single model, always, on any data whatsoever. That number would carry no
information. "Fit on the first 20 days, still ahead on the last 10" is the only version
of this claim that survives a hostile question, so the headline is the out-of-sample
number and the in-sample number is displayed beside it, labelled.

The winner's in-sample MAE against its out-of-sample MAE was **1.7793 / 1.9173 °F** at
6 h, **1.9730 / 1.9661 °F** at 12 h and **2.0141 / 2.1066 °F** at 24 h. The size of that
gap is the cost of the fitting, and it is a result in its own right. At 6 h and 24 h the
fit degraded by about 0.09-0.14 °F when moved onto unseen days; at 12 h it did not
degrade at all, which is a 40-sample coincidence and should not be read as the fit
generalising *better* than it was measured to.

**C2 — 120 samples are not 120 independent observations.**
Four initialisations a day over 30 days gives roughly 120 forecast-observation pairs per
lead time, but samples within a single day share a weather regime: if a stationary front
sat over eastern Nebraska on the 14th, all four of that day's samples are wrong in
correlated ways. The effective sample size is closer to **30 independent-ish days** than
to 120. **Every confidence claim in this README should be read against 30, not 120.**
This is the caveat most likely to change how you weigh the result, which is why it is
this high in the list.

The realised counts were **80 train / 40 test** at 6 h, **80 / 40** at 12 h and
**80 / 40** at 24 h — identical at all three leads, as expected from a fully-paired
120-row series split chronologically. The
split is chronological, with the boundary at the first paired valid time plus 20 days —
not a random shuffle, because a random split would leak tomorrow's regime into today's
training set.

**C3 — No bias correction and no MOS were applied, and that is a choice.**
Two reasons, both required by SPEC §5. First, it **confounds the hypothesis**: with a
per-model bias correction in the pipeline you could not tell whether an improvement came
from blending or from the correction, and blending is the thing under test. Second, it
hands the room its own best objection — "isn't this just MOS?" — with no clean answer.
Leaving it out keeps the question answerable. **v2 adds bias correction and reports the
increment separately**, which is the only way to learn what each part contributes.

**C4 — Nearest grid cell, no interpolation, and an unmeasured elevation gap.**

- Station elevation is **295.7 m**.
- Each model's forecast is taken from its **nearest grid cell** to the station, with
  **no horizontal interpolation and no elevation or lapse-rate correction**.
- Because the four models are on four different grids, each one's nearest cell sits at a
  different location, and therefore at a different model terrain height. Distances from
  KOMA: **HRRR 0.012°, NBM 0.009°, NAM 0.040°, GFS 0.119°** — GFS is the outlier at
  roughly 13 km away, which is a straightforward consequence of its coarser grid. The
  cell centres actually used, for the record: HRRR (41.2914, -95.8923), GFS (41.2500,
  -96.0000), NAM (41.2864, -95.9305), NBM (41.3034, -95.9029).
- The mechanism to understand: a terrain-height mismatch between a model's cell and the
  real station shows up as a **systematic offset in degrees F**, and a systematic offset
  is exactly what the **`bias` column** measures. That column is on the page for every
  model at every lead. Reading it tells you more than a single terrain number would,
  because it captures the net effect of the mismatch rather than one input to it.
- **The honest gap: the grid-cell terrain height was never fetched.** The fetch path
  requests only the `:TMP:2 m above ground:` message — it never requests `:HGT:surface:`
  or any orography field. **No terrain-height delta was measured, and none is stated
  here.** Quantifying it is one `:HGT:surface:` fetch per model, and it is named as v2
  work in §10. A named unmeasured gap is worth more than a plausible invented number.
- Why this caveat lives in the README rather than in the data: `results.json` cannot
  carry it. `backend/contract.py::validate_results()` locks the exact key set of `meta`
  and rejects any document with an extra field, so there is nowhere in the served
  document to put it. This file is its only home.

**C5 — Coverage, and the exclusion rule that did not fire.**

Coverage was **100.00% for all four models** on this run. Every one of the 360 attempted
fetches per model succeeded, 120 of 120 per model-lead, with `below_floor: false`
everywhere — the full table is in the committed `data/coverage.json`. **Nothing was
excluded from this study.**

Separately, and independently of that outcome: a **90% coverage floor** exists in the
pipeline. A model falling below it is dropped from the study entirely and is **named on
the page together with its coverage percentage**, so a missing model is visible rather
than quietly absent. The floor exists because three models on 120 well-paired samples is
a better experiment than four models on 40 — a patchy model would otherwise shrink the
paired intersection for everyone (see the paired-comparison rule in §6). The exclusion
path is unit-tested. This window simply never triggered it.

As recorded in the results document: `models_included` is
**`["HRRR", "GFS", "NAM", "NBM"]`** and `models_excluded` is **`[]`** — empty. All four
models are in the study. (GFS earning zero weight in the winning blends, §5.1, is a
scoring result and has nothing to do with this list.)

**C6 — The data source actually used.**

Forecasts come from **NOAA's AWS S3 GRIB2 archive**, retrieved by parsing each run's
`.idx` file and issuing an HTTP byte-range GET for exactly the one message needed.
Observations come from **IEM ASOS station `OMA`**. Those are the only two networks
this project talked to.

The document records `source: "noaa_s3_grib"` and `is_synthetic: false`.

**The Open-Meteo fallback did not fire.** SPEC §11 R1 is retired. This is stated
explicitly rather than left to inference, because SPEC §10 requires the page to name the
source that produced its numbers, and "no fallback fired" is part of that answer.

Two traps in this path are worth recording, because both were hit for real:

- **The `.idx` is parsed every time and a message index is never hardcoded.** NBM's
  index for the 2 m temperature message *moves with lead time* — 187 at f006, 192 at
  f012, 195 at f024. Any cached or constant index silently fetches the wrong variable.
- **The variable match is anchored with a leading colon**: `":TMP:2 m above ground:"`,
  not `"TMP:2 m above ground"`. The unanchored form is a substring of
  `APTMP:2 m above ground` — apparent temperature — which is message 1 in NBM. **During
  validation the unanchored match silently returned apparent temperature**, which looks
  entirely reasonable and is a different variable. Two guards now stand behind the
  anchor: any index line containing `ens std dev` is rejected, and the decoded short
  name is asserted to be `t2m` and never `aptmp`.

**C7 — Reproducibility is bounded by the wall clock.**
The 30-day window is derived from the current time at fetch, so a later re-run scores a
different month and produces different numbers. See §7 for the mechanism and for where
this run's exact bounds are pinned.

---

## 9. "How many variations did you try?"

This is the first question a sceptical room asks, and it deserves its own section.

**The answer is one.** One site (KOMA). One 30-day window. One 20/10 chronological
split. One headline metric (MAE). One grid step (0.1). Three lead times, fixed in
advance. No site was swapped, no window was slid, no split was retried, and no metric
was changed after seeing a number.

**The evidence, rather than the assertion.** The decision log is `docs/SPEC.md` §15, and
**its commit history carries the timestamps**: the requirements commit lands before the
fetch commits, which lands before the scoring commit. Run `git log` and check the
ordering yourself — a pre-registered protocol with timestamps you can verify is a
stronger answer than any promise this README could make.

**The rule it comes from.** SPEC §10: *never tune the experiment to produce a win.* No
extra lead times, no second window, no alternative split, and no different site because
the first result was unexciting. That rule was written down before any data existed,
which is the only time such a rule can be written honestly.

### How we know it isn't fake

1440 of 1440 successful fetches and a very high join match rate are *exactly* the shape
a fabricated dataset would have. So the evidence sits beside the claim:

1. **The acceptance anchor reproduces digit-for-digit out of the parquet.** For the
   2026-08-05 12z run at f006, valid 18:00Z: HRRR **68.24**, GFS **71.65**, NAM
   **69.53**, NBM **70.61** °F. The parquet carries 68.239766 / 71.654152 / 69.525166 /
   70.610011. Four models disagreeing by three degrees is what real model output looks
   like. The nearest real observation to that valid time is **17:52 = 68.00 °F**, eight
   minutes early — there is no 18:00 observation, which is the join problem of §6 in a
   single concrete row.
2. **The missing-data detector was fired against real live 404s** on the NOAA bucket and
   raised `ArchiveMissing` as designed. The zero-missing count is therefore a *measured*
   zero on an exercised code path, not an untested branch that has never once returned
   true.
3. **The data is non-degenerate.** 1209 distinct `temp_f` values across 1440 rows, zero
   NaNs, and a real diurnal cycle when grouped by valid UTC hour — 12Z is coolest at
   about 68.3 °F and 00Z warmest at about 84.7 °F, which is dawn and late afternoon in
   Nebraska. Fabricated data rarely gets the diurnal phase right by accident.
4. **The one-hot blend identity check.** A weight vector at a corner must reproduce that
   model's own error exactly, to floating-point tolerance. It is a unit test and it is
   non-negotiable per SPEC §8: if the blend code cannot reproduce a single model, none of
   its interior points mean anything.
5. **The join is not suspiciously round.** The observation series is 932 rows over 744
   distinct hours, and only **5 of those 932** land on minute `:00`. The matched counts
   and the mean absolute offset are reported in §6 and on the page — the offset is the
   `OMA` `:52` reporting pattern showing up as data, rather than the suspiciously clean
   zero that an exact-match join would have produced by silently matching nothing.

### Two other questions worth pre-answering

**"Isn't this just MOS / ensemble averaging?"** In the mathematics, largely yes — and
the maths is decades old. The new part is not the estimator; it is doing the reweighting
*per site against the customer's own sensors*, continuously, as a service.

**"Why not just use NBM?"** NBM is already a member of the blend, and it is a strong
baseline precisely because it is itself a multi-model blend. The claim under test is
narrower than "beat NBM": it is whether site-specific reweighting *on top of* NBM still
adds anything. That claim can come back negative, and §5 reports it either way.

**Framing, once more, because it is the honest one:** a feasibility demo at one site
over 30 days, not a result.

---

## 10. What's next (v2)

- **Bias correction / MOS**, with the increment reported separately so blending and
  correction can be told apart (C3).
- **Measure the grid-cell terrain-height delta** — one `:HGT:surface:` fetch per model,
  which closes the gap named in C4 with a number instead of a mechanism.
- **More sites**, which is the only way to learn whether per-site weights generalise or
  whether KOMA is a special case.
- **A longer window**, to get past the ~30 independent days of C2.
- **More variables** — wind and dewpoint behave differently from temperature and are
  where blending may help more, or less.
- **Probabilistic metrics** (Brier, CRPS). "Most accurate model" is not one number:
  skill varies by variable, lead time and region, and a deterministic MAE ranking hides
  all of that.
- **A refetch path**, once there is a real operational reason to press it (C3 of the
  design rationale in §3: an unpressed route is dead code).

---

## 11. Repo map and commands

```
Bhar/
├── fetch/       # NOAA S3 .idx parse + byte-range GRIB fetch; IEM ASOS observations; window logic
├── score/       # join, per-model metrics, 286-vector simplex search, results.json writer
├── backend/     # FastAPI app; contract.py locks the SPEC §7 results.json shape
├── frontend/    # static page: leaderboard, weight sliders, chart, honesty panel; vendored fonts/CSS
├── data/        # coverage.json + results.json committed; *.parquet and raw/ gitignored
├── tests/       # pure-logic pytest: .idx parsing, the join, blend maths, unit conversion
├── docs/        # SPEC.md (requirements source of truth), BRIEF.md (business context)
├── scripts/     # smoke_ui.sh — agent-browser UI check
└── run.sh       # the one command that starts the demo
```

| Command | What it does |
|---------|--------------|
| `BHAR_BACKEND_PORT=8011 BHAR_FRONTEND_PORT=5184 ./run.sh` | Start backend + frontend; open the `Frontend:` URL it prints (§2) |
| `uv run pytest -q` | Full test suite; must exit 0 |
| `uv run pytest -q -m "not integration"` | Default set; integration tests use captured fixtures only |
| `uv run ruff check .` | Lint, narrow rule set — real errors, not style |
| `uv run python -m fetch.backfill` | The single data command: forecasts + observations + coverage.json |
| `uv run python -m fetch.obs` | Observations only, escape hatch |
| `uv run python -m score.run` | Join, score, search the blend grid, write `data/results.json` |
| `scripts/smoke_ui.sh` | Optional agent-browser UI check against a running demo |
| `uv run uvicorn backend.main:app --port 8000` | Backend alone (port must be free — see §2) |
| `uv run python -m http.server 5173 --directory frontend` | Frontend alone |

**There is no type checker and no build step**, deliberately (SPEC §13). Do not report
either as missing.

**`docs/SPEC.md` is the requirements source of truth** — §7 is the `results.json`
contract, which `backend/contract.py` enforces executably on every request.
`docs/BRIEF.md` carries the business context.

---

## Development pipeline

This repository was built with a Claude Code development pipeline: the orchestrator
dispatches work to agents running in isolated contexts, and each phase writes its output
to a file rather than to a conversation.
See `CLAUDE.md` at the repo root and the `.claude/` directory for how it is wired.
