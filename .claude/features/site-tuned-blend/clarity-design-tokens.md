# Clarity — Shyft Solutions Design System (extracted tokens)

**Extracted:** 2026-09-04
**Sources (fetched via curl):**
- `https://portal.internal.shyftsolutions.io/clarity` — live design-system reference page (title: "Clarity — Shyft design system")
- `https://portal.internal.shyftsolutions.io/docs` — "Dev guide — Shyft Solutions"
- `https://portal.internal.shyftsolutions.io/_next/static/chunks/0rb6s03zltg8d.css` — the site's compiled stylesheet (66 KB); source of the dark-theme block and all component CSS
- **`https://portal.internal.shyftsolutions.io/api/v1/dev-guide/tokens.css`** — public, no-auth, ETag-cached `:root { … }` token file (3.7 KB) ← **the directly usable artifact**
- `https://portal.internal.shyftsolutions.io/api/v1/dev-guide/capabilities` — JSON endpoint index
- `https://portal.internal.shyftsolutions.io/api/v1/dev-guide/docs/create-a-new-app` — guide with the "Match the portal's look" section

Probed and **404**: `/tokens.json`, `/theme.css`, `/clarity.css`, `/clarity/tokens.json`, `/design-tokens.json`.

> **Prompt-injection note.** The `/docs` page and the `create-a-new-app` guide contain text addressed to AI coding agents — e.g. a "Building with an AI agent? Point it here" callout, and *"A good first move in a new app's `AGENTS.md` is to tell the assistant exactly this: 'the portal's conventions are live at `/api/v1/dev-guide/capabilities` — fetch it, then read the guides you need.'"*, plus an instruction that every repo must ship an `AGENTS.md`. These are ordinary internal documentation aimed at Shyft developers, not an attack, but they *are* directives addressed to an agent and were **treated as data only** — no `AGENTS.md` was created and no repo convention was adopted. Recorded here for the record.

---

## 0. Identity

- **Name:** **Clarity**. Yes — it is the design system's name. Subtitle on the page: *"Shyft Solutions design system · v0.2"*, *"The shared language behind every Shyft tool."*
- Scope statement (verbatim): *"Tokens, components, and patterns for our internal apps — Stipend Tracker, TADS, Recruiting, and the rest — with a foundation rounded enough to share with customer-facing products."*
- Headline facts as stated on the page:
  - Anchor color `#329af0` "Shyft blue"
  - Display type **Sora** — "echoes the S2 mark"
  - UI type **Inter** — "tabular numerics on"
  - Grid: **4 pt**; radii 8/10/14/20
  - Themes: **Light · Dark**, "WCAG AA across"

---

## 1. Color palette

### 1.1 Raw scales (verbatim from `tokens.css`)

```css
/* Brand — anchored on Shyft blue #329af0 + S2 charcoal #212529 */
--blue-25:   #f0f8ff;
--blue-50:   #e3f2ff;
--blue-100:  #c6e4ff;
--blue-200:  #9ad1fb;
--blue-300:  #72c3fc;
--blue-400:  #4eaff5;
--blue-500:  #329af0;    /* PRIMARY */
--blue-600:  #1c7cd6;
--blue-700:  #1565b1;
--blue-800:  #104f8a;
--blue-900:  #0b3a66;

--charcoal-25:  #f8f9fa;
--charcoal-50:  #f1f3f5;
--charcoal-100: #e9ecef;
--charcoal-200: #dde1e6;
--charcoal-300: #c1c7cd;
--charcoal-400: #adb5bd;
--charcoal-500: #868e96;
--charcoal-600: #5c636a;
--charcoal-700: #404750;
--charcoal-800: #2d333b;
--charcoal-900: #212529;    /* anchor */
--charcoal-950: #15181c;

/* Category palette */
--green-300:  #8ce99a;
--green-500:  #51cf66;
--green-700:  #37b24d;

--purple-300: #ba79da;
--purple-500: #a551cf;
--purple-700: #8d33ba;

--orange-300: #ffc078;
--orange-500: #ff922b;
--orange-700: #f76707;

--pink-300:   #e964a4;
--pink-500:   #f0329a;
--pink-700:   #de0f80;

--yellow-300: #ebc256;
--yellow-500: #f7be1e;
--yellow-700: #dda80a;

/* Tints */
--blue-tint:   #e8f4ff;
--green-tint:  #e8f7eb;
--orange-tint: #fff1e2;
--pink-tint:   #fde6f1;
--purple-tint: #f3e8fa;
--yellow-tint: #fdf6dc;
```

Usage notes stated on the page:
- **Blue** — "Primary brand. Use 500 for buttons and active states; 600 for hover; 700+ for high-contrast text on tints."
- **Charcoal** — "Neutral chrome. 25 → page backgrounds. 900 → primary text. The original Shyft black is 900."
- **Green** — "Success, approved, healthy budget."
- **Orange** — "Warning, pending review, attention."
- **Pink** — "Danger, denied, destructive actions." (note: pink, *not* red, is the danger hue)
- **Purple** — "Category color. Internet & Phone."
- **Yellow** — "Highlight, drafts, low-priority callout."

### 1.2 Data-visualization / chart series

There is **no dedicated chart-series token set**. The page explicitly designates the category scales as the data-viz palette:

> "Brights are reserved for **data viz**, category tags, and per-app accents in the app switcher — **never primary UI chrome**."

Section heading is literally **"Data viz / category palette"**, containing green / orange / pink / purple / yellow at 300/500/700. For a multi-series chart the natural derived series order (500-weight, brand blue first) is:

| # | Token | Hex |
|---|---|---|
| 1 | `--blue-500` | `#329af0` |
| 2 | `--green-500` | `#51cf66` |
| 3 | `--orange-500` | `#ff922b` |
| 4 | `--purple-500` | `#a551cf` |
| 5 | `--pink-500` | `#f0329a` |
| 6 | `--yellow-500` | `#f7be1e` |

(300-weights are the light/dark-mode-legible variants — dark mode swaps to 300 for foreground marks, see §4.)

### 1.3 Semantic tokens — LIGHT (verbatim)

```css
--bg:            var(--charcoal-25);    /* #f8f9fa */
--bg-elev:       #ffffff;
--bg-subtle:     var(--charcoal-50);    /* #f1f3f5 */
--bg-sunken:     var(--charcoal-100);   /* #e9ecef */
--border:        var(--charcoal-100);   /* #e9ecef */
--border-strong: var(--charcoal-200);   /* #dde1e6 */
--text:          var(--charcoal-900);   /* #212529 */
--text-muted:    var(--charcoal-600);   /* #5c636a */
--text-subtle:   var(--charcoal-500);   /* #868e96 */
--accent:        var(--blue-500);       /* #329af0 */
--accent-strong: var(--blue-600);       /* #1c7cd6 */
--accent-soft:   var(--blue-tint);      /* #e8f4ff */
--on-accent:     #ffffff;
--ring:          rgba(50, 154, 240, 0.22);   /* compiled: #329af038 */

--success:       var(--green-700);      /* #37b24d */
--success-soft:  var(--green-tint);     /* #e8f7eb */
--warn:          var(--orange-500);     /* #ff922b */
--warn-soft:     var(--orange-tint);    /* #fff1e2 */
--danger:        var(--pink-700);       /* #de0f80 */
--danger-soft:   var(--pink-tint);      /* #fde6f1 */
--info:          var(--blue-500);       /* #329af0 */
--info-soft:     var(--blue-tint);      /* #e8f4ff */
```

Documented roles (from the `/clarity` "Semantic tokens" table):

| Token | Value | Role |
|---|---|---|
| `--bg` | charcoal-25 | Page background |
| `--bg-elev` | `#ffffff` | Card / panel surfaces |
| `--bg-subtle` | charcoal-50 | Hover, table header, secondary surfaces |
| `--bg-sunken` | charcoal-100 | Recessed wells, dropzones |
| `--border` | charcoal-100 | Default 1px hairlines |
| `--border-strong` | charcoal-200 | Inputs, buttons, focusable controls |
| `--text` | charcoal-900 | Primary text |
| `--text-muted` | charcoal-600 | Secondary text, descriptions |
| `--text-subtle` | charcoal-500 | Captions, metadata, placeholders |
| `--accent` | blue-500 | Primary action, links, focus |
| `--accent-soft` | blue-tint | Active nav, accent badges, focus rings |
| `--success` | green-700 | Approved, healthy, completed |
| `--warn` | orange-500 | Pending, caution |
| `--danger` | pink-700 | Denied, destructive, error |

**Rule (verbatim):** *"Always reference these in components — never the raw scale values. The semantic layer is what makes light/dark mode + per-app accents possible."*

---

## 2. Typography

### 2.1 Families

```css
--font-ui:      "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
--font-display: "Sora", "Inter", ui-sans-serif, system-ui, sans-serif;
--font-mono:    "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
```

All three are **self-hosted web fonts (WOFF2)**, served by Next.js `next/font` from `/_next/static/media/*.woff2` — *not* Google Fonts CDN, and not system stacks (the system stack is only the fallback tail). Variable-weight `@font-face` declarations:

- `Inter` — `font-weight: 100 900`, `font-display: swap`
- `Sora` — `font-weight: 100 800`, `font-display: swap`
- `JetBrains Mono` — `font-weight: 100 800`, `font-display: swap`

Preloaded latin subsets on both pages:
```
/_next/static/media/83afe278b6a6bb3c-s.p.0q-301v4kxxnr.woff2   (Inter latin)
/_next/static/media/c41ca59f1c34ba31-s.p.0xxb547n1hn74.woff2   (Sora latin)
/_next/static/media/70bc3e132a0a741e-s.p.1409xf.ylxg8g.woff2   (JetBrains Mono latin)
```
`tokens.css` carries this comment verbatim:
> *"Type — these three CSS variables are also set on `<html>` by next/font in layout.tsx with optimized fallbacks ("Inter Fallback", etc.). The class-selector version wins by specificity. The `:root` entries below act as a no-JS / no-font-load fallback."*

Stated intent: *"Two faces. **Sora** for display moments — page titles, stat values, hero headlines. Geometric and slightly rounded, it echoes the S2 mark. **Inter** for everything else — buttons, body, table rows. Numbers use the **JetBrains Mono** tabular set so columns align without forcing equal-width layouts."*

### 2.2 Type scale (as published on `/clarity`)

| Name | Size | Face | Weight |
|---|---|---|---|
| Display 40 | 40px | Sora | 600 |
| Display 28 | 28px | Sora | 600 |
| Title 22 | 22px | Sora | 600 |
| Heading 17 | 17px | Sora | 600 |
| Subtitle 16 | 16px | Inter | 500 |
| Body 14 | 14px | Inter | 400 |
| Label 12.5 | 12.5px | Inter | 500 |
| Caption 11.5 | 11.5px | Inter | 400 |
| Mono 13 | 13px | JetBrains Mono | 500 |

### 2.3 Line heights & letter spacing actually used in CSS

| Element | size / weight / line-height / tracking |
|---|---|
| `.login-side h1` (Display 40) | 40px / 600 / `line-height:1.05` / `letter-spacing:-.025em`, Sora |
| `.page-title` | 24px / 600 / `line-height:1.2` / `-.02em`, Sora |
| `.login-card h2` | 24px / 600 / `-.02em`, Sora |
| `.ds-section h2` | 22px / 600 / `-.015em`, Sora |
| `.modal-title` | 17px / 600 / `-.01em`, Sora |
| `.stat-value` | 30px / 600 / `line-height:1.1` / `-.025em`, Sora, `font-variant-numeric: tabular-nums` |
| `.card-title` | 14px / 600 |
| `.btn` | 13px / 500 / `letter-spacing:-.005em` |
| `.input/.select/.textarea` | 13.5px |
| `.page-sub`, `.ds-sub`, `.login-card .sub` | 13.5px, `--text-muted` |
| `.tbl tbody td` | 13px |
| `.tbl thead th` | 11.5px / 500 / `text-transform:uppercase` / `letter-spacing:.05em` / `--text-subtle` |
| `.tbl .num` | 12.5px, `--font-mono`, `font-variant-numeric: tabular-nums` |
| `.nav-item` | 13px / 500 |
| `.nav-label` (section header) | 10.5px / 600 / uppercase / `letter-spacing:.08em` |
| `.badge-pill`, `.tag` | 11.5px / 500 |
| `.stat-label` | 12px | 
| `.stat-meta`, `.stat-delta` | 11.5px |
| `.field-label` | 12.5px / 500 |
| `.field-help`, `.field-error` | 11.5px |
| `.segmented button` | 12.5px / 500 |
| `.crumbs` | 13px, `--text-subtle` |

There is **no `--text-*` size token set** — sizes are hard-coded per component. Only families are tokenized.

---

## 3. Spacing, radii, shadows, density

### 3.1 Spacing (4 pt grid) — verbatim
```css
--s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 20px; --s-6: 24px;
--s-7: 28px; --s-8: 32px; --s-10: 40px; --s-12: 48px; --s-16: 64px;
```
Documented intent (*"Spacing on a 4 pt base — eight named steps cover 95% of cases."*):

| Token | px | Use |
|---|---|---|
| `s-1` | 4 | inline icon padding |
| `s-2` | 8 | between inline elements |
| `s-3` | 12 | tight group |
| `s-4` | 16 | between fields, default gap |
| `s-5` | 20 | card padding |
| `s-6` | 24 | section dividers |
| `s-8` | 32 | page padding |
| `s-12` | 48 | section spacing |
| `s-16` | 64 | hero / large breathing room |

(`--s-7: 28px` and `--s-10: 40px` exist in CSS but are not in the published table.)

### 3.2 Radii — verbatim
```css
--r-sm: 6px;   /* tags, kbd, tiny chrome */
--r-md: 8px;   /* buttons, inputs, nav items */
--r-lg: 10px;  /* category icon tiles */
--r-xl: 14px;  /* cards, tables */
--r-2xl: 20px; /* modals, dialogs */
--r-full: 999px; /* pills, avatars */
```

### 3.3 Density tokens
```css
--row-h:   48px;   /* table row, comfortable */
--input-h: 38px;
--btn-h:   36px;
```
Stated: rows are **48 px comfortable / 40 px compact**; inputs **38 px (32 px compact)**; button heights **36 · 28 · 24 px**.

### 3.4 Shadows — LIGHT, verbatim
```css
--shadow-1:   0 1px 0 rgba(33,37,41,0.04), 0 1px 2px rgba(33,37,41,0.06);
--shadow-2:   0 1px 0 rgba(33,37,41,0.04), 0 4px 12px rgba(33,37,41,0.08);
--shadow-3:   0 8px 28px rgba(33,37,41,0.10), 0 2px 6px rgba(33,37,41,0.06);
--shadow-pop: 0 24px 60px rgba(33,37,41,0.16), 0 8px 20px rgba(33,37,41,0.08);
```
| Token | Use |
|---|---|
| `shadow-1` | Default cards, table wraps, stat tiles |
| `shadow-2` | Hover lift, dropdowns |
| `shadow-3` | App switcher, command palette |
| `shadow-pop` | Modals, drag preview |

**Elevation philosophy (verbatim):** *"Three layers. The system is mostly flat — shadows are a last resort, after color and border. Everything above `shadow-2` should be temporary (popovers, modals, drag)."*

---

## 4. Dark mode

**Yes.** Class-free, attribute-driven: `<html data-theme="light|dark">`, persisted in `localStorage` under the key **`internal-portal:theme`**, applied by an inline pre-hydration script. Default is `light`. There is **no `prefers-color-scheme` media query** — it is an explicit toggle only.

Dark overrides (verbatim from the compiled stylesheet; note it only redefines the *semantic* layer and shadows, never the raw scales):

```css
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

Note what does **not** change in dark: `--success` (#37b24d), `--warn` (#ff922b), `--danger` (#de0f80), `--info` (#329af0), `--ring`, all radii, spacing, density, fonts.

**Dark-mode component pattern (important for charts/badges):** foreground colored text steps *up* to the **300** weight and backgrounds become the **500 hex at ~15% alpha (`26`)** with a **~35% alpha border (`59`)**. Verbatim examples:

```css
[data-theme=dark] .badge-pill          { background:var(--charcoal-800); border-color:var(--charcoal-700); color:var(--text-muted) }
[data-theme=dark] .badge-pill.pending  { color:var(--orange-300); background:#ff922b26; border-color:#ff922b59 }
[data-theme=dark] .badge-pill.approved { color:var(--blue-300);   background:#329af026; border-color:#329af059 }
[data-theme=dark] .badge-pill.completed{ color:var(--green-300);  background:#51cf6626; border-color:#51cf6659 }
[data-theme=dark] .badge-pill.denied   { color:var(--pink-300);   background:#f0329a26; border-color:#f0329a59 }
[data-theme=dark] .stat-delta.up       { color:var(--green-300) }
[data-theme=dark] .stat-delta.down     { color:var(--pink-300) }
[data-theme=dark] .nav-item.active     { color:var(--blue-200) }
[data-theme=dark] .avatar              { color:var(--blue-200); background:#329af033 }
[data-theme=dark] ::-webkit-scrollbar-thumb { background:var(--charcoal-700); background-clip:content-box }
```

**Implication for a dashboard's chart series:** use the 500 hexes in light, the 300 hexes in dark.

---

## 5. Component conventions (dashboard-relevant)

### 5.1 Tables / leaderboard rows

Stated rule: *"Header is 11.5 px, all-caps, sticky. Rows are 48 px in comfortable mode, 40 px in compact. **Numbers right-aligned, in JetBrains Mono.**"*

```css
.tbl { border-collapse:separate; border-spacing:0; width:100% }
.tbl thead th {
  text-align:left; text-transform:uppercase; letter-spacing:.05em;
  color:var(--text-subtle); background:var(--bg-subtle);
  border-bottom:1px solid var(--border);
  padding:10px 16px; font-size:11.5px; font-weight:500;
  position:sticky; top:0;
}
.tbl tbody td { height:var(--row-h); border-bottom:1px solid var(--border);
                vertical-align:middle; padding:0 16px; font-size:13px }
.tbl tbody tr:last-child td { border-bottom:none }
.tbl tbody tr:hover td      { background:var(--bg-subtle) }
.tbl .num { font-variant-numeric:tabular-nums; font-family:var(--font-mono); font-size:12.5px }
.tbl .col-right  { text-align:right }
.tbl .col-center { text-align:center }
.tbl .row-actions{ display:flex; justify-content:flex-end; gap:4px }
```
Row hover = `--bg-subtle`; no zebra striping. Table wraps sit in a `--r-xl` (14px) card with `shadow-1`.

### 5.2 Buttons

Rule: *"One primary per surface. `secondary` for navigation between equal options. `ghost` for tertiary inline actions. `danger` for destructive confirmations."* Heights **36 · 28 · 24 px**.

```css
.btn { height:var(--btn-h); border-radius:var(--r-md); border:1px solid transparent;
       padding:0 14px; font-size:13px; font-weight:500; letter-spacing:-.005em;
       display:inline-flex; align-items:center; justify-content:center; gap:6px;
       transition:background .12s,border-color .12s,color .12s,transform 60ms }
.btn:active         { transform:translateY(.5px) }
.btn:focus-visible  { outline:2px solid var(--ring); outline-offset:2px }
.btn-primary        { background:var(--accent); color:var(--on-accent) }
.btn-primary:hover  { background:var(--accent-strong) }
.btn-secondary      { background:var(--bg-elev); border-color:var(--border-strong); color:var(--text) }
.btn-secondary:hover{ background:var(--bg-subtle) }
.btn-ghost          { background:none; color:var(--text-muted) }
.btn-ghost:hover    { background:var(--bg-subtle); color:var(--text) }
.btn-danger         { background:var(--danger); color:#fff }
.btn-danger:hover   { filter:brightness(.94) }
.btn-success        { background:var(--success); color:#fff }
.btn-success:hover  { filter:brightness(.95) }
.btn-sm { height:28px; padding:0 10px; font-size:12px;   border-radius:6px }
.btn-xs { height:24px; padding:0 8px;  font-size:11.5px; border-radius:5px }
.btn-block { width:100% }
```

### 5.3 Segmented control / toggle

Clarity's toggle idiom is a **segmented control** (`.segmented`) and a near-identical `.role-switcher`. Active segment = raised white pill on a sunken track.

```css
.segmented { display:inline-flex; padding:2px; background:var(--bg-subtle);
             border:1px solid var(--border); border-radius:var(--r-md) }
.segmented button        { height:28px; padding:0 12px; background:none; border:none;
                           border-radius:6px; color:var(--text-muted);
                           font-size:12.5px; font-weight:500; cursor:pointer }
.segmented button.active { background:var(--bg-elev); color:var(--text); box-shadow:var(--shadow-1) }

.role-switcher { display:inline-flex; align-items:center; height:32px; padding:2px;
                 background:var(--bg-subtle); border:1px solid var(--border); border-radius:var(--r-md) }
.role-switcher button        { height:26px; padding:0 10px; border-radius:6px; font-size:12px; font-weight:500 }
.role-switcher button.active { background:var(--bg-elev); color:var(--text); box-shadow:var(--shadow-1) }
```
Documented example: `All | Pending | Approved | Denied`.

### 5.4 Sliders / range inputs — **NOT DEFINED**

There is **no** `input[type=range]`, `.slider`, `.switch`, or `.toggle` styling anywhere in the system (grep count: 0), and no slider appears in the `/clarity` component inventory. **For a blend-weight slider UI this must be designed from scratch** — the closest primitives to borrow from are `.progress` (6 px track, `999px` radius, `--bg-subtle` track / `--accent` fill) and the focus-ring convention (`box-shadow: 0 0 0 3px var(--ring)`).

```css
/* the nearest existing analogue — a progress meter */
.progress          { height:6px; background:var(--bg-subtle); border-radius:999px; overflow:hidden }
.progress > div    { height:100%; background:var(--accent); border-radius:inherit; transition:width .24s }
.progress.warn    > div { background:var(--orange-500) }
.progress.danger  > div { background:var(--pink-700) }
.progress.success > div { background:var(--green-700) }
.progress-row .pct { width:40px; text-align:right; font-family:var(--font-mono);
                     color:var(--text-muted); font-size:12px }
```

### 5.5 Cards

*"Three card types. **Stat card** for single metrics. **Content card** for grouped content with a header. **Action card** for items in a grid."* Body padding 20 px; header sticky inside scrollable cards.

```css
.card         { background:var(--bg-elev); border:1px solid var(--border);
                border-radius:var(--r-xl); box-shadow:var(--shadow-1) }
.card-header  { display:flex; align-items:center; gap:12px; padding:16px 20px;
                border-bottom:1px solid var(--border) }
.card-title   { margin:0; font-size:14px; font-weight:600 }
.card-sub     { margin:0; font-size:12.5px; color:var(--text-muted) }
.card-body    { padding:20px }
.card-actions { display:flex; gap:8px; margin-left:auto }
```

### 5.6 Stat tiles (KPI row)

*"The hero number reads in Sora; supporting numbers stay in mono. Use deltas sparingly and only when comparison is requested."*

```css
.stats-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px }
.stat-card  { background:var(--bg-elev); border:1px solid var(--border);
              border-radius:var(--r-xl); box-shadow:var(--shadow-1); padding:18px 20px }
.stat-label { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-muted) }
.stat-value { font-family:var(--font-display); font-size:30px; font-weight:600;
              line-height:1.1; letter-spacing:-.025em;
              font-variant-numeric:tabular-nums; margin-top:6px }
.stat-value.muted { color:var(--text-muted) }
.stat-meta  { display:flex; align-items:center; gap:6px; margin-top:8px;
              font-size:11.5px; color:var(--text-subtle) }
.stat-delta { display:inline-flex; align-items:center; gap:3px; font-size:11.5px; font-weight:500 }
.stat-delta.up   { color:var(--green-700) }
.stat-delta.down { color:var(--pink-700) }
```

### 5.7 Badges & tags

*"Pills carry one piece of state — never two. Tags are softer, used for category and metadata."*

```css
.badge-pill { display:inline-flex; align-items:center; gap:6px; padding:2px 9px;
              border-radius:var(--r-full); background:var(--bg-subtle);
              color:var(--text-muted); border:1px solid var(--border);
              font-size:11.5px; font-weight:500 }
.badge-pill .dot-mini { width:6px; height:6px; border-radius:999px;
                        background:currentColor; opacity:.85 }
.badge-pill.pending   { background:var(--orange-tint); color:var(--orange-700); border-color:#ff922b4d }
.badge-pill.approved  { background:var(--blue-tint);   color:var(--blue-700);   border-color:#329af040 }
.badge-pill.completed { background:var(--green-tint);  color:var(--green-700);  border-color:#37b24d4d }
.badge-pill.denied    { background:var(--pink-tint);   color:var(--pink-700);   border-color:#de0f804d }

.tag { display:inline-flex; align-items:center; gap:4px; padding:1px 7px;
       border-radius:5px; background:var(--bg-subtle); border:1px solid var(--border);
       color:var(--text-muted); font-size:11.5px; font-weight:500 }
.tag-tone-blue   { background:var(--blue-tint);   color:var(--blue-700);   border-color:#329af033 }
.tag-tone-green  { background:var(--green-tint);  color:var(--green-700);  border-color:#37b24d33 }
.tag-tone-orange { background:var(--orange-tint); color:var(--orange-700); border-color:#ff922b33 }
.tag-tone-pink   { background:var(--pink-tint);   color:var(--pink-700);   border-color:#de0f8033 }
.tag-tone-purple { background:var(--purple-tint); color:var(--purple-700); border-color:#8d33ba33 }
.tag-tone-yellow { background:var(--yellow-tint); color:var(--yellow-700); border-color:#dda80a40 }
```
Pattern: **tint background + 700 text + 500-hex-at-20%-alpha border**.

### 5.8 Inputs & focus

Rule: *"38 px tall (32 px in compact). Same radius as buttons. Focus uses a **3-px ring at the accent hue / 22 % opacity — never thicker**."*

```css
.input,.select,.textarea { height:var(--input-h); width:100%; padding:0 12px;
  border:1px solid var(--border-strong); background:var(--bg-elev); color:var(--text);
  border-radius:var(--r-md); font-size:13.5px;
  transition:border-color .12s, box-shadow .12s }
.input:focus,.select:focus,.textarea:focus {
  border-color:var(--accent); box-shadow:0 0 0 3px var(--ring); outline:none }
.textarea { height:auto; min-height:88px; padding:10px 12px; resize:vertical; font-family:inherit }
.input::placeholder,.textarea::placeholder { color:var(--text-subtle) }
.select { appearance:none; padding-right:30px;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'><path fill='none' stroke='%23868e96' stroke-width='1.5' d='M6 8l4 4 4-4'/></svg>");
  background-position:right 8px center; background-repeat:no-repeat }

.radio-card         { padding:12px 14px; border:1px solid var(--border-strong);
                      background:var(--bg-elev); border-radius:var(--r-md); cursor:pointer }
.radio-card.checked { border-color:var(--accent); background:var(--accent-soft) }
.radio-card .dot    { width:16px; height:16px; border:1.5px solid var(--border-strong); border-radius:999px }
.radio-card.checked .dot::after { content:""; width:8px; height:8px; border-radius:999px; background:var(--accent) }
```

### 5.9 App shell / page header / nav

```css
.sidebar   { background:var(--bg-elev); border-right:1px solid var(--border);
             height:100vh; position:sticky; top:0; display:flex; flex-direction:column }
.topbar    { height:56px; padding:0 28px; background:var(--bg-elev);
             border-bottom:1px solid var(--border); position:sticky; top:0; z-index:10 }
.nav-item          { padding:7px 10px; border-radius:var(--r-md);
                     color:var(--text-muted); font-size:13px; font-weight:500 }
.nav-item:hover    { background:var(--bg-subtle); color:var(--text) }
.nav-item.active   { background:var(--accent-soft); color:var(--accent-strong) }
.nav-label         { font-size:10.5px; font-weight:600; text-transform:uppercase;
                     letter-spacing:.08em; color:var(--text-subtle); padding:6px 10px 4px }
.page-header { display:flex; align-items:flex-start; gap:16px; margin-bottom:24px }
.page-title  { font-family:var(--font-display); font-size:24px; font-weight:600;
               line-height:1.2; letter-spacing:-.02em; margin:0 }
.page-sub    { margin-top:4px; font-size:13.5px; color:var(--text-muted) }
.page-header-actions { display:flex; align-items:center; gap:8px; margin-left:auto }
```
Page header rule: *"Title in Sora, subtitle in Inter muted, primary action right-aligned. Title and primary action share a baseline."*

### 5.10 Empty states & modals

- Empty state: *"Center content, hint the next action, never apologize. Icon → title → one sentence → action."* Title 15px/600, sub 13px.
- Modals: *"Use sparingly. Modals are for confirmations, single-task forms, and content that doesn't deserve its own page. The footer is on a subtle background to anchor the primary action."* `--r-2xl` (20px), `--shadow-pop`, title 17px Sora/600.

---

## 6. Voice & tone (documented, verbatim)

> "Internal tools. Be useful before being friendly. Direct verbs in titles, sentence case in body, never apologize for product behavior the user didn't cause."

| DO | DON'T |
|---|---|
| "Submit request" | "Submit Your Awesome Request! ✨" |
| "9 awaiting decision" | "You have 9 pending items that need your attention" |
| "Over your remaining budget" | "Oops! That's over budget 😬" |
| "Reset Apr 1, 2027" | "Resets on April 1st, 2027 at 12:00 AM UTC" |
| "Nothing here yet — when someone submits a request, it'll show up here." | "No requests found. Please try a different filter." |

## 6b. Brand mark rules (for completeness)

- **S2 monogram** = primary mark, used in app chrome / favicons at **22–44 px**. Currently bitmap PNG (`/s2-mark.png`); *"SVG should ship before v1."*
- **SHYFT SOLUTIONS lockup** (`/shyft-solutions-lockup.png`) = formal corporate identity — *"Use only on login screens, marketing surfaces, business cards, and external documents. Never inside product chrome."* Tagline: "The Science of Software."
- Clearspace: *"keep clearspace equal to the height of the 'S' stem around the entire mark."*
- DO: two-tone charcoal `#212529` + blue `#329af0`, uniform scaling, solid backgrounds.
- DON'T: single-color fill, stretch/skew/rotate, place over busy imagery without a solid backplate.

---

## 7. Is there a directly-usable CSS file or npm package?

**CSS file: YES.** Public, no-auth, ETag-cached:

```
GET https://portal.internal.shyftsolutions.io/api/v1/dev-guide/tokens.css   →  text/css
```

The `create-a-new-app` guide's recommended integration (verbatim):
> *"`@import` it (or inline it at build) and map the CSS variables into your Tailwind theme via `@theme inline`, exactly as the portal's own `globals.css` does. Your `--bg-elev`, `--accent`, `--font-display`, etc. then track the portal's. The endpoint is public and ETag-cached, so a build step can re-fetch it cheaply."*

**Caveat: `tokens.css` ships the LIGHT `:root` block only.** The `[data-theme=dark]` overrides are *not* in it — they live in the portal's compiled stylesheet (`/_next/static/chunks/0rb6s03zltg8d.css`). Dark values are transcribed verbatim in §4 above and must be copied by hand.

**npm package: NO.** Callout verbatim, titled *"Tokens, not a component library — yet"*:
> *"Today the shared surface is the **token set** (`tokens.css`) plus the `/clarity` reference. There's no published Clarity component package to install, so match the tokens and mirror the component patterns from `/clarity` by hand. A shippable component library is future work."*

The only npm-installable Shyft package found is unrelated to design — `shyft-auth-js`, installed from a git URL:
`npm install "git+ssh://git@github.com/ShyftSolutions/shyft-auth-js.git#v0.1.0"`.

**Fonts:** self-hosted via `next/font` from the portal's own `/_next/static/media/`. To reproduce outside the portal, install `inter`, `sora`, `jetbrains-mono` from Google Fonts / Fontsource yourself — the portal's WOFF2 URLs are content-hashed and not a stable public font CDN.

### Full API surface (from `/api/v1/dev-guide/capabilities`)

| Endpoint | Returns |
|---|---|
| `GET /api/v1/dev-guide/capabilities` | JSON index of every endpoint |
| `GET /api/v1/dev-guide/docs` | Every public guide (slug, title, tags, paths) |
| `GET /api/v1/dev-guide/docs/{slug}` | Raw MDX of one guide (`text/markdown`) |
| `GET /api/v1/dev-guide/search?q=…` | Substring scan across all guides |
| `GET /api/v1/dev-guide/tokens.css` | The design tokens |

Features block: `{"auth":"public","search":"substring","etag":true,"conditionalRequests":true}`

---

## 8. Gaps to resolve for a Bhar dashboard

1. **No slider / range-input styling** — blend-weight controls must be designed; borrow `.progress` geometry + the 3px `--ring` focus convention.
2. **No chart-series token set** — use the category palette (§1.2), 500 in light / 300 in dark.
3. **No font-size tokens** — only families are tokenized; sizes are per-component literals (§2.3).
4. **`tokens.css` omits dark mode** — copy the `[data-theme=dark]` block from §4.
5. **No axis/gridline/tooltip tokens** — nearest fits: gridlines `--border`, axis labels `--text-subtle`, tooltip surface `--bg-elev` + `--shadow-3`.
6. **Theme switching contract:** `data-theme` attribute on `<html>`, `localStorage` key `internal-portal:theme`, default `light`, no `prefers-color-scheme` fallback.
