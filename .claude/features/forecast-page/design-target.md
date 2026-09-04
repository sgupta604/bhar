# Design Target — forecast-page (F1)

**Source:** `.claude/features/site-tuned-blend/clarity-design-tokens.md` (Clarity v0.2, the primary
source — every token named in this document exists there). Cross-referenced against
`docs/FORECAST-SPEC.md` §5.2 (run label, staleness), §5.3 (step grid, gaps), §6 (historical skill
only — the integrity core), §7 + §7.1 (forward weight banding, weight staleness), §9 (the
`forecast.json` contract), §10 (history payload), §11 (503), §12-F1 (this ticket), §15 (integrity
rules) and §17 (design and frontend).

**Sibling document:** `.claude/features/demo-shell/design-target.md` (T3). This document is a direct
descendant of it and the two are meant to read as one system. Where T3 already settled a fact — the
model→colour map, the range-slider CSS, the chart/axis CSS, the three improvement states, the
numeric-formatting rule — this document **references it and does not restate it**.

### What this document is, and what it is not

This is a **written visual target**. F1 produces **no HTML, no CSS and no JS file**. Every literal
CSS block below is **specification text**, to be pasted into a file that a *later* ticket creates:

| File | Written by | Reads which sections here |
|---|---|---|
| `frontend/forecast.html` | **F5** | §1.1–1.4, §1.7–1.9, §3, §5, §7 |
| `frontend/forecast.css` | **F5** | §0.1, §0.2, §2, §3, §5, §6, §7 |
| `frontend/forecast.js` | **F5** | §1.2–1.4, §3, §5, §6 |
| the history view | **F6** | §1.6, §6 |
| the trust panel | **F7** | §1.5, §4, §6 |

None of those files exists yet, and F1 must not create them.

### Rules this document follows, and that the frontend implementer must also follow

- **Semantic tokens only.** Never a raw scale value in UI chrome. The one sanctioned exception is
  the model→colour map (§0.1), which is consumed as `var(--model-*)` and is itself defined in terms
  of the data-viz scale inside `frontend/tokens.css`.
- **Never an invented token name.** Every `var(--…)` in this document exists in
  `clarity-design-tokens.md`. Clarity has **no font-size tokens, no chart tokens, no slider tokens
  and no timeline/strip tokens** — those sizes are per-component literals, and each block that uses
  a literal says so in its preamble.
- **Target viewport 1440×900**, matching T3.
- **The run label (§1.1) must be reachable without scrolling at 1440×900.** This is a hard
  requirement, not a preference — see §5.2 of the spec and §7 below.
- **Section numbers in this document are a contract.** F5, F6 and F7 are three separate tickets
  reading this one document and citing its sections. Do not renumber.
- **Section-reference convention.** A bare `§n` always means *this document*. A reference to any
  other document is always qualified by name — `FORECAST-SPEC §5.2`, `token doc §5.7`, `T3 §3`.
  This matters because the numbering genuinely collides: FORECAST-SPEC has a §1.3, a §5.2 and a
  §5.3, and so does this document, and they mean entirely different things.
- Every shared fact is stated **once** and referenced by section number everywhere else.

---

## 0. Reuse by reference, and what is banned in this design

This section is the foundation. Every later section references it rather than restating it.

### 0.1 The model → colour map — BY REFERENCE, never re-derived

The map is stated once, as prose, in `.claude/features/demo-shell/design-target.md` §0, and is
implemented once, in CSS, in `frontend/tokens.css` — inside the `:root` block under the comment
banner **`Model -> color map. Single source of truth for the page`** (verified at write time:
`frontend/tokens.css:5-17`, the four declarations at `:9-12`).

| Model | Bhar-local custom property | Clarity data-viz token | Hex |
|---|---|---|---|
| HRRR | `--model-hrrr` | `--blue-500` | `#329af0` |
| GFS | `--model-gfs` | `--orange-500` | `#ff922b` |
| NAM | `--model-nam` | `--purple-500` | `#a551cf` |
| NBM | `--model-nbm` | `--green-500` | `#51cf66` |

Those hexes are printed here **for reading convenience only.**

> **`forecast.css` must not redeclare `--model-hrrr`, `--model-gfs`, `--model-nam` or
> `--model-nbm`.** It consumes them as `var(--model-hrrr)` etc. from the linked `tokens.css`.
> `frontend/tokens.css` **is** on FORECAST-SPEC §3's permitted-link list, so the forecast page gets
> the map for free by linking it. That single definition is exactly what guarantees HRRR is the
> same blue on the demo page and on the forecast page (§17). A second declaration is how they drift.

**The one sanctioned exception is the dark theme layer (§5.3).** Stepping the series from the 500
weight to the 300 weight in dark necessarily re-states the four names inside a `[data-theme=dark]`
block. That is the *theme layer* of the same map — same names, same hues, same `var(--<hue>-N00)`
form — not a second source of truth, and the light values remain declared once and only once in
`tokens.css`. No other block in `forecast.css` may re-state them for any reason. §5.3 carries the
full reasoning and the migration note for the day the demo page gains a dark theme.

`frontend/models.js:17-21` reads these back out of `getComputedStyle(document.documentElement)`;
that mechanism is why the parity holds at runtime and not merely on paper.

Data-viz pink (`--pink-500` `#f0329a`) and yellow (`--yellow-500` `#f7be1e`) remain **deliberately
unused for a model**, per T3 §0 — pink collides with `--danger`, which this page spends on the
synthetic banner and on a non-positive improvement, and nowhere else.

### 0.2 T3's two shipped Clarity gap blocks — BY REFERENCE, never restated

Two of Clarity's three gaps were already filled by T3 and are already shipped in linkable
`frontend/tokens.css`. **This document does not restate their CSS, and `forecast.css` must not
copy it.** Locate each by its comment banner (`grep -n 'Clarity gap' frontend/tokens.css`); the
line ranges are verified at write time but will shift:

| Gap | Comment banner | Location | Status |
|---|---|---|---|
| #1 Range slider | `── Weight slider — Clarity gap #1 (no native range styling exists in Clarity) ──` | `frontend/tokens.css:49-142` | **Shipped.** Reuse as-is if the forecast page ever needs a range input |
| #2 Chart / axis | `── Chart / axis — Clarity gap #2 (no chart-series or axis tokens exist in Clarity) ──` | `frontend/tokens.css:144-207` | **Shipped.** Reuse for any axis or chart-card chrome |

Also already shipped and reused by reference, not restated:

| Thing | Location | Used by |
|---|---|---|
| Synthetic-banner CSS | `frontend/tokens.css:19-47` (`html[data-synthetic="true"]` + `.synthetic-banner`) | §1.8, §3 |
| `.num` / `.mono-value` | `frontend/tokens.css:209-214` | §6 |

> **The forecast strip is Clarity gap #3, and it is the only gap F1 writes CSS for.** Clarity has
> no timeline, no strip and no per-step-cell component of any kind (§17). Its literal CSS is §2.
> The stale treatment (§3) is the one other place this document authors new literal CSS, because
> Clarity has no such pattern either; it mirrors the *shape* of the synthetic block, not its colour.

<!-- BANLIST:START -->
### 0.3 Banned in this design — FORECAST-SPEC §6.2

**Read this before §1.2, §1.4, §1.5, §2 and §4.** It is placed here, ahead of every region spec,
because the strip and the spread figure are precisely where a well-intentioned "improvement" will
try to add the thing this section forbids.

FORECAST-SPEC §6 is the single most important section in that document. The trust panel shows **how
this blend performed at this site, at this lead time, over the scored 30-day window**. It is
history, stated in the past tense. It is never a promise, a probability, or an interval around
tomorrow's number. Rendering past MAE as a band around a future number claims that past skill
transfers to *this particular* forecast — it does not, and it fails hardest during exactly the
extreme events people care about.

**Banned field, key, class and label names — anywhere on this page or in this document:**

`confidence` · `confidence_pct` · `probability` · `p10` · `p50` · `p90` · `percentile` ·
`ci_low` · `ci_high` · `error_bar` · `uncertainty`

**Banned character usage:** the character `±` attached to any forecast value. It does not appear
anywhere in this document outside this block, and must not appear anywhere in
`frontend/forecast.{html,js,css}`.

**Banned visual forms — around the forecast line or the blend value, anywhere on the page:**

1. a **band**
2. a **ribbon**
3. a **shaded envelope**
4. a **whisker**

**Banned copy phrasings:** "We are N% confident" · "there is an N% chance" · "expected error of
±X" · "accurate to within X".

**The §6.3 carve-out — model spread IS allowed.** `members` (each model's own forecast at that
step) and the derived `member_spread_f` (max − min) may be shown, because **they are facts about
the models, not a probability**. They may be rendered as a "how much the models disagree right now"
figure — four discrete member marks, a small strip, or a 4-point sparkline. Subject to two
restrictions, both non-negotiable:

- **Never drawn as an error bar around the blend value.** Not as a bar, not as a bracket, not as
  any geometry attached to `blend_f`. If it touches the blend number, it is wrong.
- **Never converted into a percentage.** Disagreement is not calibrated uncertainty and the page
  must not imply that it is.

**The BANLIST rule — addressed to every later section of this document, and to F5, F6 and F7.**
Every string listed above appears **in this block and nowhere else in this document**. The same
holds for `frontend/forecast.html`, `frontend/forecast.js` and `frontend/forecast.css`, which have
no equivalent block and therefore must contain none of them at all. The gate is two lines and is
meant to be re-run by every downstream ticket against its own source files:

Strip this block by its two HTML-comment markers, then grep what remains for:

```
confidence|probability|percentile|uncertainty|error_bar|ci_low|ci_high|\bp10\b|\bp50\b|\bp90\b|±
```

The exact two-line `awk | grep` invocation is written out in the F1 plan
(`.claude/features/forecast-design/2026-09-04T16-20-01_plan.md`, Task 6.1) and in F1's handoff
checklist. It is **not** reproduced here: an `awk` script that names the marker strings, sitting
inside the block those markers delimit, closes the block early and leaks the rest of it past the
filter. Keep the invocation in the plan, keep the pattern here.

It must return nothing. `forecast/contract.py` (F3) enforces the same ban on the payload with an
exact-key-set check, so a banned key name fails validation before it can ever reach the page.

**Say it in words instead.** Where a later section needs to forbid the plus-or-minus form, it
writes *"never attach a plus-or-minus figure to a forecast value"* rather than printing the
character. Where it needs to name the forbidden geometry it writes *"band, ribbon, shaded envelope
or whisker"*, which are ordinary words and are not on the grep list.
<!-- BANLIST:END -->

---

## 1. Per-region specification

The eight regions of FORECAST-SPEC §12-F1, each specified concretely — tokens named, sizes stated,
copy written verbatim.

| # | Region | Section(s) here | Governing clause in **FORECAST-SPEC** |
|---|---|---|---|
| 1 | Headline number + run label | §1.1 | §5.2 |
| 2 | The forward strip | §1.2, §2 | §5.3, §7, §17 |
| 3 | The 24 h fitted-range boundary | §1.2, §2, §4 | §7 |
| 4 | Gap treatment | §1.3, §2 | §5.3, §15 |
| 5 | Trust panel | §1.5, §4 | §6.1, §7, §7.1 |
| 6 | Back-arrow + past-day view | §1.6 | §10 |
| 7 | Stale treatment + synthetic banner | §1.7, §1.8, §3 | §5.2, §15 |
| 8 | Empty state (503) | §1.9 | §11 |

### 1.1 Page frame, headline number, and the permanent run label

**Frame.** The page reuses `index.html`'s shell idiom exactly: page background `--bg` (`#f8f9fa`),
a centred column `max-width:1380px`, page padding `var(--s-8)` (32px) horizontal,
`var(--s-4)` (16px) top. The synthetic banner (§1.8) sits **outside** the shell, as the first child
of `<body>`, so it never shifts the column's horizontal rhythm. Those `.shell` / `.page-header` /
`.page-title` / `.page-sub` rules live in `frontend/app.css`, which is **not** on FORECAST-SPEC §3's
permitted-link list — `forecast.css` therefore **re-authors** them from the token doc rather than
importing them. That duplication is correct and deliberate; **§7 carries the full re-author list.**

**Page header** — the `.page-header` idiom (token doc §5.9), matching `frontend/index.html`'s header
line for line so the two pages read as one product:

| Element | Class | Spec |
|---|---|---|
| Title | `.page-title` | `--font-display` (Sora), 24px / 600, `line-height:1.2`, `letter-spacing:-.02em`, `--text`. Copy: `Forecast — Omaha Eppley (KOMA)` |
| Site line | `.page-sub` | `--font-ui` (Inter), 13.5px, `--text-muted`. Copy: `KOMA · Omaha Eppley Airfield` |
| Scope line | `.page-sub` | `--font-ui`, 13.5px, `--text-muted`. Copy: `2m temperature · degF · next <meta.horizon_h> h at <meta.step_h> h steps` |
| Layout | `.page-header` | `display:flex; align-items:flex-start; gap:var(--s-4); margin-bottom:var(--s-3)` |

The site line is **composed from `meta.site`, never retyped**: `meta.site.id` + ` · ` +
`meta.site.name`. `meta.site` is itself copied verbatim from `results.json` into `forecast.json`
(§9). `frontend/app.js:73` already does the equivalent (`$('header-site').textContent =
meta.site.name`) and F5 repeats that mechanism — a hardcoded `"Omaha Eppley Airfield"` string in
the HTML is a defect, because it survives a site change that nothing else survives.

**The headline number.** One `.stat-card` (token doc §5.6), holding exactly **one `blend_f`, in °F,
for the nearest forward step** — the first row of `forecast[]` by `valid_time`, i.e. the smallest
`lead_h` present. Not an average, not a range, not a next-24-h summary.

| Part | Class | Spec |
|---|---|---|
| Label | `.stat-label` | 12px, `--text-muted`, `display:flex; gap:6px`. Copy: `Next step · <lead_h> h lead · <valid_time> ` |
| Value | `.stat-value` | `--font-display` (Sora), **30px / 600**, `line-height:1.1`, `letter-spacing:-.025em`, `font-variant-numeric:tabular-nums`, `margin-top:6px`, colour `--text`. Renders `78.4 °F` — one decimal, per §6 |
| Meta | `.stat-meta` | 11.5px, `--text-subtle`, `margin-top:8px`, `display:flex; align-items:center; gap:6px`. **This is the run label.** |

Card chrome: `background:var(--bg-elev); border:1px solid var(--border);
border-radius:var(--r-xl); box-shadow:var(--shadow-1); padding:18px 20px`.

> **The headline temperature is the ONE Sora numeric on this page.** It is the hero number and
> Clarity reserves Sora for exactly that (token doc §5.6: *"The hero number reads in Sora;
> supporting numbers stay in mono"*). **Every other numeric temperature and error value on the page
> is `--font-mono` (JetBrains Mono) with `font-variant-numeric:tabular-nums`** — see §6.

**The permanent run label.** It is a `.stat-meta` inside the headline stat card, structurally
adjacent to the number. That placement is not decoration: it makes the label share the number's
position in the layout, which puts it above the fold at 1440×900 for free and keeps the two from
ever drifting apart in a later edit.

Format, **verbatim**:

```
Run 2026-09-04 12:00Z · 5 h old
```

Composed from `meta.cycle.init_time` (rendered `YYYY-MM-DD HH:mmZ`, UTC, never localised) and
`meta.cycle.age_minutes` (floored to whole hours). `meta.cycle.run_label` (`"12z"`) exists in the
contract and is available for compact contexts such as a cell tooltip; the header string is the
format above and is not abbreviated. The label's own text stays `--text-subtle` in the fresh state;
in the stale state it takes the `--warn` tone (§1.7, §3) — **it changes colour, it never appears or
disappears.**

> **§5.2 anti-pattern, stated explicitly: the run label is permanent chrome and is NEVER a warning
> badge.** A label that appears only when something is wrong trains the viewer to ignore it — and
> the one case where it must be read is the case where it was never shown before. It is visible in
> **all four states**: fresh, stale, synthetic, and beside the empty state wherever a cycle is known
> (§1.9). There is no configuration, no viewport and no payload under which the page shows a
> temperature without saying which run produced it.

**Above-the-fold requirement — 1440×900, hard requirement, not a preference.** The run label must be
readable **without scrolling** at 1440×900. The vertical budget the layout must respect:

| Band | Height |
|---|---|
| Synthetic banner (only when `data-synthetic="true"`) | ~33px |
| Shell top padding `var(--s-4)` | 16px |
| `.page-header` (title + two `.page-sub` lines) + `margin-bottom:var(--s-3)` | ~86px |
| `.stat-card` top padding → `.stat-value` baseline | ~60px |
| `.stat-value` → `.stat-meta` (the run label) | ~46px |
| **Run-label baseline, worst case (banner present)** | **≈ 241px** |

That leaves the requirement satisfied with more than 650px of margin, which is the point: the run
label sits so far above the fold that no plausible future addition to the header can push it below
one. **F5 must re-check this after any header change**, and the check is exactly "load at 1440×900,
the run label is visible before any scroll". Any layout that puts the headline number in a right-
hand rail, behind a tab, or below the forward strip fails this requirement.

---

### 1.2 The forward strip — layout, weight bands, and the fitted-range boundary

The strip is the page's spine: one **cell per forward step**, left to right, oldest lead first. Each
cell carries exactly three things on its face — `lead_h`, `valid_time`, `blend_f` — plus the member
marks of §1.4. Everything else about that step (`weights`, `weights_fitted_at_lead_h`,
`member_spread_f`) lives in the detail panel below the strip, described at the end of this section.

**Read §0.3 before implementing this section.** The strip is the single most likely place on the
page for a well-meaning addition to violate FORECAST-SPEC §6.2.

#### The grid is data, not a constant

**The cell count is never hardcoded.** The strip is generated from `meta.horizon_h` and
`meta.step_h`:

```
n_steps  = meta.horizon_h / meta.step_h
lead_h   = meta.step_h × i,  for i in 1 … n_steps
```

F2's probe determines the real grid (FORECAST-SPEC §5.3 — the step grid is the **intersection**
across all four models, not an assumption). A frontend that assumes 16 cells will render a wrong
page the first time NAM's horizon comes up short, and will render it *confidently*. Every number
below that looks like a constant is a worked example of one particular payload.

Per §9 rule 8, every `valid_time` on that grid appears in `forecast` **or** in `gaps` — never both,
never neither. The strip therefore has exactly `n_steps` cells always; a `gaps[]` entry produces a
gap cell (§1.3), not a missing cell. **The strip never has a hole in it.**

#### Worked example A — the full horizon (`horizon_h: 48`, `step_h: 3` → 16 cells)

| Cell | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `lead_h` | 3 | 6 | 9 | 12 | 15 | 18 | 21 | 24 | 27 | 30 | 33 | 36 | 39 | 42 | 45 | 48 |
| `weights_fitted_at_lead_h` | 6 | 6 | 6 | 12 | 12 | 12 | 24 | 24 | 24 | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| `is_extrapolated_lead` | — | — | — | — | — | — | — | — | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** |

Banding rule (FORECAST-SPEC §7): **nearest fitted lead by absolute difference, ties to the shorter
lead.** `fitted_leads` is `[6, 12, 24]`. `is_extrapolated_lead` is `true` **iff**
`lead_h > max(fitted_leads)`. The band is read off `weights_fitted_at_lead_h` in the payload — the
page never recomputes it, so the payload and the pixels cannot disagree.

**The boundary lands between cell 8 and cell 9. Exactly half of this strip is unverified.**

#### Worked example B — a truncated horizon (`horizon_h: 24`, `step_h: 3` → 8 cells)

| Cell | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| `lead_h` | 3 | 6 | 9 | 12 | 15 | 18 | 21 | 24 |
| `weights_fitted_at_lead_h` | 6 | 6 | 6 | 12 | 12 | 12 | 24 | 24 |
| `is_extrapolated_lead` | — | — | — | — | — | — | — | — |

Here **no cell is extrapolated, and the boundary rule is not drawn at all.** The boundary is a
consequence of the data (`any(is_extrapolated_lead)`), never decoration that is always present. Two
bands appear where three did; the 24 h band is two cells wide instead of ten.

**What the page tells the viewer when the horizon is short.** A silently shorter strip is a lie by
omission — it lets a viewer conclude that 24 h is all NOAA publishes. So whenever
`meta.horizon_h < 48`, a `--warn`-toned note sits directly beneath the strip (`.strip-note`, CSS in
§2), stating the horizon, the reason, and the models responsible. It is derived, never typed:

> **Horizon truncated to `{meta.horizon_h}` h.** The step grid is the intersection of all four
> models; `{join(unique(gaps[].missing_models))}` did not publish past `{meta.horizon_h}` h in this
> cycle. Steps beyond it are shown as gaps, never filled in.

`{...}` are substitutions from the payload. If `gaps[]` is empty but `horizon_h < 48`, the models
clause is dropped and the sentence ends at the first period. The note is part of the design, not an
afterthought: it is the only thing on the page that distinguishes *"the atmosphere ends at 24 h"*
from *"our step grid does"*.

#### Cell size, and the wrap-vs-scroll rule at 1440×900

- **Cell minimum width: `108px`** (`--strip-cell-min`). Below that, the mono `blend_f` value at
  18 px and the four member marks stop being legible side by side.
- **Cell minimum height: `104px`.** Content sets the real height.
- **Column gap: `var(--s-2)` (8 px).**

At 1440×900 the strip shares the row with the trust panel (§1.5). Budget: 1440 − 2 × `--s-8` page
padding (64) − 380 px trust panel − `--s-6` column gap (24) ≈ **972 px** for the strip column.

```
cols = clamp(4, floor((972 + 8) / (108 + 8)), 8)  →  8
```

**The strip wraps; it does not scroll.** Eight cells per row at 1440×900, so a 16-cell strip is two
rows of eight and **the row break coincides with the fitted-range boundary** — row 1 is the fitted
range, row 2 is entirely extrapolated. That coincidence is a gift, not a mechanism: the column count
is computed, and the boundary treatment below is specified to be correct whether or not it lands on
a row edge. Where the arithmetic allows more than one column count inside the `[4, 8]` clamp, F5
**prefers the count that puts the boundary on a row edge.**

Horizontal scrolling is the fallback only below the 4-column floor (a viewport far narrower than the
target). In that fallback the container gets `overflow-x: auto` and **the unverified state must
remain visible at every scroll position** — which it does, because the extrapolated treatment lives
on every cell (below) and not only on the rule between them.

#### The 24 h fitted-range boundary — a hard visual break, not a tick

Between the last fitted cell (`lead_h` 24) and the first extrapolated cell (`lead_h` 27) the page
draws **three things, all of them, always**:

1. **A rule.** 2 px, `var(--warn)`. Full width of the strip when the boundary falls on a row edge
   (`.strip-boundary`); a 2 px left border on the first extrapolated cell when it falls mid-row
   (`.strip-cell[data-boundary-start="true"]`). Both forms are in §2.
2. **A label on the rule,** verbatim: **`Beyond the fitted range`**. In the mid-row form the label
   rides the band bracket above the first extrapolated cell.
3. **A persistent treatment on every cell past it** — `--warn-soft` surface, `--warn` border, and an
   `UNVERIFIED` flag on the first extrapolated cell of each visual row (so any single-row crop or
   screenshot still carries the word).

**Why all three and not a tick mark:** half a 48 h strip is unverified, and a divider the eye skips
lets a viewer read a 42 h number as measured — which is exactly the claim FORECAST-SPEC §7 forbids
the page to make.

The detail panel for any extrapolated cell repeats the §7 sentence verbatim, with no number beside
it: *"No skill measurement exists beyond a 24-hour lead. These hours use the 24-hour weights and are
unverified."*

**Tone budget.** Extrapolated cells take `--warn` / `--warn-soft`. **`--danger` (pink `#de0f80`) is
not spent here** — it belongs to the synthetic banner (§1.8) and to a non-positive improvement
(§4), and to nothing else. An extrapolated lead is not an error; it is an honest limit, and it must
not shout as loudly as a fixture masquerading as a forecast.

#### Weight-band shading

Three bands, read directly off `weights_fitted_at_lead_h`. Two encodings, deliberately independent,
because a cell can be in the 24 h band and still be verified (cells 7–8) or unverified (cells 9–16):

| `weights_fitted_at_lead_h` | Cell surface | Bracket label above the run |
|---|---|---|
| `6` | `var(--bg-elev)` | `Weights fitted at 6 h` |
| `12` | `var(--bg-subtle)` | `Weights fitted at 12 h` |
| `24` | `var(--bg-sunken)` | `Weights fitted at 24 h` |

The three surfaces are a neutral ordinal ladder — the further the step is from the lead its weights
were fitted at, the more recessed its surface. **Model colours are never used for a band**; the
bands are not models, and `var(--model-*)` on cell chrome would collide with the member marks that
do carry model identity (§1.4). The extrapolated surface (`--warn-soft`) is declared after the band
rules and wins the cascade, so an unverified cell reads as unverified first and 24 h-banded second.

Above each run of same-band cells sits a **bracket**: a hairline `--border-strong` top rule spanning
the run, with the label from the table. When the strip wraps, brackets are drawn **per visual row**,
so a run split across a wrap produces two brackets with the same label — correct, and better than a
bracket that appears to skip a line break. In example A the brackets are `6 h`(3) · `12 h`(3) ·
`24 h`(2) on row 1, and a single `24 h`(8) on row 2.

Reproduced here so the mapping is inspectable at a glance, verified against FORECAST-SPEC §7:

| Cell | 1–3 | 4–6 | 7–8 | 9–16 |
|---|---|---|---|---|
| `lead_h` | 3, 6, 9 | 12, 15, 18 | 21, 24 | 27, 30, 33, 36, 39, 42, 45, 48 |
| `weights_fitted_at_lead_h` | 6 | 12 | 24 | 24 |
| `is_extrapolated_lead` | false | false | false | **true** |

#### How a cell reveals its detail — and the keyboard rule

**Every cell is a real `<button type="button">`, and the detail is an adjacent persistent panel
(`.strip-detail`) below the strip — not a hover tooltip.** Three reasons, in order of weight:

1. **Keyboard reachable, by construction.** A native button is in the tab order without a
   `tabindex` and takes Enter/Space for free. Hover-only detail is unreachable by keyboard and by
   touch. This is a requirement, not a preference.
2. A four-row weights table plus four member values plus the extrapolated sentence does not fit
   legibly in a tooltip at 12.5 px.
3. A persistent panel is present in a screenshot. A tooltip is not, and the demo is screenshotted.

Behaviour: `focusin` on a cell updates the panel, so Tab or arrow traversal live-updates it;
Enter/Space **pins** the selection (`aria-pressed="true"`). Hover raises the cell (`--shadow-2`) as
affordance only and **does not** change the panel — a pointer sweeping the strip must not strobe it.
`:focus-visible` draws the 3 px `var(--ring)` per token doc §5.8. The pinned state is drawn with a
border and ring only and **never repaints the cell surface**, because the surface is carrying the
band and the unverified state.

Panel contents, in order: `valid_time` (as `Thu 4 Sep · 18:00Z`) · `lead_h` · `blend_f` in °F ·
the four-row weights table (model dot, name, weight to one decimal, mono tabular) ·
`Weights fitted at a {weights_fitted_at_lead_h}-hour lead` · the four `members` values ·
`Model spread {member_spread_f} °F (max − min across 4 models)` · and, for an extrapolated cell,
the §7 sentence verbatim. The strip carries `aria-label="Forward forecast, {n_steps} steps"`; each
cell's accessible name states its lead, its value, and — when extrapolated — the word *unverified*,
so the boundary exists for a screen reader too and not only in pixels.

The cell for the nearest forward step is marked `data-current="true"` and carries an `--accent`
border; it is the same step the headline number shows (§1.1).

---

### 1.3 The gap cell

A `valid_time` that appears in `gaps[]` renders as a cell that is **visibly absent** — not an empty
slot, not a blank, not a shorter strip. It states, on its face, `missing_models` and `reason`.

**Anatomy** (`.strip-cell.is-gap`, CSS in §2):

- `lead_h` and `valid_time` render exactly as on a normal cell — the step is real; the data is not.
- Where `blend_f` would be, an em dash `—` in `var(--text-subtle)`, mono. **No number.**
- `missing_models` as small chips, each with a `var(--model-*)` dot from §0.1, so *which* model is
  missing is readable without opening the panel.
- `reason` verbatim from the payload, `var(--font-mono)` 10 px, `--text-muted`. Never paraphrased,
  never prettified — e.g. `beyond model horizon`.
- No member marks, no spread. There is nothing to draw.
- Still a focusable `<button>`, and the panel shows `valid_time`, `lead_h`, `missing_models` and
  `reason` verbatim. Consistency of the keyboard traversal matters more than saving a tab stop.

**The three nevers.** Stated here in words because the CSS cannot enforce them (FORECAST-SPEC §5.3,
§15):

> A gap is **never interpolated across** — the page does not draw a value between its neighbours.
> A gap is **never back-filled** from an earlier cycle, a neighbouring step, or a fallback model.
> A gap is **never renormalized over the remaining models.**

The third is the one that will be proposed as a fix, so it earns its own sentence: **a three-model
renormalization is a different blend than the one that was fitted, and the skill numbers on this
page do not apply to it.** Every MAE and every `improvement_pct` in §4 was measured on a four-model
vector. Dropping NAM and rescaling the other three to sum to 1.0 produces a number with no backtest
behind it, displayed under a trust panel that appears to vouch for it. A gap is honest; a
substituted blend is not.

**Distinct from extrapolated, at a glance.** These are different failures and must not share a
visual language — a viewer who has learned "orange dashes mean roughly-fine" will read a gap as a
soft warning rather than as absent data:

| | Extrapolated cell (§1.2) | Gap cell (§1.3) |
|---|---|---|
| What it means | We have a number; nothing measured it | We do not have a number |
| Surface | `--warn-soft`, filled | Unfilled: `--bg` under a hatched `--border` diagonal |
| Border | **Solid** 1 px `var(--warn)` | **Dashed** 1 px `var(--border-strong)` |
| Elevation | `--shadow-1`, sits on the page | `box-shadow: none`, sits *in* the page |
| Value | The real `blend_f` | `—` |
| Tone | `--warn` (orange) | Neutral grey — no tone colour at all |
| Flag | `UNVERIFIED` | The `missing_models` chips and `reason` |

Dashed borders and the hatch belong to **absence only**, page-wide. Nothing else on the forecast
page may use them.

---

### 1.4 Members, model spread, and the zero-weight model

`members` (each model's own forecast at that step) and the derived `member_spread_f` (max − min) are
allowed by FORECAST-SPEC §6.3 because **they are facts about the four models, and not a claim about
how likely any temperature is.** The allowed form only, and nothing else.

**The form: four discrete member marks on a shared scale.** A 14 px-tall strip at the foot of each
cell (`.strip-members`, CSS in §2): a hairline axis with **four dots**, one per model in
`meta.models_included`, each filled with its `var(--model-*)` colour from §0.1. Equivalent and
acceptable: the same four points drawn as a small 4-point sparkline. Nothing else.

**The scale is shared across the whole strip, and it is a spread scale.** The axis domain is
`0 … max(member_spread_f)` over every cell in the payload (F5 sets it once as `--spread-domain` on
the strip container); each mark sits at `(members[m] − min(members)) / --spread-domain`,
left-anchored. So a step where the models agree shows four dots stacked at the left, and a step
where they disagree shows them fanned — **and the two cells are comparable to each other**, which a
per-cell normalization would destroy by making every cell look equally spread.

**The two §6.3 restrictions, restated inline because this is where they get broken:**

1. **Never drawn as an error bar around the blend value.** Not as a bar, not as a bracket, not as
   any geometry attached to `blend_f`. The member strip is a separate row with its own axis, below
   the value and visually detached from it. Concretely: **`blend_f` is never plotted on the member
   scale.** The moment the blend appears on that axis, the four marks become a range around it, and
   that is the band/whisker geometry §0.3 bans — via a different route, but the same claim.
2. **Never converted into a percentage.** `member_spread_f` renders as degrees F, to two decimals,
   mono tabular, labelled `Model spread`. Disagreement is not calibrated skill and the page must not
   imply that it is.

Neither is a band, ribbon, shaded envelope or whisker: no region between the marks is filled, and
nothing is drawn around the blend number.

**The zero-weight model — GFS.** GFS carries weight `0.0` at all three fitted leads (§4's table) and
is nonetheless a required `members` key (§9 rule 7).

> **The GFS member mark is shown on every cell, its weight renders as `0.0` in the detail panel, it
> is visually de-emphasised — a hollow ring in `var(--model-gfs)` at 55 % opacity rather than a
> filled dot, and its weights row is set in `--text-subtle` — and it is never dropped.**

Dropping it would misrepresent the §9 contract (which requires all four keys) and would hide a real
result: the backtest looked at GFS and gave it nothing, at every lead. That is a finding, and the
page shows findings. It is also the one thing on the strip that proves the weights were *fitted*
rather than assumed.

**The de-emphasis is computed, never hardcoded.** The rule is `weights[model] === 0`, applied per
cell to whatever model it matches. GFS is today's zero; a refit could move it, and a page with
`GFS` written into a CSS selector would then lie in two directions at once. The hollow-ring
treatment is `.strip-mark[data-zero-weight="true"]`, and F5 sets that attribute from the data.

---

### 1.5 Trust panel — layout and the weights-staleness note

Destination: `frontend/forecast.{html,css,js}`, written by **F5**, populated by **F7**.
Governing clauses: FORECAST-SPEC §6, §6.1, §7, §7.1, §15; this document's §0.3, §4 and §6.

**Read §0.3 before implementing this region.** The trust panel is the one place on the page where
a well-meant "improvement" will try to turn a past MAE into a statement about tomorrow. It does not
become one. The panel answers exactly one question — *how did this blend do at this site, at this
lead, over the scored window* — in the past tense, and stops there.

**Preamble on literals.** Clarity publishes no font-size tokens (§0 rules), so every `px` size below
is a per-component literal, chosen to sit on Clarity's own steps (11.5 / 12 / 12.5 / 13 / 14 px).
Colour, spacing, radius, shadow and density are all tokens.

**Container.** One content card, `.skill-panel`, built on the `.card` / `.card-header` /
`.card-title` / `.card-sub` / `.card-body` idiom **re-authored into `forecast.css`** — `app.css` is
not linkable and `vendor/clarity-tokens.css` carries no class rules, so `forecast.css` restates these
component classes from the token doc. That duplication is deliberate and is enumerated in **§7**;
it is not restated here.

- `.skill-panel` — `background:var(--bg-elev); border:1px solid var(--border);
  border-radius:var(--r-xl); box-shadow:var(--shadow-1)`.
- `.card-header` — `padding:16px 20px; border-bottom:1px solid var(--border)`.
  `.card-title` 14px/600 `--text`: **`How this blend has performed here`**.
  `.card-sub` 12.5px `--text-muted`: the window and split, e.g.
  `2026-08-04 → 2026-09-04 UTC · 30 days · fitted on the first 20, scored on the last 10`.
- Body padding `var(--s-5)` (20px). No chart, no axis, no series in this panel.

**One block per fitted lead.** Three `.skill-lead` blocks — 6 h, 12 h, 24 h — stacked in that order,
each separated by `border-bottom:1px solid var(--border)` (none on the last), vertical padding
`var(--s-5)`. The order is fixed and is **never sorted by any metric**; sorting by MAE would let the
page rearrange itself into a flattering order, which is the §15 tuning ban in another costume.

Each block, top to bottom:

1. `.skill-lead-head` — `display:flex; align-items:baseline; gap:var(--s-3)`.
   - Lead badge, the `.badge-pill` idiom re-authored per §7: `--bg-subtle` surface, `--border`
     hairline, `--r-full`, `--font-ui` 11.5px/500 `--text-muted`, copy `6-hour lead` / `12-hour lead`
     / `24-hour lead`. One piece of state per pill, per the token doc's badge rule.
   - `.skill-improve`, pushed right (`margin-left:auto`), `.num` mono 13px tabular. Its tone token
     and its copy template follow **`.claude/features/demo-shell/design-target.md` §3, "The three
     improvement states (D4)"** — read that table there; it is **not** restated here, and F7 must not
     re-derive it. All three leads currently land in its first state, which is a fact about the data
     and not a licence to hardcode the tone.
2. `.skill-copy` — the verbatim past-tense sentence for that lead from **§4**. `--font-ui` 13px,
   `line-height:1.5`, `--text`, `max-width:68ch`. This is the load-bearing element of the panel; the
   numeric row below it is a restatement for scanning, not a substitute for it.
3. `.skill-nums` — a five-cell grid, labels above values.
   Labels `--font-ui` 11.5px/500, `text-transform:uppercase`, `letter-spacing:.05em`,
   `--text-subtle`. Values use the shipped `.num` / `.mono-value` idiom
   (`frontend/tokens.css:209-214`, §0.2): `--font-mono`, `font-variant-numeric:tabular-nums`,
   `text-align:right`. Signed values follow §6.

   | Cell | Source field | Treatment |
   |---|---|---|
   | `BLEND MAE (OUT-OF-SAMPLE)` | `skill.by_lead[].blend_mae` | headline, mono **14px**, `--text` |
   | `IN-SAMPLE (FITTED DAYS)` | `skill.by_lead[].blend_mae_in_sample` | mono 12.5px, `--text-muted`, **label never omitted** |
   | `BEST SINGLE (HRRR)` | `best_single_model` + `best_single_mae` | mono 12.5px, `--text`, model name from the field, never hardcoded |
   | `IMPROVEMENT` | `improvement_pct` | mono 12.5px, tone per T3 §3 |
   | `SAMPLE` | `n_test` + `independent_days_approx` | mono 12.5px `--text-muted`, rendered `40 test rows · ~30 independent days` |

   The out-of-sample cell is always first and always the larger type. The in-sample cell is always
   second and always carries its label. **Their positions are fixed in the DOM and are never reordered
   by magnitude** — that is what makes the 12 h case (§4) unmisreadable: whichever number is smaller,
   the reader can still see at a glance which is which.
4. `.skill-weights` — the fitted weight vector actually used at that lead, four chips in canonical
   order HRRR · GFS · NAM · NBM. Each chip: an 8px dot at `var(--model-hrrr)` etc. (§0.1, consumed,
   never redeclared), label `--font-ui` 12.5px/500 `--text`, weight `.num` mono 12.5px.
   **GFS renders as `0.0` at all three leads and is never dropped** — see §1.4 for the zero-weight
   treatment, which this panel reuses rather than inventing a second one.
5. `.skill-basis` (panel footer, once, below all three blocks, always visible — never collapsed
   behind a disclosure): `--font-ui` 12.5px `--text-muted`, carrying `skill.basis`, `skill.note`, and
   the sample-size reason in one sentence: *Four initialisations a day over 30 days share a weather
   regime, so the ~120 forecast-observation pairs at each lead are closer to ~30 independent days.*

**The extrapolated block, and the two-way cross-link with the strip.**

Directly beneath the three lead blocks, inside the same card, sits `.skill-extrapolated`, carrying
**`id="skill-beyond-fitted"`** and the verbatim sentence in §4. Treatment: 3px `border-left` in
`--warn`, background `--warn-soft`, padding `var(--s-3) var(--s-4)`, `--font-ui` 13px `--text`.
`--warn`, never `--danger` — extrapolation past the fitted range is a caution, not a failure, and
`--danger`'s pink is already spent on the synthetic banner and on a non-positive improvement (§0.1).
Never `--success`.

The cross-link is specified in **both** directions, because a viewer reading a 42 h cell must reach
this statement without hunting for it:

- **Strip → panel.** Every strip cell with `is_extrapolated_lead: true` — the post-boundary region
  specified in **§1.2**, whose cell classes and geometry are §1.2's and §2's to define, not this
  section's — carries `aria-describedby="skill-beyond-fitted"` and is activatable (click, and
  `Enter`/`Space` on focus) to scroll that block into view and flash its `--warn` border. The hover
  and focus affordance on such a cell states the same sentence.
- **Panel → strip.** `.skill-extrapolated` names the region back in words: *the shaded cells from a
  27-hour lead onward on the strip above*, with the phrasing parameterised on the real boundary
  (§1.2's banding is driven by `meta.horizon_h` / `meta.step_h`, not by a hardcoded cell count).

**Weights staleness (FORECAST-SPEC §7.1).** A `.skill-weights-age` block closes the card, below
`.skill-extrapolated`. `--font-ui` 12.5px, `--text-muted`, numeric values in `.num` mono.
It shows, from `meta.weights_source`:

| Shown | Field | Rendered |
|---|---|---|
| Fitted window | `window` | `2026-08-04T12:00:00Z → 2026-09-04T00:00:00Z` — the real dates, always visible |
| Split | `split` | `20 train days / 10 test days · 80 train rows / 40 test rows per lead` |
| Fitted at | `generated_at` | `2026-09-04T12:53:01Z` |
| Age | `weights_age_days` | mono, in days, e.g. `0 days` |
| Fitted leads | `fitted_leads` | `6, 12, 24` |
| Source | `path` | mono 12.5px `--text-subtle` — it is a path, not prose |

And, in the customer's language, always present regardless of age:

> **Weights fitted on 30 days of August do not necessarily hold in December.** These weights were
> fitted on `2026-08-04` → `2026-09-04`. The atmosphere's regime changes; a blend tuned on summer
> convection has no claim on winter inversions, and KOMA has both.

**Past 45 days** (`weights_age_days > 45`) the block gains a visible note, same `--warn` /
`--warn-soft` treatment as `.skill-extrapolated`, naming the age and the window it was fitted on.
Below that threshold the block is plain muted metadata: **there is no green "fresh" badge and no
`--success` tone anywhere in this panel** — freshness is not an achievement to celebrate, and green
here would read as an endorsement of numbers whose shelf life nobody has measured.

**v1 does not refit, does not schedule a refit, and does not pretend to know the right interval.**
Refit cadence is FORECAST-SPEC §22, deferred to v2 deliberately. The panel says that in one line
rather than implying a cadence exists.

**What this panel must never render** (§0.3, restated here because this is the region that would
tempt it): nothing in the trust panel is drawn as a band, a ribbon, a shaded envelope or a whisker,
and no plus-or-minus figure is ever attached to a forecast value. Past MAE is a number in a table
cell and a clause in a past-tense sentence — it never becomes geometry around `blend_f`, on this
panel or anywhere else. If F7 adds the realized-error strip from F6, it renders as discrete
per-day marks, never as a shaded region and never attached to a forward value. Model spread
(`member_spread_f`) belongs to §1.4 and stays there; it is not repeated in this panel.

---

### 1.6 The back-arrow control and the past-day view

Destination: the history view, written by **F6**. Governing clauses: FORECAST-SPEC §10, §15, §6.

The framing of the whole region, and its section heading copy: **`Here is what we said. Here is what
happened.`** — `--font-ui` 14px/600 `--text`. Nothing in this view is a forecast; every number in it
has already been settled by an observation.

**The day stepper.** The back-arrow uses the **sunken-track / raised-pill segmented control** idiom
from the token doc §5.3 — the same idiom `frontend/index.html:28` already uses for its lead toggle
(`<div class="segmented" id="lead-toggle" role="group">`, active state expressed as
`aria-pressed="true"`, styled in `frontend/app.css:52-75`). **Read that markup; never edit it.**
`forecast.css` re-authors the class per §7 rather than linking `app.css`.

- `.day-stepper` — `display:inline-flex; align-items:center; padding:2px;
  background:var(--bg-subtle); border:1px solid var(--border); border-radius:var(--r-md)`.
- Three children: a previous-day button, the current date, a next-day button.
  Buttons `height:28px; padding:0 var(--s-3); background:none; border:none; border-radius:6px;
  color:var(--text-muted); font-family:var(--font-ui); font-size:12.5px; font-weight:500`.
  The arrow glyphs are `‹` and `›`, each with a real `aria-label` (`Previous day` / `Next day`) —
  the glyph is never the accessible name.
- The date sits between them as the raised pill: `background:var(--bg-elev); color:var(--text);
  box-shadow:var(--shadow-1)`, date in `--font-mono` 12.5px tabular, ISO `2026-09-02`.
- At either end of the window the corresponding button is `--text-subtle`, `cursor:not-allowed`,
  `aria-disabled="true"`. It is dimmed, not removed — a control that vanishes is a control the
  viewer thinks they broke.
- Focus: the 3px `box-shadow: 0 0 0 3px var(--ring)` convention (token doc §5.4, §5.8).

**Per past day.** One `.card` (re-authored per §7) whose `.card-header` carries the date and the
day's `mae_f` per lead in `.num` mono, and whose body is a `.tbl` (re-authored per §7) with **one
row per entry, at leads 6, 12 and 24 only**:

| Column | Field | Treatment |
|---|---|---|
| `LEAD` | `lead_h` | `.badge-pill`, `6 h` / `12 h` / `24 h` |
| `INIT (UTC)` | `init_time` | mono 12.5px `--text-muted` |
| `VALID (UTC)` | `valid_time` | mono 12.5px `--text-muted` |
| `WE SAID` | `blend_f` | mono 13px `--text`, 2 dp, `°F` |
| `OBSERVED` | `observed_f` | mono 13px `--text`, 2 dp, `°F` |
| `ERROR` | `error_f` | mono 13px, signed, **with the sign labelled** — see below |
| `BEST SINGLE` | `best_single_model_f` | mono 12.5px `--text-muted` |
| `OBS OFFSET` | `obs_offset_min` | mono 12.5px `--text-subtle`, signed, in minutes |

`members` for a row is available on row expansion and follows §1.4's member treatment; it is not a
default column, and it never renders as a band, ribbon, shaded envelope or whisker, here or anywhere.

**The signed error, and labelling the sign.** `error_f` is `blend_f − observed_f`, per §10. It is
rendered with a real minus **U+2212 `−`** on negatives and an explicit `+` on positives, per §6 —
**never `Math.abs`, never clamped, never split into a magnitude column and a direction icon**. The
sign carries a word beside it, in `--font-ui` 12.5px `--text-muted`, because a bare `−0.80` does not
tell a grower anything:

- `error_f > 0` → `+1.24 °F  warm` — *we forecast warmer than it turned out.*
- `error_f < 0` → `−0.80 °F  cold` — *we forecast colder than it turned out.*
- `error_f == 0` → `0.00 °F  exact`.

A warm bias must read as a warm bias. The word is never dropped, never abbreviated to an arrow, and
never truncated at narrow widths. Tone stays neutral `--text` in all three cases: a warm bias is a
finding, not an error state, so it takes neither `--danger` nor `--success`. The day's `mae_f` is
unsigned by construction and is labelled as a mean absolute error so it is not read as a bias.

**The observation offset.** METAR is not on the hour — `OMA` reports near `:53` — so every row
records how far the matched observation sat from the valid time. The join is **a 30-minute
nearest-observation window**, the same one the backtest used (SPEC §4, spike F5). The mean absolute
offset over the scored window is **7.92 minutes**, shown once under the table in
`.card-sub` type: *Observations are matched within a 30-minute nearest-observation window; METAR at
`OMA` reports near `:53`, and the mean absolute offset over this window was 7.92 minutes.*

**Why three leads — stated on the page, verbatim.** This copy appears directly under the day
stepper, `--font-ui` 12.5px `--text-muted`, and is not collapsible:

> The past view shows three leads because three leads is what the archive was fetched at — it is
> **not a downsample** of the forward view. The forward strip is 3-hourly; the archive is 6, 12 and
> 24 hours. A 3-hourly past curve means refetching the archive at every step, and that is v2.

That is FORECAST-SPEC §10's rule and §22's deferral, said once, where the viewer would otherwise
assume the past view is the forward view with rows removed.

**Observations are never interpolated. A missing observation drops the row.** There is no fill, no
carry-forward, no nearest-hour substitution and no averaging across the gap. A dropped row is simply
absent from the day's table, and the day's `mae_f` is computed only over the rows that matched.

**A day with zero matched entries is absent from the view, with the reason shown.** It is not a step
in the stepper, and it is never rendered as a day with a perfect score — FORECAST-SPEC §15: *an empty
join scores perfectly and is fake*. Omitted dates are listed once, below the day card, in the
`.empty-state` voice (token doc §5.10 — centre, hint the next action, never apologize):

> `2026-08-17` is not shown: no forecast-observation pair matched within the join window.

The reason string comes from the payload's recorded reason, rendered as data in `--font-mono` 12.5px
`--text-subtle` beneath the human sentence, exactly as T3 §1.9 handles the 503 body. Where a day
matched at some leads and not others, the day is present and the unmatched rows are absent; the
table's row count is therefore data, and F6 asserts on it rather than assuming three rows.

**Nothing in this view renders as a band, ribbon, shaded envelope or whisker, and no plus-or-minus
figure is attached to any value.** Every number here is a settled past observation or a settled past
error, and it is presented as one.

---

### 1.7 Stale treatment

`meta.cycle.is_stale` is `true` **iff** `meta.cycle.cycles_fallen_back > 0` **or**
`meta.cycle.age_minutes > 540` (§9 rule 11 — 540 minutes is the 9 h threshold of §5.2). When it is
true, `stale_reason` is non-null; when it is false, `stale_reason` is `null`. The page never
computes staleness itself — it reads the boolean.

The stale treatment is **in addition to** the always-present run label of §1.1, never a replacement
for it. Two elements, both inside the headline stat card, both directly under the run label:

1. **The pill** — the Clarity `.badge-pill` idiom (token doc §5.7), `--warn` tone: tint background
   `--warn-soft`, `--orange-700` text, and a `--orange-500`-at-20%-alpha border. Copy:

   | Condition | Pill copy |
   |---|---|
   | `cycles_fallen_back > 0` | `Stale · <cycles_fallen_back> cycle(s) behind target` |
   | `cycles_fallen_back == 0` (so `age_minutes > 540`) | `Stale · <age_minutes ÷ 60, floored> h old` |

   `cycles_fallen_back` is always rendered when it is non-zero — it is the difference between
   `meta.cycle.target_init_time` (what we wanted) and `meta.cycle.init_time` (what we served), and a
   viewer cannot infer it from the run label alone.

2. **The reason line** — `meta.cycle.stale_reason` **verbatim**, never paraphrased, never truncated,
   never wrapped in friendlier words. It is server-authored text, so it is typeset as technical
   detail in `--font-mono` 12.5px `--text-muted`, the same idiom the 503 detail uses (§1.9).
   Example, from the §9 contract: `fell back 1 cycle: HRRR f021 absent from archive`.

**Tone budget.** Stale is `--warn` (`#ff922b`). **Never `--danger`** — the pink is spent on the
synthetic banner and on a non-positive improvement, and on nothing else (§0.1). A stale cycle is a
real forecast from an older run, not fabricated data, and the two must not look alike. Equally,
never `--success` green for a fresh cycle: freshness is the ordinary case and the ordinary case is
untinted.

Visibility is attribute-gated on `html[data-stale="true"]` — markup always present, never a JS
`display` toggle. See §3 for the rule, the state table and the literal CSS.

---

### 1.8 Synthetic banner

Gated on the **single boolean** `meta.is_synthetic`, exactly as the demo page already does it:

- `<html data-synthetic="true">` set by JS from that one boolean, and from nothing else.
- A `[SYNTHETIC]` prefix prepended to `document.title`.
- The banner markup is unconditional in `forecast.html` — the first child of `<body>`, before the
  page shell — and its visibility is CSS keyed on the attribute.

**Reuse the existing CSS verbatim.** The `html[data-synthetic="true"]` inset frame and the
`.synthetic-banner` rules are already shipped in **linkable** `frontend/tokens.css:19-47`, which is
on FORECAST-SPEC §3's permitted-link list. `forecast.css` **must not restate or re-author them** —
this is the one state block the forecast page gets for free, and a second copy is how the two pages
drift. See §0.2, where the block is catalogued. `frontend/app.js:56-64` is the wiring pattern F5
repeats.

Banner copy (verbatim, `<generated_at>` substituted from `meta.generated_at`):

```
SYNTHETIC FORECAST DATA — these numbers are fabricated. Not a real NOAA cycle. Generated <generated_at>.
```

No close affordance — no button, no dismiss icon, ever. The tokens.css comment says so and the rule
carries over unchanged.

`--danger` pink (`#de0f80`) is spent here and on a non-positive improvement, and on nothing else.
Stale (§1.7) and extrapolated leads (§1.2) take `--warn`.

**The run label stays.** A synthetic payload still carries a `meta.cycle`, so §1.1's label renders
normally beneath the banner. The banner says the numbers are fabricated; the label says which
fabricated cycle they claim to be. Both are true and both are shown.

> **§9 rule 9 — the string `"true"` is not a boolean.** `is_synthetic: "true"` is a non-empty string,
> which is truthy in JS but fails the contract's boolean check; the reverse trap, `is_synthetic:
> "false"`, is *also* truthy and would raise a banner over real data, while a payload that reached
> the page with the check skipped could just as easily hide one over fabricated data. `forecast/contract.py`
> rejects a non-boolean before it can reach the page, and F5's JS must branch on the boolean
> directly (`if (!meta.is_synthetic) return;`) rather than on a string comparison.

---

### 1.9 Empty state (503)

When `GET /api/forecast` returns **503** (no cache, or a contract path that failed — §11), the page
hides the shell and renders one centred `.card.empty-state`. `frontend/app.js`'s `renderEmptyState`
(around `frontend/app.js:487-509`) is the exact pattern F5 repeats, with the copy and the CLI
swapped for this page's.

Structure — **icon → title → one human sentence → the server's reason** (token doc §5.10:
*"Center content, hint the next action, never apologize. Icon → title → one sentence → action."*):

| Part | Class | Spec | Copy |
|---|---|---|---|
| Icon | `.empty-icon` | 28px, `line-height:1`, `margin-bottom:var(--s-4)` | `◍` |
| Title | `.empty-title` | `--font-ui`, 15px / 600, `--text` | `No forecast cache. Fetch a cycle.` |
| Sentence | `.empty-body` | `--font-ui`, 13px / 400, `--text-muted` | `Run: uv run python -m forecast.refresh` |
| Detail | `.empty-detail` | `--font-mono`, 12.5px, `--text-subtle`, `word-break:break-word` | **the server's 503 reason, verbatim** |

Container: `.card` chrome (`--bg-elev`, `--border`, `--r-xl`, `--shadow-1`), `max-width:620px`,
`margin:var(--s-16) auto`, `text-align:center`, `padding:var(--s-12) var(--s-8)`.

**The server's reason is shown verbatim, in mono, visually distinct from the human sentence.** It is
data, not prose: it is not rewritten, not shortened, not prefixed with "Error:", and not merged into
the sentence above it. The mono face and `--text-subtle` are what mark it as machine output, so a
viewer can paste it into a bug report and a developer can grep for it.

**Never blank-but-styled.** A 503 must never produce a page with an empty forward strip, a headline
reading `—`, or a skeleton that never resolves. Either the payload rendered, or this card is on
screen naming what went wrong. Rendering an empty-but-well-formed page is the exact failure shape
FORECAST-SPEC §11 forbids on the server side, and the client must not reintroduce it.

**Never apologize** (token doc §6): no "Sorry", no "Oops", no exclamation mark, no emoji. The title
is a direct statement plus a direct verb. **Name the CLI that fixes it** — `uv run python -m
forecast.refresh` — because there is no refetch endpoint by design (§11: no POST, no write, no
refetch route), so the next action is a command, not a button. No retry button is specified; a
button that cannot fetch is worse than no button.

**The run label, where a cycle is known.** If a cycle is known despite the 503 — a stale cache whose
contract validation failed, say, where the reason names the init time — §1.1's run label renders
above the empty-state card in its usual `.stat-meta` form. If nothing is known, it is **omitted
entirely**; the page never renders `Run — · — old`, and never guesses a cycle from the wall clock.
A faked run label is worse than no run label.

**Re-author note.** `.empty-state`, `.empty-icon`, `.empty-title`, `.empty-body` and `.empty-detail`
— along with the `.card` chrome they sit in — must be **re-authored in `frontend/forecast.css`**
from the token doc. They currently live in `frontend/app.css`, which is **not** on FORECAST-SPEC
§3's permitted-link list; `forecast.html` may not link it, and copying its file would put the demo
page's stylesheet on the forecast page's load path. **§7 carries the full re-author list** — see it
rather than deriving the list here.

---

---

## 2. Literal CSS — Clarity gap #3: the forecast strip

The one genuinely new component. Destination: `frontend/forecast.css`, written by **F5**.

The one genuinely new component. Destination: **`frontend/forecast.css`, written by F5. F1 does not
create that file.**

**Preamble.** Clarity has **no timeline, no strip and no per-step-cell component of any kind**
(token doc §8, FORECAST-SPEC §17), and it has **no font-size tokens** (token doc §2.3 — *"sizes are
hard-coded per component"*). Every size, weight, tracking and geometry literal below is therefore a
**per-component literal**, exactly as T3's two gap blocks are. Colour, spacing, radius, shadow and
font-family are **semantic tokens only**; every `var(--…)` here exists in
`clarity-design-tokens.md`, except the four `--model-*` properties, which are consumed from the
linked `frontend/tokens.css` per §0.1 and are **never redeclared**.

Two deliberate deviations, both stated rather than hidden:

- **The `UNVERIFIED` flag inverts the badge idiom.** Token doc §5.7's pill is *tint background /
  700-text / 20 %-alpha border*, whose text colour is a raw scale value. To stay semantic-only and
  keep the label readable, the flag puts the tone on a `.badge-pill .dot-mini`-style dot and the
  1 px border (`var(--warn)`) and leaves the text at `var(--text)`.
- **T3's `--slider-fill` / `--slider-pct` precedent** is followed for the per-instance properties
  F5 sets from JS: `--strip-cols`, `--band-span`, `--mark-pos`, `--mark-color`, `--spread-domain`.
  They are wiring, not design tokens, and each has a fallback.

Not restated here, per §0.2: the range-slider block, the chart/axis block, the synthetic-banner CSS
and `.num` / `.mono-value` — all already shipped in linkable `frontend/tokens.css`. The component
classes `forecast.css` must **re-author** from the token doc (`.card`, `.tbl`, `.badge-pill`,
`.stat-*`, `.empty-state`, the page shell) are listed in §7, not here.

```css
/* ── Forecast strip — Clarity gap #3 (Clarity has no timeline, strip or
   per-step-cell component of any kind) ──────────────────────────────────────
   Destination: frontend/forecast.css, written by F5.

   Sizes are per-component literals: Clarity tokenizes families, colour,
   spacing, radii and shadows, but no font sizes and no timeline geometry.
   Colour/space/radius/shadow/family below are semantic tokens only.
   --model-* comes from the linked tokens.css and is never redeclared here.

   Set from JS by F5, per instance (T3's --slider-fill precedent):
     --strip-cols      integer, column count per row (see the design doc §1.2)
     --band-span       integer, cells a band bracket spans
     --mark-pos        0-1, a member mark's position on the shared spread axis
     --mark-color      that member's var(--model-*)
     --spread-domain   informational; the axis domain in degF, for the label */

.forecast-strip {
  --strip-cell-min: 108px;
  --strip-cols: 8;
  --strip-gap: var(--s-2);          /* 8px */
  display: flex;
  flex-direction: column;
  gap: var(--s-3);                  /* 12px between visual rows */
  margin: 0;
  padding: 0;
}

/* One visual row: a band-bracket track above a cell track, sharing columns. */
.strip-row {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
}

.strip-bands,
.strip-cells {
  display: grid;
  grid-template-columns:
    repeat(var(--strip-cols), minmax(var(--strip-cell-min), 1fr));
  gap: var(--strip-gap);
}

/* Fallback only, below the 4-column floor. Never reached at 1440x900.
   The per-cell extrapolated treatment is what keeps the fitted-range
   boundary legible at every scroll position here. */
.forecast-strip[data-overflow="scroll"] .strip-row { overflow-x: auto; }
.forecast-strip[data-overflow="scroll"] .strip-bands,
.forecast-strip[data-overflow="scroll"] .strip-cells {
  grid-template-columns: none;
  grid-auto-flow: column;
  grid-auto-columns: var(--strip-cell-min);
  width: max-content;
}

/* ── Band bracket ── one per run of equal weights_fitted_at_lead_h, per row. */
.strip-band {
  grid-column: span var(--band-span, 1);
  border-top: 1px solid var(--border-strong);
  padding-top: var(--s-1);
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--text-subtle);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Cell ── a real <button type="button">: tab order and Enter/Space for free. */
.strip-cell {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: var(--strip-cell-min);
  min-height: 104px;
  padding: var(--s-3) var(--s-2);   /* 12px 8px */
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  font-family: var(--font-ui);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: box-shadow 0.12s, border-color 0.12s;
}

.strip-cell:hover {
  box-shadow: var(--shadow-2);
  border-color: var(--border-strong);
}

/* 3px ring at the accent hue / 22% opacity — token doc §5.8, never thicker. */
.strip-cell:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--ring);
}

/* Pinned selection: border + ring ONLY. It must never repaint the surface,
   because the surface is carrying the weight band and the unverified state. */
.strip-cell[aria-pressed="true"] {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--ring);
}

/* The nearest forward step — the same step the headline shows (§1.1). */
.strip-cell[data-current="true"] { border-color: var(--accent); }

/* ── Weight bands ── neutral ordinal ladder: further from the fitted lead,
   more recessed. Never a --model-* colour; those belong to the member marks. */
.strip-cell[data-band="6"]  { background: var(--bg-elev); }
.strip-cell[data-band="12"] { background: var(--bg-subtle); }
.strip-cell[data-band="24"] { background: var(--bg-sunken); }

/* ── Extrapolated ── declared AFTER the bands so it wins the cascade: an
   unverified cell reads as unverified first, 24h-banded second.
   --warn, never --danger: --danger is spent on synthetic and on a
   non-positive improvement, and on nothing else. */
.strip-cell[data-extrapolated="true"] {
  background: var(--warn-soft);
  border-color: var(--warn);
}

.strip-flag {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border: 1px solid var(--warn);
  border-radius: var(--r-sm);
  background: var(--bg-elev);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.strip-flag::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--r-full);
  background: var(--warn);
}

/* ── The fitted-range boundary ── form 1: the break falls on a row edge.
   A rule plus a label, drawn only when any cell is extrapolated. */
.strip-boundary {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin: var(--s-1) 0;
  font-family: var(--font-ui);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text);
}
.strip-boundary::after {
  content: "";
  flex: 1 1 auto;
  height: 2px;
  border-radius: var(--r-full);
  background: var(--warn);
}

/* Form 2: the break falls mid-row. Same weight, same colour, turned 90deg. */
.strip-cell[data-boundary-start="true"] {
  border-left: 2px solid var(--warn);
  padding-left: calc(var(--s-2) - 1px);
}
.strip-band[data-boundary-start="true"] {
  border-left: 2px solid var(--warn);
  padding-left: var(--s-2);
  color: var(--text);
}

/* ── Cell face ── lead_h, valid_time, blend_f. Every numeric temperature and
   every lead figure is mono + tabular (design doc §6). */
.strip-lead {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  color: var(--text-muted);
}

.strip-time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  color: var(--text-subtle);
}

.strip-value {
  margin-top: auto;
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  color: var(--text);
}
.strip-value .strip-unit {
  margin-left: 2px;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-muted);
}

/* ── Member marks ── four discrete marks on a shared spread axis (§1.4).
   Its own row, with its own axis, detached from .strip-value. blend_f is
   NEVER plotted here: the moment it is, the marks become a range around it. */
.strip-members {
  position: relative;
  height: 14px;
  margin-top: var(--s-1);
  border-top: 1px solid var(--border);
}
.strip-mark {
  position: absolute;
  top: 4px;
  left: calc(var(--mark-pos, 0) * 100%);
  margin-left: -3.5px;
  width: 7px;
  height: 7px;
  border-radius: var(--r-full);
  background: var(--mark-color, var(--text-subtle));
}

/* A member whose fitted weight is exactly 0.0 — GFS at every lead today.
   Shown, de-emphasised, NEVER dropped. Driven by the data, never by name. */
.strip-mark[data-zero-weight="true"] {
  background: var(--bg-elev);
  border: 1.5px solid var(--mark-color, var(--text-subtle));
  opacity: 0.55;
}

/* ── Gap cell ── absence. Unfilled and hatched, dashed, no elevation, no tone
   colour. Dashed borders and this hatch mean "absent" page-wide and are used
   for nothing else, so a gap can never be mistaken for an extrapolated cell. */
.strip-cell.is-gap {
  background:
    repeating-linear-gradient(135deg,
      var(--border) 0 1px, transparent 1px 7px),
    var(--bg);
  border: 1px dashed var(--border-strong);
  box-shadow: none;
}
.strip-cell.is-gap:hover { box-shadow: none; }
.strip-cell.is-gap .strip-value {
  color: var(--text-subtle);
  font-weight: 500;
}

.strip-missing {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-family: var(--font-ui);
  font-size: 10.5px;
  font-weight: 500;
  color: var(--text-muted);
}
.strip-missing-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 5px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg-elev);
}
.strip-missing-chip::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--r-full);
  background: var(--mark-color, var(--text-subtle));
}

/* gaps[].reason, verbatim from the payload. Never paraphrased. */
.strip-reason {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.35;
  color: var(--text-muted);
}

/* ── Truncated-horizon note ── shown whenever meta.horizon_h < 48 (§1.2). */
.strip-note {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  margin-top: var(--s-3);
  padding: var(--s-3);
  background: var(--warn-soft);
  border: 1px solid var(--warn);
  border-radius: var(--r-md);
  font-family: var(--font-ui);
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text);
}

/* ── Detail panel ── adjacent and persistent, not a tooltip: keyboard
   reachable by construction, and present in a screenshot. */
.strip-detail {
  margin-top: var(--s-4);
  padding: var(--s-5);
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-1);
}
.strip-detail-title {
  margin: 0 0 var(--s-3);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
}
.strip-detail-row {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-1) 0;
  font-family: var(--font-ui);
  font-size: 12.5px;
  color: var(--text);
}
.strip-detail-row::before {
  content: "";
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  background: var(--mark-color, var(--text-subtle));
}
.strip-detail-row .strip-detail-num {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--text);
}
/* weights[model] === 0.0 — shown at 0.0, de-emphasised, never omitted. */
.strip-detail-row[data-zero-weight="true"],
.strip-detail-row[data-zero-weight="true"] .strip-detail-num {
  color: var(--text-subtle);
}
.strip-detail-note {
  margin: var(--s-3) 0 0;
  font-family: var(--font-ui);
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text-muted);
}
/* The §7 sentence on an extrapolated cell. No number appears beside it. */
.strip-detail-note[data-tone="warn"] {
  padding-left: var(--s-3);
  border-left: 2px solid var(--warn);
  color: var(--text);
}
```

**Tokens consumed, all verified present in `clarity-design-tokens.md`:** `--s-1` `--s-2` `--s-3`
`--s-4` `--s-5` · `--r-sm` `--r-md` `--r-xl` `--r-full` · `--bg` `--bg-elev` `--bg-subtle`
`--bg-sunken` · `--border` `--border-strong` · `--text` `--text-muted` `--text-subtle` ·
`--accent` `--ring` · `--warn` `--warn-soft` · `--shadow-1` `--shadow-2` · `--font-ui`
`--font-mono` `--font-display`. Plus `--model-hrrr` / `--model-gfs` / `--model-nam` / `--model-nbm`
via `--mark-color`, consumed from `frontend/tokens.css` per §0.1. No invented token name;
`--danger` is not spent anywhere in this block. Dark-mode overrides for these rules are §5's, not
this block's.

---

## 3. State table — attribute-gated states (`data-synthetic`, `data-stale`, `data-theme`)

**The rule, in words, and it governs every state on this page:**

> **The markup is always present. Visibility is a CSS rule keyed on an attribute on the `<html>`
> element. Never a JS `display` toggle.**

JS has exactly one job per state: `setAttribute` when the condition holds, and leave the attribute
**absent** when it does not. It never writes `style.display`, never adds and removes nodes to hide
them, and never writes the string `"false"` into a state attribute — `[data-stale="true"]` does not
match `data-stale="false"`, so a "false" string produces a state that is invisible for the wrong
reason and that no selector can be written against. Absent means off.

This is not a stylistic preference. It is what makes "flip one boolean in the JSON, re-render, and
every signal appears or vanishes with zero code edits" literally true, and it is why the synthetic
banner is testable by setting one attribute in devtools. `frontend/tokens.css:19-47` is the shipped
precedent — read it; the stale block below is the same shape applied to a second state.

| Attribute on `<html>` | Source field | Set by | Visual effect | CSS lives in |
|---|---|---|---|---|
| `data-synthetic="true"` | `meta.is_synthetic` (JSON boolean; §9 rule 9) | F5's JS, from that one boolean | 3px inset `--danger` page frame · sticky `.synthetic-banner` becomes `display:flex` · `[SYNTHETIC]` prefix on `<title>` | **`frontend/tokens.css:19-47`, already shipped — reuse verbatim, do not restate** (§0.2, §1.8) |
| `data-stale="true"` | `meta.cycle.is_stale` (true iff `cycles_fallen_back > 0` or `age_minutes > 540`) | F5's JS, from that one boolean | `--warn` stale pill becomes visible · `stale_reason` line becomes visible · the permanent run label takes the `--warn` tone | **`frontend/forecast.css`, written by F5 — literal CSS below** |
| `data-theme="light"` \| `"dark"` | the viewer's stored theme (localStorage `internal-portal:theme`), applied by a pre-hydration inline script — **not** from the payload | F5's theme script, before first paint | swaps the semantic token layer | **§5, written under a separate stream — the dark layer is specified there and not here** |

Note the asymmetry, and keep it: `data-synthetic` and `data-stale` are **payload facts** and take
only the value `"true"` or are absent. `data-theme` is a **viewer preference** and carries one of
two explicit values, `light` or `dark`, because a theme has no "off". Do not specify the dark layer
from this section — **see §5**.

**Literal CSS — the stale treatment.** Clarity has no stale, no freshness and no cycle-age pattern
of any kind, so this is authored here. The synthetic block is the precedent to mirror **in shape,
not in colour**: unconditional markup, attribute-gated visibility, no dismiss affordance — but
`--warn`, never `--danger`.

*Preamble, as T3's gap blocks do it:* every `var(--…)` below exists in
`.claude/features/site-tuned-blend/clarity-design-tokens.md`. **Sizes are per-component literals** —
Clarity publishes no font-size tokens. The one literal hex, `#ff922b33`, is Clarity's own badge
recipe (token doc §5.7: *tint background + 700 text + 500-hex-at-20%-alpha border*); Clarity ships
no alpha token, so the literal is sanctioned there and only there. **Destination:
`frontend/forecast.css`, written by F5.** F1 does not create that file.

```css
/* ── Stale-cycle signals — keyed ONLY off <html data-stale="true"> ──
   Same shape as the synthetic block in frontend/tokens.css:19-47 (unconditional
   markup, attribute gates visibility, no dismiss affordance) — deliberately NOT
   the same colour. Stale is --warn. --danger belongs to synthetic data and to a
   non-positive improvement, and to nothing else.
   Absent attribute => every rule below is inert. There is no "false" value. */

.cycle-stale        { display: none }
.cycle-stale-reason { display: none }

html[data-stale="true"] .cycle-stale        { display: inline-flex }
html[data-stale="true"] .cycle-stale-reason { display: block }

/* The pill — Clarity .badge-pill idiom (token doc §5.7) in the --warn tone. */
.badge-pill.cycle-stale {
  align-items: center;
  gap: var(--s-1);                  /* 4px */
  padding: 2px 9px;
  border-radius: var(--r-full);     /* 999px */
  background: var(--warn-soft);     /* --orange-tint */
  color: var(--orange-700);
  border: 1px solid #ff922b33;      /* --orange-500 at 20% alpha, per token doc §5.7 */
  font-family: var(--font-ui);
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.5;
  white-space: nowrap;
}
.badge-pill.cycle-stale .dot-mini {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
  opacity: .85;
}

/* meta.cycle.stale_reason, verbatim. Server text, so it is typeset as machine
   output — same idiom as .empty-detail in §1.9. */
.cycle-stale-reason {
  margin-top: var(--s-1);           /* 4px */
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text-muted);
  word-break: break-word;
}

/* The run label is permanent chrome (§1.1). Under staleness it changes tone —
   it never appears, never hides, never becomes a badge. */
html[data-stale="true"] .cycle-run-label { color: var(--orange-700) }
```

Token check: `--s-1`, `--r-full`, `--warn-soft`, `--orange-700`, `--font-ui`, `--font-mono`,
`--text-muted` are all present in `clarity-design-tokens.md` (token doc §1.3, §2.1, §3.1, §3.2) and in the
vendored `frontend/vendor/clarity-tokens.css` the page links. No invented token name appears above.

---

## 4. Trust-panel copy — verbatim, with the real numbers

The strings below are the copy F7 renders, with the values substituted from `skill.by_lead[]` — the
sentences are the exact template shape, not hardcoded literals, and the numbers shown are the values
those fields currently carry, verified from `data/results.json`
(`generated_at: 2026-09-04T12:53:01Z`). Window `2026-08-04T12:00:00Z → 2026-09-04T00:00:00Z`,
30 days, split chronologically 20 train days / 10 test days, 80 train rows / 40 test rows per lead.

**Rounding, stated once so nobody re-derives it.** MAE is displayed to **2 decimal places** in prose
and in the headline cell, matching FORECAST-SPEC §6.1's own phrasing. `improvement_pct` is displayed
to **1 decimal place**, matching T3 §3's copy shape. The full-precision values from the payload are
in the table below and are what the numeric cells sort and compare on; nothing is rounded twice, and
nothing is rounded differently to make a comparison land better.

| Lead | Weights HRRR / GFS / NAM / NBM | `blend_mae` (out-of-sample) | `blend_mae_in_sample` | `best_single_model` / `best_single_mae` | `improvement_pct` | `n_test` / `independent_days_approx` |
|---|---|---|---|---|---|---|
| 6 h | 0.5 / 0.0 / 0.1 / 0.4 | **1.9173** | 1.7793 | HRRR / 2.1075 | +9.0249 | 40 / ~30 |
| 12 h | 0.6 / 0.0 / 0.1 / 0.3 | **1.9661** | 1.9730 | HRRR / 2.2814 | +13.8205 | 40 / ~30 |
| 24 h | 0.5 / 0.0 / 0.1 / 0.4 | **2.1066** | 2.0141 | HRRR / 2.5231 | +16.5075 | 40 / ~30 |

**HRRR is the best single model at all three leads — not NBM.** The brief's intuition was that NBM,
being NOAA's own blend, would win; it did not. `best_single_model` is read from the payload and
rendered; the model name is never hardcoded in the copy, and the copy follows the data even when the
data contradicts the pitch.

**GFS carries weight 0.0 at every fitted lead.** That is a real result. It is shown, it renders as
`0.0`, it is de-emphasised, and it is never dropped from the vector (§1.4, §9 rule 7).

#### The three lead statements — verbatim

**6-hour lead.**

> Over the last 30 days at KOMA, this blend's typical miss at a 6-hour lead was 1.92 °F — better than
> the best single model (HRRR, 2.11 °F) over the same period. In-sample, on the 20 days the weights
> were fitted on, it was 1.78 °F. That is 40 scored forecasts, which is roughly 30 independent days,
> not 120. That is history, not a promise about this forecast.

**12-hour lead.**

> Over the last 30 days at KOMA, this blend's typical miss at a 12-hour lead was 1.97 °F — better
> than the best single model (HRRR, 2.28 °F) over the same period. In-sample, on the 20 days the
> weights were fitted on, it was also 1.97 °F; the two differ by less than 0.01 °F, and at this lead
> the fit did not degrade on unseen days. That is a 40-sample coincidence, not evidence that the fit
> generalised better than it was measured to. That is 40 scored forecasts, which is roughly 30
> independent days, not 120. That is history, not a promise about this forecast.

**24-hour lead.**

> Over the last 30 days at KOMA, this blend's typical miss at a 24-hour lead was 2.11 °F — better
> than the best single model (HRRR, 2.52 °F) over the same period. In-sample, on the 20 days the
> weights were fitted on, it was 2.01 °F. That is 40 scored forecasts, which is roughly 30
> independent days, not 120. That is history, not a promise about this forecast.

**The sample-size reason, once, in `.skill-basis` under all three blocks** (§1.5):

> Four initialisations a day over 30 days share a weather regime, so the ~120 forecast-observation
> pairs at each lead are closer to ~30 independent days.

#### The 12-hour ordering, and how the panel keeps it unmisreadable

At 12 h the out-of-sample figure (1.9661) is **lower** than the in-sample figure (1.9730). That
ordering is the opposite of the other two leads, and README C1 attributes it to a 40-sample
coincidence. Three rules, all in force at every lead, are what let the panel survive it:

1. **The two cells never swap position.** `BLEND MAE (OUT-OF-SAMPLE)` is always the first cell and
   always the larger type; `IN-SAMPLE (FITTED DAYS)` is always the second and always smaller and
   muted. Neither is ever sorted, promoted or re-ordered by which happens to be lower. A reader who
   cannot remember which number is which reads the labels, which are always there.
2. **The in-sample number never appears alone**, never carries the headline treatment, and never
   carries a tone token. It is the cost-of-fitting figure, not a score.
3. **No delta between them is rendered as a tone-coloured or arrowed figure.** If the gap is shown
   at all it is shown as a labelled, neutral, signed value using §6's U+2212 — never green when it
   happens to favour the fit, never an up-arrow, never a badge. At 12 h it would favour the fit, and
   a green arrow there would assert precisely the thing README C1 says the data does not support.

The 12 h copy above states the coincidence in the sentence itself, in the customer's language,
rather than leaving the ordering to be discovered from the numbers. **It must not be reworded into
anything that reads as the fit generalising better than measured**, and the two numbers must not be
rounded to hide the ordering. Per §6 they are rendered twice at different precisions, and that is
what keeps this lead honest: the **prose** rounds to 2 dp, where both read `1.97` and the ordering
is invisible, so the sentence states the direction in words; the panel's **numeric cells** carry the
full payload precision, `1.9661` against `1.9730`, where the ordering stays inspectable by anyone
who looks. Neither rendering may be dropped at this lead to simplify the other.

#### Leads beyond 24 hours — no number, ever

For any lead with `is_extrapolated_lead: true`, the panel renders `.skill-extrapolated`
(`id="skill-beyond-fitted"`, §1.5) containing this sentence and nothing else, verbatim:

> No skill measurement exists beyond a 24-hour lead. These hours use the 24-hour weights and are unverified.

**No number appears in or beside that block.** Not an MAE, not an improvement figure, not a sample
size, not a percentage, not an interpolation, not a "roughly". The only digits inside it are the
`24` in the sentence itself. There is no per-lead skill block for 27 h through 48 h, no greyed-out
row where one would go, and no tooltip on an extrapolated strip cell that quotes a number.

This is non-negotiable (FORECAST-SPEC §7). **Inventing an interpolated MAE for a 42-hour lead is
exactly the tuning §15 bans** — the backtest never measured beyond 24 h, so the page has nothing to
report there, and a blank is the honest rendering. Half the forward strip is in this region (§1.2),
which is the reason the sentence gets a card block of its own rather than a footnote.

#### Rendering `improvement_pct` honestly

- **A real minus, U+2212 `−`, on a negative value.** Never `Math.abs`, never clamped to zero, never
  rendered as a magnitude with the direction implied elsewhere. See §6 for the page-wide rule.
- **Never `--success` green on a non-positive value.** Zero and negative are legitimate outcomes
  (FORECAST-SPEC §15: *if the blend's historical skill at a lead is no better than the best single
  model, the page says so*), and they render in the tone their state calls for.
- The three states — the condition boundaries, the tone token for each, and the copy template for
  each — are tabulated in **`.claude/features/demo-shell/design-target.md` §3, "The three improvement
  states (D4)"**. F5 and F7 read that table there. **It is not restated here**, so there is exactly
  one place it can drift from.
- All three leads currently sit in that table's first state. That is what this data says today, not
  a property of the page: the tone is computed from `improvement_pct` on every render, and a refit
  that produced a zero or negative value must move the panel to the matching state with no code
  change beyond the data.

---

## 5. The dark layer

FORECAST-SPEC §17 says: *"Dark mode: `<html data-theme="dark">`, localStorage key
`internal-portal:theme`. **Mirror `theme.js`'s inline pre-hydration script** or the presenter sees a
light-theme flash."* There is nothing to mirror. **`frontend/theme.js` does not exist on this
branch**, and no `[data-theme=dark]` rule exists anywhere in `frontend/`.

**Verification (run 2026-09-04, at write time, in the worktree).**
`grep -rn "data-theme" frontend/` returns **exactly one hit, and it is a comment** —
`frontend/tokens.css:2`, *"Authored under `:root` only, so a `[data-theme=dark]` block can drop in
later (D11)."* `ls frontend/theme.js` returns **No such file or directory**. Both expectations from
the F1 plan (Task 4.1) held. `frontend/vendor/clarity-tokens.css` is a single `:root { … }` block —
115 lines, one selector, **zero class rules and zero `[data-theme]` rules**
(`grep -nE '^[^ /*].*\{' frontend/vendor/clarity-tokens.css` → `1::root {`). `theme.js` is named in
FORECAST-SPEC §3's off-limits table because it exists in *uncommitted* work on the demo checkout;
on this branch it is not a file, and F5 must not wait for it or import it.

**So this document supplies the dark layer itself.** Everything below is specification text. F5
decides whether to wire it — see *"Which of the two F5 should do"* at the end of this section, which
names the answer so F5 is not left guessing.

#### 5.1 The `[data-theme=dark]` semantic override block — authored inside `forecast.css`

Copied from `.claude/features/site-tuned-blend/clarity-design-tokens.md` §4, which reproduces
Clarity's compiled stylesheet verbatim. It redefines **only** the semantic layer and the shadows —
never the raw scales.

> **Why this duplication is correct:** the block belongs in `forecast.css`, a brand-new file, and
> **not** in `tokens.css` or `vendor/**`, because FORECAST-SPEC §3 makes those off-limits and the
> regression gate requires the demo path to stay **byte-identical** to the branch point — adding a
> dark block to `tokens.css` would change a file the 16:00 demo loads, to fix a page the demo does
> not open. Scoping it to `forecast.css` gets the forecast page a dark theme while the demo page
> stays exactly as T3 shipped it. This is the same reasoning as §7's re-author-not-import list.

```css
/* ── Dark layer — forecast page only ──────────────────────────────────────────
   Clarity's dark theme, verbatim from clarity-design-tokens.md §4. It is authored
   HERE, in forecast.css, and NOT in tokens.css or vendor/**, because those are
   off-limits (FORECAST-SPEC §3) and the demo path must stay byte-identical.
   Semantic layer + shadows only. The raw scales are never redefined.
   Attribute-driven only: no prefers-color-scheme anywhere. */
[data-theme=dark] {
  --bg:            var(--charcoal-950);  /* #15181c */
  --bg-elev:       var(--charcoal-900);  /* #212529 */
  --bg-subtle:     var(--charcoal-800);  /* #2d333b */
  --bg-sunken:     var(--charcoal-950);  /* #15181c */
  --border:        var(--charcoal-800);  /* #2d333b */
  --border-strong: var(--charcoal-700);  /* #404750 */
  --text:          #f3f5f7;
  --text-muted:    var(--charcoal-400);  /* #adb5bd */
  --text-subtle:   var(--charcoal-500);  /* #868e96 */
  --accent:        var(--blue-400);      /* #4eaff5 */
  --accent-strong: var(--blue-300);      /* #72c3fc */
  --accent-soft:   #329af026;            /* blue @ 15% */
  --on-accent:     var(--charcoal-950);  /* #15181c */
  --success-soft:  #51cf6624;
  --warn-soft:     #ff922b26;
  --danger-soft:   #f0329a26;
  --info-soft:     #329af026;
  --shadow-1:   0 1px 0 #0006, 0 1px 2px #0006;
  --shadow-2:   0 1px 0 #0006, 0 6px 16px #0006;
  --shadow-3:   0 8px 28px #00000080, 0 2px 6px #0000004d;
  --shadow-pop: 0 24px 60px #0009, 0 8px 20px #0006;
}
```

Two things in that block look like typos and are not. `--danger-soft` resolves to `#f0329a26` —
data-viz pink, **not** the `--danger` pink `#de0f80` — and `--success-soft` uses alpha `24` where
every other soft token uses `26`. Both are verbatim from the compiled stylesheet. **Copy them as
they are; do not "correct" them.** Chasing consistency here means the forecast page's dark tints
stop matching every other Clarity surface.

**What does not change in dark, and must not be changed here:** `--success` (`#37b24d`), `--warn`
(`#ff922b`), `--danger` (`#de0f80`), `--info` (`#329af0`), `--ring`, every radius, every spacing
step, the density tokens, and all three font families. The colour budget of §0 therefore survives
the theme switch intact: `--danger` is still spent on the synthetic banner and on a non-positive
improvement and on nothing else; stale and extrapolated still take `--warn`; "recent" is still
never `--success` green.

One consequence worth knowing before it looks like a bug: in **light**, `--warn` and the GFS series
colour are the *same* hex (`#ff922b` — `--warn` is `var(--orange-500)`, and `--model-gfs` is
`var(--orange-500)`). In **dark** they separate, because the series steps to `--orange-300`
(`#ffc078`) while `--warn` holds at `#ff922b`. That is expected. Do not "fix" the light collision by
recolouring GFS — the model→colour map (§0.1) is fixed, and stale/extrapolated chrome is chrome, not
a series mark; they are separated by shape and position, not by hue.

#### 5.2 The inline pre-hydration `<script>` for `forecast.html`

Literal, pasteable, and **the first child of `<head>` — above every `<link rel="stylesheet">`.**
If it runs after the first stylesheet paints, the presenter gets a white flash before the page
resolves to dark, which on a projector at 16:00 is the most visible defect on the page.

```html
<head>
  <meta charset="utf-8">
  <!-- Pre-hydration theme. MUST be the first child of <head>, before any stylesheet
       link: a stylesheet that paints before data-theme is set gives a light flash.
       Explicit toggle only — Clarity has no prefers-color-scheme behaviour (§4 of
       the token doc), so this reads localStorage and nothing else. Default: light. -->
  <script>
    (function () {
      var t = 'light';
      try { if (localStorage.getItem('internal-portal:theme') === 'dark') t = 'dark'; } catch (e) {}
      document.documentElement.setAttribute('data-theme', t);
    })();
  </script>
  <link rel="stylesheet" href="vendor/clarity-tokens.css">
  <!-- … the remaining three links, in the order §7 fixes … -->
</head>
```

Rules this encodes, each deliberate:

- **Key `internal-portal:theme`** — exactly that string, colon included. It is Clarity's key
  (token doc §4) and FORECAST-SPEC §17 names it. The forecast page shares it with the rest of the
  portal on purpose.
- **Default `light`.** Anything that is not the literal string `dark` resolves to light, so a
  corrupt or absent value degrades to the theme the whole project already ships.
- **No `prefers-color-scheme`, anywhere** — not in the script, not in a media query in
  `forecast.css`. Clarity's theme is an explicit toggle only (token doc §4). A media query would
  make the page's appearance depend on the presenter's OS setting, which is precisely the surprise
  a demo does not need.
- **`try`/`catch` around `localStorage`.** It throws outright when the page is opened from `file://`
  or with site data blocked. An exception here happens before the stylesheets and would leave the
  page unstyled.
- **Attribute on `<html>`**, matching §3's other attribute-gated states (`data-synthetic`,
  `data-stale`), so all three are read the same way.

#### 5.3 The dark-mode series rule — model colours step 500 → 300

Clarity's stated pattern (token doc §4): *"foreground colored text steps up to the 300 weight and
backgrounds become the 500 hex at ~15% alpha (`26`) with a ~35% alpha border (`59`)"*, and
*"use the 500 hexes in light, the 300 hexes in dark."*

| Model | Light (from `tokens.css`, §0.1) | Dark foreground | Dark tinted surface | Dark tint border |
|---|---|---|---|---|
| HRRR | `--blue-500` `#329af0` | `--blue-300` `#72c3fc` | `#329af026` | `#329af059` |
| GFS | `--orange-500` `#ff922b` | `--orange-300` `#ffc078` | `#ff922b26` | `#ff922b59` |
| NAM | `--purple-500` `#a551cf` | `--purple-300` `#ba79da` | `#a551cf26` | `#a551cf59` |
| NBM | `--green-500` `#51cf66` | `--green-300` `#8ce99a` | `#51cf6626` | `#51cf6659` |

The step is applied **once**, by overriding the four Bhar-local names inside the dark block, so
every consumer in §1.2, §1.4 and §2 keeps writing `var(--model-hrrr)` and gets the right value in
both themes without a single dark-specific selector:

```css
[data-theme=dark] {
  --model-hrrr: var(--blue-300);    /* #72c3fc */
  --model-gfs:  var(--orange-300);  /* #ffc078 */
  --model-nam:  var(--purple-300);  /* #ba79da */
  --model-nbm:  var(--green-300);   /* #8ce99a */
}
```

> **This is not a second declaration of the map, and §0.1's prohibition still stands.** The *light*
> values are declared once and only once, in `frontend/tokens.css:9-12`; nothing here touches them.
> This is the theme layer of the same four names, expressed in the same form (`var(--<hue>-N00)`) and
> stepping the same hues — the map is unchanged, only its weight. The parity §17 demands (HRRR the
> same blue on both pages) is unaffected, because the demo page is light-only. **If the demo page
> ever gains a dark theme, this four-line override moves into `tokens.css` so both pages step
> together** — that, and not a `forecast.css`-local copy, is the fix at that point.

Tinted surfaces (a per-model tint on a strip cell, a member mark's chip, a legend swatch) cannot go
through `var(--model-*)` because they need an alpha channel, so they are literal hex pairs from the
table above. Substitute the real selectors from §2; the shape is:

```css
[data-theme=dark] .<cell-or-chip-selector-from-§2>[data-model="hrrr"] {
  background: #329af026;
  border-color: #329af059;
}
/* …and the same pair for gfs / nam / nbm from the table above. */
```

Everything else in dark is free. The page is authored entirely on semantic tokens (`--bg-elev`,
`--border`, `--text`, `--text-muted`, `--warn-soft`, `--danger-soft`), and §5.1 redefines exactly
those, so cards, tables, the strip chrome, the stale treatment, the synthetic banner and the empty
state all re-tone with no further rules.

#### 5.4 The cheaper fallback, and which of the two F5 should do

The fallback is **light-only for v1**, exactly as T3 shipped (D11 deferred): no `<script>` in the
head, no dark block in `forecast.css`, no theme toggle control in the UI, and every rule authored
under `:root` and on semantic tokens so the dark layer stays a drop-in.

**Recommendation: ship light-only for v1, with the dark block written here and ready to wire.**
The reason is scope, not taste. The dark layer is unplanned work — it exists only because
FORECAST-SPEC §17's premise (that a `theme.js` is there to mirror) turned out to be false on this
branch, as §5's verification above records. There is a demo at 16:00 and seven tickets after this
one; the demo page itself is light-only, so a dark forecast page buys no parity with anything, and
a half-wired theme (a toggle with no pre-hydration script, or a script with no toggle) is strictly
worse than none. **F5: do not paste §5.1, §5.2 or §5.3 into `frontend/forecast.*`.** An unreachable
CSS block inside a shipped file rots; it is better read here, where it is dated and explained.

If dark is wanted later, wiring it is three additions and **no restructuring**:

1. Paste §5.2's `<script>` as the first child of `forecast.html`'s `<head>`, above the four
   stylesheet links.
2. Paste §5.1's block plus §5.3's four-line model override at the end of `forecast.css`, after
   every `:root`-scoped rule so the cascade resolves the way §7's load order intends.
3. Add one toggle control that writes `localStorage['internal-portal:theme']` and sets
   `document.documentElement.dataset.theme` to the same value. **Do not add the toggle without
   step 1** — a toggle whose choice is forgotten on reload is a bug the audience will find.

Nothing in §1, §2, §3 or §4 changes: no selector is restructured, no token is renamed, no markup
moves. That is the whole point of authoring on semantic tokens. §3's state table lists `data-theme`
alongside `data-synthetic` and `data-stale` for the same reason — one attribute on `<html>`, read
one way, three states.

---

---

## 6. Numeric formatting and signed values (applies page-wide)

T3's `.claude/features/demo-shell/design-target.md` §6 is the precedent, and this section mirrors
its shape. The rule is the same, the exceptions are new.

**The rule.** Every temperature and every error value on the page — the strip's per-cell blend
values, the member values, model spread, the trust panel's MAE figures, the history table's
`blend_f` / `observed_f` / `error_f` columns, the daily `mae_f`, `obs_offset_min`, the weights, and
the 503's diagnostics — renders in `var(--font-mono)` (JetBrains Mono) with
`font-variant-numeric: tabular-nums` set **explicitly**, right-aligned. Setting the property
explicitly matters: the mono face alone does not guarantee the tabular set, and without it a column
of leads and errors shifts by a fraction of a character as the digits change.

The CSS already exists and is linkable — `.num` / `.mono-value` at `frontend/tokens.css:209-214`,
referenced in §0.2. **`forecast.css` must not restate it.** Apply the class; do not re-author the
rule. (This is the one class rule on this page that is *not* on §7's re-author list, precisely
because `tokens.css` is on the permitted-link list and already carries it.)

**The one exception — the headline temperature (§1.1).** It reads in `var(--font-display)` (Sora)
via `.stat-value`, per the token doc §5.6: *"The hero number reads in Sora; supporting numbers stay
in mono."* `.stat-value` already sets `font-variant-numeric: tabular-nums` itself, so the hero
number is tabular too. It is the **only** number on the page in Sora. Every other number, including
the run label's age and the stale banner's figures, is mono. See §1.1 for the headline's size,
placement and the run label that sits under it.

**Decimal places.** The payload's precision and the page's precision are deliberately not the same
thing, and the difference is an integrity decision, not a formatting preference.

| Value | Payload carries | Page renders | Why |
|---|---|---|---|
| `blend_f`, `members[*]`, `observed_f`, `best_single_model_f` | 2 dp (`78.41`) | **1 dp** — `78.4 °F` | The measured error at this site is roughly 2 °F (§4). Printing hundredths of a degree on a forecast claims a precision the scoring says does not exist. |
| `error_f` (signed), `member_spread_f` | 2 dp (`1.24`, `1.85`) | **1 dp** — `1.2 °F`, `1.9 °F` | Same scale as the values they are derived from; matching them keeps a history row's columns readable. |
| `blend_mae`, `blend_mae_in_sample`, `best_single_mae` | 4 dp (`1.9173`) | **2 dp in prose copy** — `1.92 °F`; **4 dp verbatim in the panel's numeric cells** — `1.9173` | Two renderings, deliberately, and §4 uses both. Prose follows FORECAST-SPEC §6.1's own acceptable phrasing, which reads `1.92 °F`. The cells keep full payload precision because the digits are load-bearing: at 12 h the out-of-sample MAE is `1.9661` against an in-sample `1.9730`, and at 2 dp both read `1.97` and the ordering stops being inspectable. §4 states the direction in words precisely because the prose rounding hides it. |
| `days[].mae_f` | 2 dp (`1.31`) | **2 dp, verbatim** | A daily aggregate over a handful of entries; the payload's own precision is the honest one. |
| `improvement_pct` | 4 dp (`9.0249`) | **1 dp with an explicit sign** — `+9.0 %` | Matches T3 §3's copy shape on the sibling page, so the two pages round a percentage the same way. One decimal is all a 40-sample test set supports. The sign is always shown, positive included. |
| `weights[*]`, `member_spread_f` in a compact chip | 1 dp source | **1 dp, always** — `0.5`, `0.0` | GFS's fitted weight is genuinely `0.0` at every lead. It renders as `0.0`, never as `0`, never blank, and is never dropped. |
| `age_minutes`, `obs_offset_min`, `lead_h`, `n_test`, `independent_days_approx`, `weights_age_days`, `cycles_fallen_back` | integer | **integer**, mono | Counts. `obs_offset_min` is signed; the others are not. |

Units come from `meta.units` and are rendered as `°F` after a single space (`78.4 °F`), never
retyped as a literal in JS. Percentages get a space before the `%`, matching `+9.0 %` above.

**Signed values.** Wherever a value can be negative — `error_f`, `improvement_pct`,
`obs_offset_min` — the sign is rendered with a **real minus, U+2212 `−`**, never the ASCII hyphen
`-`. The hyphen is narrower than a digit even in a tabular face and breaks the column it sits in.
JetBrains Mono carries U+2212, and so does every fallback in `--font-mono`'s stack.

Three prohibitions, all of them load-bearing:

- **Never `Math.abs`.** A negative `improvement_pct` means no blend beat the best single model, and
  a negative `error_f` means the blend ran cold. Both must be visible as negative. See T3 §3 for
  the three improvement states, their tone tokens and their copy — **not restated here.**
- **Never clamped.** No `Math.max(0, …)`, no flooring at zero, no hiding a negative behind a
  neutral dash.
- **Never faked in CSS.** The sign is a character in the text node, not a `::before`. A sign drawn
  by a pseudo-element does not survive copy-paste out of the page, and a presenter who pastes a
  number into a chat window must paste the sign with it.

`Intl.NumberFormat` and `toFixed` both emit an ASCII hyphen for negatives in `en-US`, so the
substitution is explicit and belongs in one shared formatter, not at each call site:

```js
// One place, reused everywhere. Positive values carry an explicit '+' only where the
// design asks for it (improvement_pct, obs_offset_min); temperatures do not.
const MINUS = '−';
const fmt = (v, dp, signed = false) =>
  (signed && v > 0 ? '+' : '') + v.toFixed(dp).replace('-', MINUS);
```

The three improvement states, their tone tokens and their exact copy live in T3's design target §3
and are reused unchanged. Note only the one page-specific consequence: an improvement that is zero
or negative renders in `--danger` or neutral per that table and **never** in `--success`, and this
holds identically in dark, because §5.1 leaves `--success` and `--danger` untouched.

---

---

## 7. Cross-cutting notes

**Load order — cascade-critical, and exactly this four-item sequence.** `forecast.html` links these
four stylesheets, in this order, after §5.2's inline script if the dark layer is ever wired:

1. `vendor/clarity-tokens.css` — Clarity's raw scales and light semantic layer
2. `vendor/fonts.css` — the three self-hosted `@font-face` declarations
3. `tokens.css` — Bhar-local: the model→colour map (§0.1), the synthetic-banner CSS, T3's two
   shipped gap blocks (§0.2), `.num` / `.mono-value` (§6)
4. `forecast.css` — this page's layout, the strip (§2), the stale treatment (§3), the re-authored
   components below, and the dark block (§5.1) if wired

Each file consumes what the one before it defines. Reordering them does not error; it silently
resolves custom properties to nothing, and the page renders unstyled or half-styled.

**The re-author-not-import list.** `frontend/app.css` is **not** on FORECAST-SPEC §3's
permitted-link list. That list is exactly three files — `vendor/clarity-tokens.css`,
`vendor/fonts.css` and `tokens.css` — and `app.css` is on the off-limits table beside
`index.html`, `chart.js` and the rest of the demo path. And `vendor/clarity-tokens.css` carries
**zero class rules**: verified at write time with
`grep -nE '^[^ /*].*\{' frontend/vendor/clarity-tokens.css`, which returns a single line,
`1::root {` — 115 lines, one selector, all custom properties, no components.

So the component classes the forecast page needs exist nowhere it is allowed to link, and
`forecast.css` **re-authors** each of them from the token doc:

| Class(es) | Source | Used by |
|---|---|---|
| `.card`, `.card-header`, `.card-title`, `.card-sub`, `.card-body` | token doc §5.5 | the strip card, the trust panel (§1.5), the history view (§1.6) |
| `.tbl` and its header/row/number conventions | token doc §5.1 | the history table (§1.6), the per-lead skill table (§4) |
| `.segmented` | token doc §5.3 | the lead-time / day selector (§1.6) |
| `.badge-pill` | token doc §5.7 | the stale badge (§1.7), the extrapolated marker (§1.2), the zero-weight GFS marker (§1.4) |
| `.stat-card`, `.stat-value`, `.stat-meta`, `.stat-label` | token doc §5.6 | the headline temperature (§1.1), the trust panel's MAE tiles (§1.5) |
| page header / app shell — `.page-header`, `.page-title`, `.page-sub`, `.page-header-actions`, `.topbar` | token doc §5.9 | the page frame and the run label (§1.1) |
| `.empty-state` | token doc §5.10 — **prose, not CSS**: *"Center content, hint the next action, never apologize. Icon → title → one sentence → action."* Title 15 px/600, sub 13 px. T3 §1.9 is the shipped precedent for its shape | the 503 (§1.9) |

**That duplication is correct, and it is the point.** An implementer who finds himself retyping
`.card` will reach for the obvious fix — `<link rel="stylesheet" href="app.css">` — and that one
line couples the forecast page to a file the 16:00 demo loads. From then on, any change the
forecast page wants in `.card` is a change to the demo path, which §3 forbids and the regression
gate (`git diff --stat` against the branch point shows no off-limits path modified) will catch only
after the fact. Re-authoring costs perhaps forty lines and buys a hard boundary: the demo path stays
**byte-identical**, and the forecast page can evolve without asking anyone's permission. Copy the
declarations from the token-doc sections above as they are written; do not "improve" them in
passing, or the two pages drift apart in the way §0.1 spends a whole section preventing.

The only class rules `forecast.css` must **not** re-author are the ones `tokens.css` already carries
and §0.2 lists — the range slider, the chart/axis block, the synthetic-banner CSS and
`.num` / `.mono-value`. Those arrive by linking `tokens.css`. Restating any of them is the same
drift in the other direction.

**Viewport and the fold.** Target **1440×900**, matching T3. **The run label must be reachable
without scrolling at that size — a hard requirement, not a preference** (FORECAST-SPEC §5.2, and
§1.1 for its exact format and placement). The practical constraint on everyone editing this page:
the headline temperature, the run label and the first row of the forward strip share the first
screen, so vertical padding on the page header and the strip card is the budget that gets cut when
something new needs room — never the run label, and never by pushing the strip below the fold.
Check it at 1440×900 specifically; a taller laptop hides the failure.

**FORECAST-SPEC §3 — for F5, F6 and F7: new files only.** `frontend/forecast.html`,
`frontend/forecast.js`, `frontend/forecast.css` and any new files they need are yours to create.
Everything else under `frontend/` — `index.html`, `app.js`, `app.css`, `chart.js`, `models.js`,
`format.js`, `theme.js`, `tokens.css`, `vendor/**`, and `overview.html` with its assets — is
off-limits, including for a "quick refactor while I'm here". Read them freely; import from them
never, beyond the three permitted `<link>`s named in the load order above.

**And the two permitted `backend/main.py` lines belong to F4, not to F5.** §3 grants exactly one
`import` and one `app.include_router(...)` line in `backend/main.py`, and grants them to **F4
only**. If F5 finds the forecast router unmounted, that is an F4 problem to raise, not a two-line
edit to make. The FastAPI app title `"Bhar - Site-Tuned Model Blend"` is the identity discriminator
against the port-8000 squatter, and `demo.sh` depends on it — nothing in this page's tickets touches
`main.py` beyond those two lines.
