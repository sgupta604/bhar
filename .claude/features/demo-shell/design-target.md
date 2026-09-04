# Design Target — demo-shell (T3)

**Source:** `.claude/features/site-tuned-blend/clarity-design-tokens.md` (Clarity v0.2, the primary
source — every token named below exists there). Cross-referenced against `docs/BRIEF.md` §8 (page
structure) and `docs/SPEC.md` §12 (frontend design, the two Clarity gaps, D2/D4/D7).

**Rules this document follows, and that the frontend implementer must also follow:**
- **Semantic tokens only.** Never a raw scale value (`--blue-500` is fine only where §1 below
  explicitly names it as the model-color source; UI chrome never reaches past the semantic layer).
- **Never an invented token name.** Every `var(--...)` below exists in the token doc.
- Light mode only. Author under `:root` so `[data-theme=dark]` can drop in later (deferred, D11).
- Target viewport **1440×900**. The honesty panel (footer) must be reachable without excessive
  scrolling at that size.

---

## 0. The model → color map (single source of truth — stated ONCE)

Used identically by: stacked weight bars (leaderboard), slider fills, model checkboxes, and chart
series. Do not re-derive this elsewhere; every other region references it by name.

| Model | Token | Hex |
|---|---|---|
| HRRR | `--blue-500` | `#329af0` |
| GFS | `--orange-500` | `#ff922b` |
| NAM | `--purple-500` | `#a551cf` |
| NBM | `--green-500` | `#51cf66` |

**Data-viz pink (`--pink-500` `#f0329a`) is deliberately unused for a model.** It collides with
`--danger` (`--pink-700` `#de0f80`) — the synthetic banner and the negative-improvement signal both
live in that hue family, and a model series in pink would visually merge with those alerts. Yellow
(`--yellow-500` `#f7be1e`) is also left unused; four models need only four series, and reserving the
remaining two data-viz slots keeps the palette legible if a fifth model is ever added.

In CSS these are exposed as local custom properties in `frontend/tokens.css` (Bhar-local additions,
not part of vendored Clarity):
```css
:root {
  --model-hrrr: var(--blue-500);
  --model-gfs:  var(--orange-500);
  --model-nam:  var(--purple-500);
  --model-nbm:  var(--green-500);
}
```

---

## 1. Per-region specification

### 1.1 Synthetic banner (D2)
See §4 below — it is specified fully there since it is one coherent visual system with the page
frame.

### 1.2 Header
- Region background: `--bg` (`#f8f9fa`), page-level.
- Title (`Omaha Eppley (KOMA)`): `--font-display` (Sora), **Page Title 24px/600**, `line-height:1.2`,
  `letter-spacing:-.02em`, color `--text` (`#212529`). Matches the documented `.page-title` pattern.
- Subtitle line(s) (`Last 30 days`, `2m temperature, N candidate blends scored vs METAR`):
  `--font-ui` (Inter), **13.5px**, color `--text-muted` (`#5c636a`). Matches `.page-sub`.
- Layout: `.page-header` idiom — `display:flex; align-items:flex-start; gap: var(--s-4)` (16px);
  `margin-bottom: var(--s-6)` (24px).
- Spacing: page padding `var(--s-8)` (32px) on the outer shell.

### 1.3 Lead-time toggle (`6h | 12h | 24h`)
Use the Clarity **`.segmented`** idiom verbatim (token doc §5.3) — not custom buttons.
- Track: `display:inline-flex; padding:2px; background:var(--bg-subtle); border:1px solid var(--border); border-radius:var(--r-md)` (8px).
- Each segment button: `height:28px; padding:0 var(--s-3)` (12px); `background:none; border:none; border-radius:6px; color:var(--text-muted); font-family:var(--font-ui); font-size:12.5px; font-weight:500`.
- Active segment: `background:var(--bg-elev); color:var(--text); box-shadow:var(--shadow-1)` — the
  "raised white pill on a sunken track" pattern.

### 1.4 Model checkboxes
- Each checkbox row/chip pairs the model's dot (background = its `--model-*` color from §0) with
  its label in `--font-ui`, **13px/500**, color `--text`.
- Unchecked (disabled) state dims: label color steps to `--text-subtle`, dot opacity `.4`.
- Spacing between chips: `var(--s-3)` (12px). Chip padding: `var(--s-1) var(--s-2)` (4px 8px).
- Optional container background `--bg-elev`, border `--border`, radius `--r-md` (8px) if grouped
  as a bar — follows `.badge-pill`-adjacent spacing conventions, not the badge component itself
  (checkboxes are interactive, badges are not).

### 1.5 Leaderboard
Built on the documented `.tbl` component, inside a `--r-xl` (14px) `.card` with `--shadow-1`.
- Card: `background:var(--bg-elev); border:1px solid var(--border); border-radius:var(--r-xl); box-shadow:var(--shadow-1)`.
- Card header (title "Leaderboard" or similar): `.card-title` — **14px/600**, color `--text`, inside
  `.card-header` (`padding: 16px 20px; border-bottom:1px solid var(--border)`).
- Table header row: `--font-ui` **11.5px/500**, `text-transform:uppercase`, `letter-spacing:.05em`,
  color `--text-subtle`, background `--bg-subtle`, `border-bottom:1px solid var(--border)`,
  `padding:10px 16px`, `position:sticky; top:0`.
- Body rows: height `var(--row-h)` (48px), `border-bottom:1px solid var(--border)`, `padding:0 16px`,
  font-size 13px, color `--text`. Row hover → `background:var(--bg-subtle)`. No zebra striping.
- Rank column: `--font-mono`, 12.5px, `--text-muted`.
- Weight label column (`70 / 30`, `HRRR only`): `--font-ui`, 13px/500, `--text`.
- Stacked weight bar: a horizontal bar, height ~8px, `border-radius:var(--r-full)` (999px),
  segments filled with each included model's `--model-*` color in proportion to its weight, laid
  left-to-right in canonical model order (HRRR, GFS, NAM, NBM). Track background (the zero-weight
  remainder, if any) `--bg-subtle`.
- Error value column (`mae_out_of_sample`, `mae_in_sample`): **`.num` idiom** — `--font-mono`,
  12.5px, `font-variant-numeric:tabular-nums`, right-aligned (`text-align:right`). Out-of-sample is
  the visual headline (`--text`, 500 weight via the mono face's own weight step); in-sample sits
  beside it, smaller/muted (`--text-muted`, 11.5px), explicitly labelled "in-sample" — never bare.
- Winner row highlight: background tone follows the D4 table in §3 below — matched by
  `winner.label`, **never** by row index. Never `--success` (green) when the improvement is
  non-positive.

### 1.6 Sliders (blend-weight controls)
Layout: one `<input type="range">` per enabled model, each row paired with its model's colored dot
(`--model-*`) and label (`--font-ui` 13px/500, `--text`), and a live numeric readout in
`--font-mono`, right-aligned, `font-variant-numeric: tabular-nums`, `--text`.
Row gap: `var(--s-3)` (12px). Slider itself: see the literal CSS block in §2 — built from `.progress`
geometry (6px track, `--r-full` 999px radius, `--bg-subtle` track, tinted fill) plus the 3px
`--ring` focus convention. A disabled slider (its model unchecked) dims per §2's `:disabled` rule.

### 1.7 Chart (error vs weight, two-model slice)
- Container: same `.card` treatment as the leaderboard — `--bg-elev`, `--border`, `--r-xl`,
  `--shadow-1`, `.card-header` / `.card-title` for the chart's title, `.card-body` padding 20px
  for the SVG.
- Gridlines: `--border` (`#e9ecef`), thin (1px), drawn behind the series.
- Axis labels (tick values, axis titles): `--font-ui`, **11px**, color `--text-subtle`.
  (11px sits one notch below the documented Caption 11.5 step, matching the token doc's own
  guidance in SPEC §12 gap #2 — "axis labels `--text-subtle` 11px" — an explicit exception noted
  because Clarity's smallest published UI size is 11.5px; 11px is used here only for axis ticks,
  never for any other UI text on the page.)
- Tooltip: surface `--bg-elev` (white), `box-shadow:var(--shadow-3)`, `border-radius:var(--r-md)`
  (8px), padding `var(--s-2) var(--s-3)` (8px 12px), text `--font-ui` 12.5px `--text`.
- Series: the two selected models' `--model-*` colors (§0). Endpoints (pure-model points) dotted
  and labelled in the same color. Full literal CSS in §2.

### 1.8 Footer / honesty panel
- Container: same `.card` pattern, `--bg-elev` / `--border` / `--r-xl` / `--shadow-1`, `.card-body`
  padding 20px.
- Signed-improvement headline line: `--font-ui`, **14px/600** (matches `.card-title` weight/size for
  visual prominence), color and copy per the D4 table in §3.
- `Showing top N of 286` line: `--font-ui`, 13px, `--text-muted`.
- `meta.source` line: `--font-ui`, 12.5px, `--text-muted`, value itself in `--font-mono` 12.5px
  `--text` (it is a technical token like `synthetic_fixture`, not prose).
- `models_excluded` line(s): each rendered as `--font-ui` 12.5px `--text-muted`, with the excluded
  model name in `--text` and its `coverage_pct` in `--font-mono`. Tone: neutral, not alarmed — this
  is a `--warn` (`--orange-500`)-adjacent fact, not a `--danger` one, but per SPEC §12 it must not
  use `--danger`'s pink (that hue is reserved for synthetic/negative-improvement signals). Render
  its accent dot/icon, if any, in `--warn` (`#ff922b`).
- `join_diagnostics` / `n_samples` / `meta.split` lines: `--font-ui` 12.5px `--text-muted`, numeric
  values in `--font-mono` with `font-variant-numeric: tabular-nums`.
- Row spacing between honesty-panel lines: `var(--s-2)` (8px).

### 1.9 Empty-state card
Per the documented empty-state rule (token doc §5.10): *"Center content, hint the next action,
never apologize. Icon → title → one sentence → action."*
- Container: `.card` (`--bg-elev`, `--border`, `--r-xl`, `--shadow-1`), centered content,
  generous padding (`var(--s-12)`, 48px, vertical).
- Title: `--font-ui`, **15px/600**, `--text`.
- Sub / body sentence: `--font-ui`, **13px/400**, `--text-muted`. This is where the verbatim
  server 503 message is shown — rendered as data, in `--font-mono` 12.5px `--text-subtle` beneath
  the sentence, not as the sentence itself (voice rule: never apologize; the server message is
  technical detail, kept distinct from the human sentence above it).
- No action button is required for T3 (no refetch endpoint exists, per plan D8) — the "hint the
  next action" is satisfied by naming the CLI command in the body sentence
  (`Run: uv run python -m backend.make_fixture`).

---

## 2. Literal CSS — Clarity gap #1: the range slider

Borrowed from `.progress` geometry (6px track, `999px` radius, `--bg-subtle` track, `--accent`
fill) plus the 3px `box-shadow: 0 0 0 3px var(--ring)` focus convention (token doc §5.4, §5.8).
The fill color is tintable per-model via `--slider-fill`, set inline per row (or per model class)
to that model's `--model-*` value from §0.

```css
/* ── Weight slider — Clarity gap #1 (no native range styling exists in Clarity) ──
   Set --slider-fill to the model's color (e.g. style="--slider-fill: var(--model-hrrr)")
   on each <input type="range"> instance. Falls back to --accent if unset. */

input[type="range"].weight-slider {
  --slider-fill: var(--accent);
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 20px;               /* generous hit target; track itself stays 6px, see below */
  margin: 0;
  padding: 0;
  background: transparent;
  cursor: pointer;
}

/* Track — WebKit/Blink */
input[type="range"].weight-slider::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(
    to right,
    var(--slider-fill) 0%,
    var(--slider-fill) calc(var(--slider-pct, 0%)),
    var(--bg-subtle) calc(var(--slider-pct, 0%)),
    var(--bg-subtle) 100%
  );
}

/* Track — Firefox (unfilled base track; Firefox has no single-track gradient trick
   without JS-set custom properties, so the fill on Firefox is drawn by ::-moz-range-progress) */
input[type="range"].weight-slider::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: var(--bg-subtle);
}
input[type="range"].weight-slider::-moz-range-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--slider-fill);
}

/* Thumb — WebKit/Blink */
input[type="range"].weight-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  margin-top: -5px;           /* centers 16px thumb on a 6px track: (6 - 16) / 2 */
  border-radius: 999px;
  background: var(--bg-elev);
  border: 2px solid var(--slider-fill);
  box-shadow: var(--shadow-1);
  transition: box-shadow 0.12s, border-color 0.12s;
}

/* Thumb — Firefox */
input[type="range"].weight-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--bg-elev);
  border: 2px solid var(--slider-fill);
  box-shadow: var(--shadow-1);
  transition: box-shadow 0.12s, border-color 0.12s;
}

/* Focus — 3px ring at the accent hue / 22% opacity, per token-doc §5.8's input focus rule.
   Applied on the slider element itself (outline suppressed; box-shadow carries the ring),
   consistent with .input:focus's box-shadow:0 0 0 3px var(--ring). */
input[type="range"].weight-slider:focus-visible {
  outline: none;
}
input[type="range"].weight-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px var(--ring);
}
input[type="range"].weight-slider:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 3px var(--ring);
}

/* Disabled — model unchecked. Dim track, fill, and thumb; remove pointer affordance. */
input[type="range"].weight-slider:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
input[type="range"].weight-slider:disabled::-webkit-slider-runnable-track {
  background: var(--bg-subtle);   /* fill hidden entirely — no partial color when disabled */
}
input[type="range"].weight-slider:disabled::-moz-range-progress {
  background: var(--border-strong);
}
input[type="range"].weight-slider:disabled::-webkit-slider-thumb,
input[type="range"].weight-slider:disabled::-moz-range-thumb {
  border-color: var(--border-strong);
  box-shadow: none;
  cursor: not-allowed;
}
```

**Implementation note for the frontend agent (not a token, a wiring note):** `--slider-pct` is a
custom property your JS sets on each slider element (e.g. `el.style.setProperty('--slider-pct',
value + '%')`) on `input`/change, since native `input[type=range]` has no CSS-only fill-percentage
mechanism in WebKit. `--slider-fill` is set once per row, statically, to the row's model color.

---

## 3. The three improvement states (D4)

Exact tone tokens and copy. **Always render the sign with a real minus `−` (U+2212), never
`Math.abs`, never clamp.** The winner-row highlight follows this table exactly and is **never**
`--success` (green) when the improvement is non-positive.

| Condition | Tone token | Copy |
|---|---|---|
| `> +0.05` | `--success` (`#37b24d`) | `Winner beats the best single model (NBM) by 3.3%.` |
| within `±0.05` (tie) | `--text-muted`, neutral | `Best blend ties the best single model (NBM). No improvement — 0.0%.` |
| `< −0.05` | `--danger` (`#de0f80`) | `No blend beat the best single model. The best blend is 1.2% worse than NBM.` |

Model name and percentage in the copy are substituted from `winner`/`best_single_model` data —
the strings above are the exact template shape, not hardcoded literals. Background tint for the
row/callout, if used, is `--success-soft` / none / `--danger-soft` respectively (never a raw
scale tint).

---

## 4. Synthetic-mode visual spec (D2)

Keyed **only** off `<html data-synthetic="true">`. When the attribute is absent, both the banner
and the frame vanish with zero code edits — the CSS below is unconditional; only the HTML
attribute gates it.

```css
/* ── Synthetic-data signals — keyed ONLY off <html data-synthetic="true"> ── */

html[data-synthetic="true"] {
  /* 3px inset page frame, full viewport */
  box-shadow: inset 0 0 0 3px var(--danger);
}

html[data-synthetic="true"] .synthetic-banner {
  display: flex;
}
.synthetic-banner {
  display: none;   /* hidden by default; shown only under the attribute above */
  position: sticky;
  top: 0;
  z-index: 100;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  padding: var(--s-2) var(--s-4);   /* 8px 16px */
  background: var(--danger);
  color: #ffffff;
  font-family: var(--font-ui);
  font-size: 13px;
  font-weight: 600;
  text-align: center;
  /* no close affordance — no button, no dismiss icon, ever */
}
```

Copy (verbatim, `<generated_at>` substituted from `meta.generated_at`):
```
SYNTHETIC DEMO DATA — these numbers are fabricated. Not a real backtest. Generated <generated_at>.
```

HTML wiring note: the banner markup is always present in `index.html` (`<div class="synthetic-banner">…</div>`
as the first child of `<body>`, before the page shell), and its visibility is controlled entirely by
the CSS rule above keyed on `html[data-synthetic="true"]` — never by a JS `display` toggle. The 3px
frame is likewise unconditional CSS gated the same way. This is what makes "attribute absent → zero
code edits" true: flipping `is_synthetic` in the JSON and re-rendering the `data-synthetic` attribute
is the only thing that has to change.

---

## 5. Literal CSS — Clarity gap #2: chart / axis

Gridlines `--border`; axis labels `--text-subtle` 11px; tooltip `--bg-elev` + `--shadow-3`; series
colors = the model map in §0.

```css
/* ── Chart / axis — Clarity gap #2 (no chart-series or axis tokens exist in Clarity) ──
   Applies to the inline-SVG two-model error-vs-weight slice. */

.chart-card {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-1);
}

.chart-svg .gridline {
  stroke: var(--border);
  stroke-width: 1;
}

.chart-svg .axis-label {
  font-family: var(--font-ui);
  font-size: 11px;
  fill: var(--text-subtle);
}

.chart-svg .axis-title {
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 500;
  fill: var(--text-subtle);
}

/* Series line + points — color set per instance to the model's --model-* value,
   e.g. style="--series-color: var(--model-hrrr)" on the containing <g>. */
.chart-svg .series-line {
  fill: none;
  stroke: var(--series-color, var(--accent));
  stroke-width: 2;
}
.chart-svg .series-point {
  fill: var(--series-color, var(--accent));
  stroke: var(--bg-elev);
  stroke-width: 1.5;
}
.chart-svg .series-point.is-endpoint {
  stroke-dasharray: 2 2;
}
.chart-svg .series-min-marker {
  fill: var(--bg-elev);
  stroke: var(--series-color, var(--accent));
  stroke-width: 2;
}

.chart-tooltip {
  position: absolute;
  pointer-events: none;
  background: var(--bg-elev);
  box-shadow: var(--shadow-3);
  border-radius: var(--r-md);
  padding: var(--s-2) var(--s-3);   /* 8px 12px */
  font-family: var(--font-ui);
  font-size: 12.5px;
  color: var(--text);
}

.chart-caption {
  font-family: var(--font-ui);
  font-size: 12.5px;
  color: var(--text-muted);
  margin-top: var(--s-2);   /* 8px */
}
```

---

## 6. Numeric formatting (applies page-wide)

All numeric values — leaderboard error columns, slider readouts, footer diagnostics, chart axis
ticks excepted (those are 11px per §1.7) — use `var(--font-mono)` (JetBrains Mono), right-aligned
(`text-align: right` in table/flex contexts), with `font-variant-numeric: tabular-nums` set
explicitly (do not rely on the mono face alone to guarantee tabular alignment).

```css
.num, .mono-value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
```

---

## 7. Cross-cutting notes

- **Theme:** all tokens above are Clarity's `:root` (light) semantic layer, or Bhar-local additions
  under the same `:root` block (`--model-*`, `--slider-fill` default, `--slider-pct` default). No
  `[data-theme=dark]` overrides are written in this ticket (deferred, D11) — authoring under `:root`
  is what makes that drop-in possible later without restructuring.
- **Load order** (for the implementer, not a design decision but load-bearing for cascade
  correctness): `vendor/clarity-tokens.css` → `vendor/fonts.css` → `tokens.css` (Bhar-local:
  `--model-*` + this document's two gap blocks) → `app.css` (layout/composition).
- **1440×900 viewport:** the footer/honesty panel (§1.8) is the last section on the page and must
  be reachable without excessive scrolling — keep the leaderboard to its data-driven row count
  (≥9 rows, not artificially padded) and avoid oversized vertical padding on the header/toggle
  region so the fold lands at or past the top of the footer card.
