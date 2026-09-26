# Bhar — What We Found, and What's Actually Worth Selling

**Written:** 2026-09-04, after the backtest shipped green.
**This file is not a contract and not a spec.** `docs/SPEC.md` is the contract for what was
built. `README.md` has the numbers and the caveats. This file is the argument — what the
result means commercially, what is genuinely old, and what to build next.

---

## The one paragraph

We backtested four NOAA forecast models against a real weather station at Omaha Eppley over
30 days, then searched every weighted blend of those models to find which would have had the
lowest error at that site. A blend did beat the best single model, by 9–17% depending on how
far ahead you're forecasting. **But almost all of that gain came from noticing that one model
(GFS) is bad at this site and dropping it — not from the clever weight-fitting.** A dumb
blend that just excludes GFS and averages the other three did as well or *better* at the 12-
and 24-hour leads. The careful fitting bought a little at 6 hours and nothing measurable
after that.

That is a real finding, it is a known phenomenon in the literature, and it means **the
product is not "we compute better weights."**

---

## Say this before someone in the room says it for you

Multi-model blending tuned to a specific site is not new. It is old enough to have several
names:

| Name | What it is | Since |
|---|---|---|
| **MOS** (Model Output Statistics) | The US weather service statistically correcting model output **per individual station**, using that station's own history | **1970s** |
| **NBM** (National Blend of Models) | NOAA's operational blend. Its weights already vary by region, lead time, variable and season | Current, operational |
| **Bayesian Model Averaging** (Raftery/Gneiting, U. Washington) | Fit multi-model weights per station against that station's observations, on a **rolling 25–40 day window** | **2005 paper** |
| **Measure-Correlate-Predict / "site adaptation"** | The wind industry calibrating forecasts to a customer's own met mast | ~30 years |
| **ForecastWatch** | Sells independent accuracy comparisons of commercial forecast providers | ~2003 |

Companies selling sensor-calibrated site forecasts *today*: **Solcast** (solar), **Tomorrow.io**,
**DTN**, **Vaisala/Xweather**.

The 2005 BMA paper is, essentially, this project — including the ~30-day rolling window.
**Leading with "we tuned the blend to the site" gets us corrected in the first two minutes.**
Leading with the honest version does not.

---

## Joe's note is right, and it has a name

> *"now that you have 'the most accurate' blend the game is to sort of nudge the blend weights
> over time as new model runs come in, and see if accuracy is getting better or worse with new
> weights"*

Correct, and that is how operational systems actually work (decaying-average bias correction,
rolling training windows). The formal name is **online learning / prediction with expert
advice**. The strong version of it (multiplicative weights, a.k.a. Hedge) carries a **regret
bound** — a mathematical guarantee that, over time, the adaptive blend converges to *no worse
than the best single model chosen in hindsight*.

That is a genuinely good line to sell: **"you don't have to know in advance which model to
trust at your site, and we provably can't do worse than picking the right one."** It is also a
modest change to code we already have.

**One correction worth making before repeating it:** this is not how *ensemble* models work.
An ensemble (GEFS, ECMWF ENS) perturbs the starting conditions inside a *single* model to
sample uncertainty. What we're doing is statistical post-processing *across different models*.
NBM is the blend; GEFS is the ensemble. Different layers of the stack.

---

## Our own data refutes the obvious pitch

From `README.md` §5.1:

| Lead | Un-fitted "drop GFS, average the rest" | Our fitted winner | Best single model |
|---|---|---|---|
| 6 h | 1.9865 °F | **1.9173 °F** | 2.1075 °F |
| 12 h | **1.8879 °F** | 1.9661 °F | 2.2814 °F |
| 24 h | **2.0886 °F** | 2.1066 °F | 2.5231 °F |

At 24 hours the un-fitted blend is the **best of all 286 weight combinations we tested**.

This is not a bug and not bad luck. It's the **forecast combination puzzle** (Smith & Wallis,
2009): simple averages routinely beat statistically-estimated "optimal" weights, because the
error in *estimating* the weights is larger than the gain from having them. With roughly 30
independent days of data we cannot reliably estimate three free parameters.

**So: don't lead with +16.51%.** Lead with *"we built the harness that told us the fitted
weights weren't the value — here's what is."*

---

## Four things that could actually be different

Ranked by how defensible they are.

### 1. Optimize the customer's cost, not average error

Nobody buys "degrees Fahrenheit of average error." They buy a decision.

A grower doing frost protection does not care about average error at all. They care about one
thing: *does it cross 32 °F tonight?* And their costs are **wildly asymmetric** — being 2°
too warm kills the crop; being 2° too cold means they ran the heaters for nothing. A blend
tuned to minimize average error is tuned for the wrong objective for that customer.

Same search, same code, different scoring function — and now our "optimal blend" is
legitimately different from NOAA's, per customer, for a reason we can explain. **NOAA
optimizes for the average of everybody. We optimize for one balance sheet.** That is the
cleanest answer to "why not just use NBM?"

### 2. Weights that change with the weather situation

One set of weights per site is too blunt, and it's probably *why* the fitting bought us
nothing. HRRR likely wins on clear calm nights and loses during warm air advection. Fit the
weights **conditional on the situation** — wind direction, cloud cover, day/night, season,
snow cover — and the fitting starts earning its keep, because a fixed equal-weight average
structurally cannot adapt.

This is also where local knowledge actually lives: cold-air pooling in a valley, lake breeze,
urban heat island, downslope warming. Those are systematic, *situation-dependent* errors. One
global weight can't capture them. A conditional model can.

### 3. The archive

**You cannot buy the past.** Commercial forecast APIs generally forbid storing their output,
and nobody publishes their old forecasts. Whatever we start recording today is what we own in
a year.

Be precise about the moat, though: **NOAA's archive is public on S3, so there is no moat
there.** The scarce assets are (a) *commercial vendor* forecasts as issued, and (b) customer
sensor history. This was the "ten-line cron job" in `docs/BRIEF.md` §6 and it is still not
built. The clock doesn't start until it is.

### 4. The guards — the boring code nobody else writes

We accidentally built the valuable part. Anyone can write the weight search; `BRIEF.md` says
it's "~40 lines of pandas," and it is. What almost nobody writes is the machinery that stops
you fooling yourself:

- Weather station reports land at `:52`, not on the hour. A naive exact-time join between
  forecasts and observations matches **zero rows** — and zero rows doesn't crash, it scores
  *perfectly*. We have a hard assert on the match rate. **This trap fired on us for real.**
- The obvious search string for "2 m temperature" is also a substring of "apparent
  temperature," which silently returns a different variable that looks completely reasonable.
  **This also fired on us for real.**
- Weights fitted and reported on the same 30 days are guaranteed to look good by arithmetic
  alone. We fit on the first 20 days and report on the last 10.
- The results contract explicitly **refuses to check that the improvement is positive**, so
  the system can report that we lost.

Every project that skips these ships a confident, fake number. That is a sellable service on
a platform: **verification you can't fool yourself with.**

---

## "Why wouldn't a customer just build this themselves?"

For the weight search: **they would, and fast.** Don't sell that.

What they won't rebuild well:
- The **archive** they cannot retroactively create.
- The **guards** above — they'll skip them, and they'll get a beautiful fake number.
- The **ingest ops**: 8+ models × many lead times × 4 cycles a day, forever, with all the
  GRIB traps. Nobody wants to own that.
- The **cost function elicitation** — figuring out what their errors actually cost them, and
  scoring against that. That's a conversation, not a library.

On a bring-your-own-data platform this is positioned as **a scoring and verification tier**,
not as a forecast product: *"bring your sensors — we'll tell you which of your vendors is
actually good at your site, in your cost function, and prove it out-of-sample."*

---

## What to build next, in order

1. **Add ECMWF.** IFS open data at 0.25° is free now, as are AIFS, ICON, GEM/HRDPS, RRFS.
   Our entire result is currently "GFS is bad at Omaha," and **the strongest global model in
   the world isn't in the study at all.** Cheapest, highest-value change available.
2. **Start the archive cron.** Ten lines. The clock doesn't start until it runs.
3. **More sites (100+ ASOS stations, all free).** The only way to learn whether per-site
   weights generalize or whether Omaha is a special case. The fetch code already does this;
   it's a loop.
4. **A year of history instead of 30 days.** We measured ~372 MB per month. A year is ~4.5 GB.
5. **Score against a real customer cost function** (item 1 above) on one concrete use case.
6. **Situation-conditional weights** (item 2 above).
7. **Adaptive/online weights** — Joe's note, with the regret guarantee.

---

## What last night actually bought us

Three things, none of which is "+16.51%":

1. **The data path is de-risked and proven.** Byte-range GRIB fetching from NOAA works for
   four models; the two silent-failure traps are found and guarded.
2. **An honest, slightly negative result.** The clever part didn't help much. A negative
   result you can trust is worth more than a positive one you can't — and it told us what
   *not* to sell before we sold it.
3. **A reusable verification harness**, which is more valuable than the finding it produced.

**The framing to use, unchanged from the README: a feasibility demo at one site over 30 days.
Not a result.**
