# Site-Tuned Model Blend — Project Brief

**Author:** Sanjay (Shyft)
**Date:** Fri Sep 4, 2026
**Deadline:** demo tomorrow morning (dev day / hackathon)
**Status:** MVP not yet built. This doc is the full context so far.

> Instructions for the assistant reading this: before writing any code, grill me on the **Open Questions** and **Things I Might Be Wrong About** sections. Push back where the plan is weak. Then build the MVP described under **Tonight's Scope** and leave a working demo plus a short README by morning.

---

## 1. One-sentence version

Backtest several NOAA weather models against observed data at one location, then find the weighted blend of those models that would have had the lowest error there.

## 2. Thirty-second version

NOAA publishes several forecast models (HRRR, GFS, NAM, NBM). They disagree, and which one is best varies by location. Pull 30 days of past forecasts from each for one airport, pull the observed temperatures from that airport's weather station, score each model's error. Generate a grid of weighted blends, score every blend identically, rank them. Output: "at this site, 70% HRRR / 30% GFS beat every individual model by X%."

Long term: a customer with their own sensors runs this loop continuously at their site and the weights converge to whatever works there.

## 3. How the idea got here

1. **Started as:** a "premium, more generic" consumer weather app. Killed because the forecast layer (NWP models) isn't the dated part — the presentation layer is — and consumer weather is a monetization graveyard.
2. **Became:** forecast reliability as a product. A third-party scorecard telling you how much to trust any forecast. Insight: nobody in consumer weather surfaces verification history.
3. **Became:** a benchmark sold to enterprise weather-data buyers (insurance, energy, ag, logistics) who license commercial feeds with no independent comparison.
4. **Joe's upgrade:** don't just grade models, **blend them**. Weights vary per location. A customer verifies against their own site obs and the blend converges over time. Turns a critique into a better forecast and kills the "makes vendors look bad" problem.
5. **Joe's second note:** try many blends, include pure single models as blend members, score them all, rank automatically against obs. (Also: user yay/nay UI — deferred.)
6. **Joe's third note:** more models exist for temp (NBM, NAM). His hosted tool **folkweather** exposes several models via **EDR**. Or ingest raw GRIB and extract point data.

Ownership isn't a concern. This is a team thing, possibly living inside Shyft's in-development platform **wxchange**.

## 4. What's actually novel (be honest about this)

- Multi-model blending is **not** new. NBM = National Blend of Models. MOS (per-station statistical correction) has existed since the 1970s.
- The defensible part: tuning the blend to a **specific customer site using the customer's own sensors**, delivered as a service. NOAA cannot tune to a farm it has no thermometer on.
- Moat is per-customer and sticky: switching means throwing away months of tuning.
- Secondary moat: archived forecast history. You can't buy the past. Nobody archives their old forecasts publicly; commercial API ToS usually prohibit storing output. Whatever you start capturing today is what you have in six months.

## 5. Business context (not needed for tonight, keep for the pitch)

Buyer ladder, worst payer first:
- Consumers — won't pay
- App developers — small recurring API fees for a confidence score / blended forecast
- Forecast providers — want a neutral scorer to cite
- Enterprise data buyers (insurance, energy, farms, logistics, utilities) — real budgets, no independent benchmark exists today

Pricing idea from Joe: cheap per-forecast API.

Methodological warning: "most accurate" is not one number. Skill varies by **variable, lead time, and region**. Score on all three axes with standard metrics (MAE/bias for continuous; Brier or CRPS for probabilistic). A single leaderboard will get torn apart by anyone in the field.

---

## 6. Tonight's Scope (the MVP)

Brutally small. One evening.

| Dimension | Choice | Why |
|---|---|---|
| Site | Omaha Eppley Airfield, **KOMA** (IEM station id `OMA`) — 41.3032, -95.8941 | Local, has hourly METAR, screenshot already in hand |
| Variable | **2 m temperature** | Easiest to score, no probability math, readable on a chart |
| Models | **HRRR + GFS minimum**; add **NAM** and **NBM** if data access is cheap | Two is enough to prove the idea; code shouldn't care how many |
| Lead times | **6h, 12h, 24h** | Three points on a curve |
| Window | Last **30 days** of forecast runs | Enough to score, small enough to fetch |
| Init time | Use the **12z run** for every model every day | HRRR only runs to 48h at 00/06/12/18z; keeps everything comparable |
| Ground truth | Hourly **METAR** obs for KOMA | Free, official, hourly |
| Metric | **MAE** per model per lead time (also report bias) | Simple, defensible |
| Blend search | Coarse grid of weight vectors summing to 1, step 0.1 | Pure models are the one-hot corners, so they're ranked for free |
| Output | One page: leaderboard + error-vs-weight curve | Whole pitch in one screen |
| Language | **Python** | Rust is the long-term plan; not tonight |

### Explicitly out of scope tonight
- Yay/nay user feedback UI (Joe's long-term idea; automatic scoring vs obs beats human votes when sensors exist)
- Multiple sites
- Commercial providers (ToS risk, no history anyway)
- Precipitation / probabilistic variables
- Live serving / API
- Anything in Rust

### Nice-to-have if time remains
- A cron job that snapshots today's forecasts to S3 daily. Ten lines. Starts the clock on the archive moat.

---

## 7. Pipeline

1. **Fetch forecasts** — point time series of 2 m temp at KOMA for each model, each lead time, each day in window.
   - **Path A (preferred if it works): folkweather EDR.** OGC EDR position query, something like
     `/collections/{model}/position?coords=POINT(-95.8941 41.3032)&parameter-name=t2m&datetime=...`
     Returns JSON time series. Skips GRIB parsing entirely.
     **Blocker:** only useful if folkweather keeps **past runs**. Most EDR endpoints serve latest only. Asked Joe; answer pending.
   - **Path B (fallback): NOAA AWS archives via Herbie.**
     - HRRR: `s3://noaa-hrrr-bdp-pds` (CONUS, 3 km, hourly runs)
     - GFS: `s3://noaa-gfs-bdp-pds` (0.25°, 6-hourly runs)
     - NAM: `s3://noaa-nam-pds` (12 km, 6-hourly runs)
     - NBM: `s3://noaa-nbm-grib2-pds` (hourly runs)
     - Herbie sketch (verify against current Herbie API):
       ```python
       from herbie import Herbie
       import pandas as pd
       H = Herbie("2026-08-05 12:00", model="hrrr", product="sfc", fxx=6)
       ds = H.xarray("TMP:2 m above ground")
       pt = ds.herbie.pick_points(pd.DataFrame({"longitude": [-95.8941], "latitude": [41.3032]}))
       ```
     - Subset to the temperature field only so each download is a few hundred KB, not hundreds of MB.
     - Convert Kelvin → °F.
2. **Fetch observations** — hourly temp at KOMA from Iowa Environmental Mesonet ASOS archive.
   - UI: `https://mesonet.agron.iastate.edu/request/download.phtml?network=NE_ASOS`
   - Scriptable CSV endpoint exists (`/cgi-bin/request/asos.py?station=OMA&data=tmpf&...&tz=Etc/UTC&format=onlycomma`). Verify parameters.
   - Use UTC everywhere.
3. **Join** on **valid time** (init time + lead time), not init time.
4. **Score** MAE and bias per model per lead time.
5. **Search** — enumerate weight vectors on a simplex grid (step 0.1). For 2 models: 11 blends. 3 models: 66. 4 models: 286. Compute blended forecast, score identically.
6. **Rank** blends per lead time.
7. **Display** — leaderboard (top N plus all pure models) and error-vs-HRRR-weight curve. Lead-time toggle.

Steps 1–2 are where the evening goes. Steps 3–7 are ~40 lines of pandas.

## 8. Demo page spec

Already mocked up. Structure:

- Header: `Omaha Eppley (KOMA)` · `Last 30 days` · `2m temperature, N candidate blends scored vs METAR`
- Lead-time toggle: `6h | 12h | 24h`
- Leaderboard rows: rank · weight label (e.g. `70 / 30`, `HRRR only`) · stacked weight bar (HRRR blue, GFS orange) · error °F. Winner highlighted.
- Footer line: `Winner beats best single model by X%. Showing top 4 of 11 plus the two pure models.`
- Chart: error (y) vs HRRR weight 0→100% (x). Both ends are pure models; the dip in the middle is the value.

Build the page with fake numbers first, swap in real ones once the fetch works. Never stare at nothing at midnight.

## 9. Expected results (so nobody is surprised)

- HRRR will probably beat GFS at short lead times at a CONUS station.
- **NBM will probably beat any HRRR/GFS blend** — it's already NOAA's bias-corrected blend. That's fine and is a better demo: include NBM as a pure member, let it win round one, then show whether a blend *including* NBM edges it out. "We beat NOAA's blend by tuning it to this site" is the stronger line.
- The dip may be shallow or absent at some lead times. "The blend ties the best model" is still a real result: you didn't have to know in advance which model to trust.

## 10. Open Questions — grill me on these

1. **Does folkweather EDR store past runs or latest only?** Determines Path A vs B. If unknown at build time, go Path B.
2. **Train/test split.** With 30 days, fitting weights on all 30 and reporting error on the same 30 is overfitting. Should we fit on days 1–20 and evaluate on 21–30? (Probably yes. Report both in-sample and out-of-sample.)
3. **Nearest grid point vs interpolation.** Nearest grid cell is fine for tonight; note elevation mismatch between grid cell and station (~299 m ASL).
4. **Obs QC.** METAR has occasional bad/missing hours. Drop missing, don't interpolate.
5. **Which init times?** 12z only for simplicity, or all four synoptic runs for 4× sample size? Trade sample size against fetch time.
6. **Bias correction before blending?** A per-model additive bias correction (MOS-lite) before weighting will likely help. Include or leave for v2?
7. **Herbie availability.** Is Herbie installed and does the AWS archive have all 30 days for every model? HRRR archive occasionally has gaps.
8. **Timezones.** Everything in UTC. METAR valid times are on the hour; model output at 12z + fxx is on the hour. Confirm alignment.

## 11. Things I Might Be Wrong About

- That folkweather EDR is faster than Herbie. If the endpoint is flaky or latest-only, it isn't.
- That 30 days is enough to see a meaningful dip. It may not be. That's acceptable for a feasibility demo, not for a claim.
- That MAE is the right headline metric. RMSE punishes large misses harder and might be what a customer cares about. Report both.
- That per-site weight tuning adds value on top of NBM at all. This is the actual hypothesis. Tonight tests it at one site.
- That the Herbie `pick_points` API is as sketched above. Verify.
- That IEM station id is `OMA`. Verify.

## 12. Anticipated engineer pushback and answers

- *"Isn't this just ensemble averaging / MOS?"* Yes, the math is old. New part: per-customer-site against the customer's own sensors, as a service.
- *"Why not just use NBM?"* NBM is a member. Claim under test: site-specific reweighting on top of NBM still helps.
- *"30 days, one site, that's nothing."* Correct. Feasibility demo, not a result.

## 13. Deliverables by morning

- `fetch_forecasts.py` — Path A or B, writes `forecasts.parquet` (columns: model, init_time, lead_h, valid_time, temp_f)
- `fetch_obs.py` — writes `obs.parquet` (valid_time, temp_f)
- `score.py` — join, per-model MAE/bias, blend grid search, ranked output as JSON per lead time
- `demo.html` — the page in §8, reading the JSON
- `README.md` — how to run, what the numbers mean, known caveats, what's next
- Optional: `snapshot_today.py` + cron line

## 14. People

- **Joe (Shyft):** originated the blend framing and the "score many blends" approach. Hosts folkweather. Building wxchange. Prefers concrete, small demos.
- **Sanjay:** new to weather domain, learning by building. Long-term interest in a Rust GRIB2 engine for flight/drone sim; this project is a separate, faster path into the same data.
