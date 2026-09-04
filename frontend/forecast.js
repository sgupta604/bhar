/* forecast.js — the forward-forecast page. Plain script, globals only.

   ONE FILE, ON PURPOSE. Splitting the renderer into a second module is the
   obvious refactor and is explicitly not wanted: the page ships exactly three
   non-empty forecast.* files (html, css, js) and a gate counts them. Keep the
   renderer here.

   No imports, no bundler, no framework, no <script type="module">. The sibling
   demo-path files (app.js, models.js, format.js, chart.js, theme.js) are read
   for pattern only and are never loaded by forecast.html.

   THE ARCHITECTURE RULE (forecast.html states it too): the markup is always
   present; visibility is a CSS rule keyed on an attribute on <html>. This file
   calls setAttribute when a condition holds and leaves the attribute ABSENT
   when it does not. It never writes style.display, and it never writes a
   negated string into a state attribute — a selector matching a true value
   does not match a negated one, so absent is the only off state there is.

   NOTHING IN THIS FILE IS A PAYLOAD LITERAL. No model name, no site name, no
   cell count, no temperature, no unit string. Every one of those is computed,
   because the page is rendered against two payloads that disagree on all of
   them, and a shortcut that renders one correctly lies about the other. */
(function () {
  'use strict';

  /* ── 3.1 API base, formatter, small helpers ─────────────────────────── */

  /* The only place the default port is written down. Mirrors app.js:9. */
  var API_BASE = new URLSearchParams(location.search).get('api') || 'http://localhost:8000';

  /* Byte-identical to the key in the pre-hydration snippet in forecast.html
     and to the one the portal's shared theme script uses. A test asserts it. */
  var THEME_KEY = 'internal-portal:theme';

  /* The horizon the full step grid reaches when every model publishes. Below
     it the truncated-horizon note renders; it is a comparison threshold, not a
     cell count, and the cell count is never a constant anywhere in this file. */
  var FULL_HORIZON_H = 48;

  /* Strip geometry literals from the design target: cell minimum width and the
     column gap, both in px. Used only to compute how many columns fit. */
  var CELL_MIN_PX = 108;
  var CELL_GAP_PX = 8;
  var COLS_MIN = 4;
  var COLS_MAX = 8;

  /* One shared formatter, one place. toFixed and Intl both emit an ASCII
     hyphen for negatives in en-US; the hyphen is narrower than a digit even in
     a tabular face and breaks the column it sits in, so the substitution to a
     real U+2212 minus happens here and at no call site.

     Never Math.abs. Never clamped. Never a CSS ::before sign — a sign drawn by
     a pseudo-element does not survive copy-paste out of the page, and a
     presenter who pastes a number into a chat window must paste the sign. */
  var MINUS = '−';
  var fmt = function (v, dp, signed) {
    var n = Number(v);
    if (!isFinite(n)) return '';
    return ((signed && n > 0) ? '+' : '') + n.toFixed(dp).replace('-', MINUS);
  };

  /* meta.units carries the unit; the glyph is derived from it, never retyped
     as an independent literal that a units change would leave behind. */
  function unitSymbol(units) {
    return String(units == null ? '' : units).replace(/^deg/, '°');
  }

  /* Values are rendered as "<value><space><unit>" — a real space, in the text
     node, so the unit survives a copy-paste with the number. */
  function withUnit(text, units) {
    return text + ' ' + unitSymbol(units);
  }

  var WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /* UTC everywhere. toLocaleString is never used on this page: a presenter in
     one timezone and a viewer in another must read the same cycle. */
  function utcStamp(iso) {                    // 2026-09-04 12:00Z
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()) +
      ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + 'Z';
  }
  function utcPretty(iso) {                   // Thu 4 Sep · 18:00Z
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return WD[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MO[d.getUTCMonth()] +
      ' · ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + 'Z';
  }
  function utcShort(iso) {                    // Fri 18:00Z
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return WD[d.getUTCDay()] + ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + 'Z';
  }
  function utcDate(iso) {                     // 2026-08-04
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  }
  function utcMonthName(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return MONTH_LONG[d.getUTCMonth()];
  }

  /* Whole hours, floored — the run label and the stale pill both read it. */
  function hoursOld(ageMinutes) {
    var n = Number(ageMinutes);
    if (!isFinite(n)) return 0;
    return Math.floor(n / 60);
  }

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* A model's colour is always handed to CSS as the REFERENCE STRING
     var(--model-<name>) — never a hex resolved with getComputedStyle.
     This is the memoization trap documented at app.js:508-524: the demo page
     bakes resolved hexes inline, so its theme toggle has to drop a cached
     colour map and re-render every panel that carries a mark. A reference
     resolves at paint time in whatever theme is current, which is why the
     theme flip on this page is free and why this page needs no colour reset. */
  function modelVar(model) {
    return 'var(--model-' + String(model).toLowerCase() + ')';
  }

  /* ── state ──────────────────────────────────────────────────────────── */

  var state = {
    data: null,
    meta: null,
    slots: [],          // one per forward step, in time order, never sparse
    cols: COLS_MAX,
    overflow: false,
    domain: 0,          // max(member_spread_f) over the payload — the shared axis
    firstExtrapIdx: -1,
    currentIdx: 0,      // the step the headline shows
    selected: 0,
    pinned: 0
  };

  /* ── boot + 3.1 error path (the shape of app.js:29-43) ──────────────── */

  fetch(API_BASE + '/api/forecast')
    .then(function (r) {
      if (!r.ok) {
        return r.text().then(function (body) {
          var detail = body;
          try { var j = JSON.parse(body); if (j && j.detail) detail = j.detail; } catch (e) { /* raw body */ }
          throw { userDetail: String(detail), status: r.status };
        });
      }
      return r.json();
    })
    .then(function (payload) { boot(payload); })
    .catch(function (err) {
      renderEmptyState(err && err.userDetail ? err.userDetail
        : (err && err.message ? err.message : String(err)));
    });

  mountTheme();      // works with or without a payload, so the 503 page toggles too

  function boot(payload) {
    state.data = payload;
    state.meta = payload.meta;
    applySynthetic(payload.meta);
    applyStale(payload.meta);
    try {
      buildSlots(payload);
    } catch (e) {
      /* A short or doubled join renders a fake-perfect page: an empty strip
         scores no gaps and no boundary and looks complete. Fail loudly. */
      renderEmptyState(e && e.message ? e.message : String(e));
      return;
    }
    renderHeader();
    renderHeadline();
    renderRunLabel($('cycle-run-label'), payload.meta);
    renderSkillShell();
    layoutStrip();
    renderNote();
    selectCell(0, true);          // the panel is never empty on first paint
    window.addEventListener('resize', onResize);
  }

  /* ── 3.2 the grid merge ─────────────────────────────────────────────── */

  function buildSlots(payload) {
    var meta = payload.meta;
    var nSteps = Math.round(Number(meta.horizon_h) / Number(meta.step_h));
    if (!isFinite(nSteps) || nSteps < 1) {
      throw new Error('Grid merge failed: horizon_h / step_h did not yield a usable step count ' +
        '(horizon_h=' + meta.horizon_h + ', step_h=' + meta.step_h + '). Refusing to render a strip.');
    }

    var t0 = Date.parse(meta.cycle.init_time);
    if (isNaN(t0)) {
      throw new Error('Grid merge failed: meta.cycle.init_time is not parseable (' +
        meta.cycle.init_time + '). Refusing to render a strip.');
    }

    var slots = [], byKey = {}, i;
    for (i = 1; i <= nSteps; i++) {
      var key = t0 + i * Number(meta.step_h) * 3600000;
      var slot = {
        key: key,
        idx: i - 1,
        lead_h: Number(meta.step_h) * i,
        valid_time: new Date(key).toISOString().replace('.000Z', 'Z'),
        kind: null,
        row: null,
        fills: 0
      };
      slots.push(slot);
      byKey[key] = slot;
    }

    /* THE ASSERTION. This is the frontend twin of the project's "assert on join
       match counts" rule. forecast[] and gaps[] must together cover every step
       on the grid EXACTLY ONCE — never twice, never zero times, and no row may
       sit off the grid. An empty or short join renders a fake-perfect page. */
    var offGrid = [];
    function place(row, kind) {
      var s = byKey[Date.parse(row.valid_time)];
      if (!s) { offGrid.push(String(row.valid_time)); return; }
      s.fills += 1;
      s.kind = kind;
      s.row = row;
    }
    (payload.forecast || []).forEach(function (r) { place(r, 'forecast'); });
    (payload.gaps || []).forEach(function (r) { place(r, 'gap'); });

    var doubled = 0, empty = 0;
    slots.forEach(function (s) {
      if (s.fills > 1) doubled += 1;
      if (s.fills === 0) empty += 1;
    });
    if (doubled || empty || offGrid.length) {
      throw new Error('Grid merge failed: forecast[] (' + (payload.forecast || []).length +
        ' rows) and gaps[] (' + (payload.gaps || []).length + ' rows) do not cover the ' +
        nSteps + '-step grid exactly once — ' + empty + ' step(s) uncovered, ' +
        doubled + ' step(s) covered twice, ' + offGrid.length + ' row(s) off the grid' +
        (offGrid.length ? ' (' + offGrid.join(', ') + ')' : '') +
        '. Refusing to render a partial strip.');
    }

    /* The band comes from each row's weights_fitted_at_lead_h and the boundary
       from each row's is_extrapolated_lead — both READ, never recomputed.
       meta.fitted_leads does not exist; meta.weights_source.fitted_leads does,
       but the per-row fields are the contract-validated ones and recomputing
       client-side would create a second source of truth that can disagree with
       the pixels. A gap carries neither field, and gets neither treatment. */
    state.slots = slots;
    state.firstExtrapIdx = -1;
    state.currentIdx = 0;
    var domain = 0, seenCurrent = false;
    slots.forEach(function (s) {
      if (s.kind !== 'forecast') return;
      if (!seenCurrent) { state.currentIdx = s.idx; seenCurrent = true; }
      if (s.row.is_extrapolated_lead === true && state.firstExtrapIdx < 0) {
        state.firstExtrapIdx = s.idx;
      }
      var sp = Number(s.row.member_spread_f);
      if (isFinite(sp) && sp > domain) domain = sp;
    });
    state.domain = domain;
  }

  /* ── 3.3 state attributes and the theme toggle ──────────────────────── */

  /* Three effects, one boolean, zero display writes. The boolean itself, never
     a string compare: a negated string literal is still truthy and would raise
     the banner over real data. Pattern: app.js:56-64. */
  function applySynthetic(meta) {
    if (!meta.is_synthetic) return;      // attribute absent => banner, frame, prefix all vanish
    document.documentElement.setAttribute('data-synthetic', 'true');
    document.title = '[SYNTHETIC] ' + document.title;
    $('synthetic-banner').textContent =
      'SYNTHETIC FORECAST DATA — these numbers are fabricated. Not a real NOAA cycle. Generated ' +
      meta.generated_at + '.';
  }

  /* Read from meta.cycle.is_stale ALONE. The page never recomputes staleness;
     the server owns the rule and the page owns the pixels. */
  function applyStale(meta) {
    var c = meta.cycle || {};
    if (!c.is_stale) return;             // absent attribute => every stale rule is inert
    document.documentElement.setAttribute('data-stale', 'true');
    var behind = Number(c.cycles_fallen_back) || 0;
    $('cycle-stale-text').textContent = behind > 0
      ? 'Stale · ' + behind + ' cycle(s) behind target'
      : 'Stale · ' + hoursOld(c.age_minutes) + ' h old';
    /* Server-authored text, typeset as machine output: verbatim, never
       truncated, never paraphrased, never wrapped in friendlier words. */
    $('cycle-stale-reason').textContent = c.stale_reason == null ? '' : String(c.stale_reason);
  }

  function mountTheme() {
    var root = document.documentElement;
    var btns = [$('theme-light'), $('theme-dark')].filter(Boolean);
    function sync() {
      var cur = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      btns.forEach(function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-theme-value') === cur ? 'true' : 'false');
      });
    }
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        var v = b.getAttribute('data-theme-value');
        root.setAttribute('data-theme', v);
        /* localStorage throws outright in some private-window and
           blocked-storage configurations. It must never take the page down. */
        try { localStorage.setItem(THEME_KEY, v); } catch (e) { /* non-fatal */ }
        sync();
      });
    });
    sync();                              // adopt whatever the pre-hydration script set
  }

  /* ── 3.4 header, headline, the permanent run label ──────────────────── */

  function renderHeader() {
    var meta = state.meta, site = meta.site;
    $('header-title').textContent = 'Forecast — ' + site.name + ' (' + site.id + ')';
    /* Composed from meta.site, never retyped: a hardcoded name survives a site
       change that nothing else survives. */
    $('header-site').textContent = site.id + ' · ' + site.name;
    $('header-scope').textContent = String(meta.variable).replace(/_/g, ' ') + ' · ' +
      meta.units + ' · next ' + meta.horizon_h + ' h at ' + meta.step_h + ' h steps';

    var nGaps = (state.data.gaps || []).length;
    $('strip-sub').textContent = state.slots.length + ' steps · ' + meta.step_h + ' h grid · ' +
      meta.horizon_h + ' h horizon' + (nGaps ? ' · ' + nGaps + ' gap(s)' : '');
  }

  /* One blend value, for the nearest forward step — the first forecast[] row by
     valid_time, i.e. the smallest lead_h present. Not an average, not a range,
     not a next-24-h summary. */
  function renderHeadline() {
    var meta = state.meta;
    var slot = state.slots[state.currentIdx];
    if (!slot || slot.kind !== 'forecast') return;
    $('headline-label').textContent = 'Next step · ' + slot.row.lead_h + ' h lead · ' +
      utcPretty(slot.row.valid_time);
    $('headline-value').textContent = withUnit(fmt(slot.row.blend_f, 1), meta.units);
  }

  /* PERMANENT CHROME. Visible in all four states — fresh, stale, synthetic, and
     beside the empty state wherever a cycle is knowable. Never a warning badge;
     under staleness the CSS recolours it, it never appears or disappears. */
  function renderRunLabel(host, meta) {
    if (!host) return;
    var c = (meta && meta.cycle) || {};
    if (!c.init_time) { host.textContent = ''; return; }
    host.textContent = 'Run ' + utcStamp(c.init_time) + ' · ' + hoursOld(c.age_minutes) + ' h old';
  }

  /* ── 3.5 the strip ──────────────────────────────────────────────────── */

  /* cols = clamp(4, floor((available + gap) / (cellMin + gap)), 8).
     Where more than one count sits inside the clamp, prefer the one that puts
     the fitted-range boundary on a row edge — but never give up more than one
     column for it: two columns of density costs more legibility than the
     row-edge alignment is worth, and the mid-row boundary form is specified to
     be correct anyway. Below the 4-column floor the container scrolls. */
  function computeCols() {
    var strip = $('forecast-strip');
    var avail = strip ? strip.clientWidth : 0;
    if (!avail) {
      /* Pre-layout fallback: page width minus page padding, the side panel and
         the column gap, matching the design target's own budget. */
      avail = Math.max(0, (document.documentElement.clientWidth || 1440) - 64 - 380 - 24);
    }
    var fit = Math.floor((avail + CELL_GAP_PX) / (CELL_MIN_PX + CELL_GAP_PX));
    if (fit < COLS_MIN) { state.cols = COLS_MIN; state.overflow = true; return; }

    var maxCols = Math.min(COLS_MAX, fit);
    var candidates = [maxCols];
    if (maxCols - 1 >= COLS_MIN) candidates.push(maxCols - 1);
    var chosen = maxCols;
    if (state.firstExtrapIdx >= 0) {
      for (var i = 0; i < candidates.length; i++) {
        if (state.firstExtrapIdx % candidates[i] === 0) { chosen = candidates[i]; break; }
      }
    }
    state.cols = chosen;
    state.overflow = false;
  }

  var resizeTimer = null;
  function onResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var before = state.cols, overflowBefore = state.overflow;
      computeCols();
      if (state.cols === before && state.overflow === overflowBefore) return;
      renderStrip();
      selectCell(state.pinned, true);
    }, 120);
  }

  function layoutStrip() {
    computeCols();
    renderStrip();
  }

  /* A run of cells sharing a bracket. Split on the weight band AND on the
     extrapolated flag, so the bracket that carries the mid-row boundary starts
     exactly at the first extrapolated cell and its 2px left edge lines up with
     the cell's. A gap is its own group: it has no weights, so no band label. */
  function groupKey(slot) {
    if (slot.kind !== 'forecast') return 'gap:' + slot.key;
    return 'b' + slot.row.weights_fitted_at_lead_h + ':' +
      (slot.row.is_extrapolated_lead === true ? 'x' : 'f');
  }

  function renderStrip() {
    var strip = $('forecast-strip');
    var meta = state.meta;
    var slots = state.slots;
    var cols = state.cols;

    strip.textContent = '';
    strip.style.setProperty('--strip-cols', String(cols));
    /* The member axis domain, set ONCE on the container so every cell shares
       one scale. A per-cell normalization would make every step look equally
       spread and destroy the comparison between them. */
    strip.style.setProperty('--spread-domain', fmt(state.domain, 1));
    if (state.overflow) strip.setAttribute('data-overflow', 'scroll');
    else strip.removeAttribute('data-overflow');
    strip.setAttribute('aria-label', 'Forward forecast, ' + slots.length + ' steps');

    /* The boundary is drawn IFF any cell is extrapolated — a consequence of the
       data, never decoration that is always present. When it is drawn, all
       three parts are drawn: the rule, the label, and the per-cell treatment
       with an UNVERIFIED flag on the first extrapolated cell of each visual row
       (so any single-row crop still carries the word). */
    var hasBoundary = state.firstExtrapIdx >= 0;
    var rowEdge = hasBoundary && (state.firstExtrapIdx % cols === 0);

    for (var start = 0; start < slots.length; start += cols) {
      var end = Math.min(start + cols, slots.length);

      /* Boundary form 1 — the break falls on a row edge: a full-width rule
         carrying the label, between the two rows. */
      if (hasBoundary && rowEdge && state.firstExtrapIdx === start) {
        strip.appendChild(el('div', 'strip-boundary', 'Beyond the fitted range'));
      }

      var row = el('div', 'strip-row');
      var bands = el('div', 'strip-bands');
      var cells = el('div', 'strip-cells');

      var i = start;
      while (i < end) {
        var k = groupKey(slots[i]);
        var j = i;
        while (j < end && groupKey(slots[j]) === k) j += 1;
        var band = el('div', 'strip-band');
        band.style.setProperty('--band-span', String(j - i));
        var head = slots[i];
        if (head.kind === 'forecast') {
          band.textContent = 'Weights fitted at ' + head.row.weights_fitted_at_lead_h + ' h';
          /* Boundary form 2 — the break falls mid-row: the 2px edge lands on
             the cell and on its bracket, and the label rides the bracket. */
          if (hasBoundary && !rowEdge && state.firstExtrapIdx === i) {
            band.setAttribute('data-boundary-start', 'true');
            band.textContent = band.textContent + ' · Beyond the fitted range';
          }
        }
        bands.appendChild(band);
        i = j;
      }

      var firstExtrapInThisRow = -1;
      for (i = start; i < end; i++) {
        var s = slots[i];
        if (s.kind === 'forecast' && s.row.is_extrapolated_lead === true) {
          firstExtrapInThisRow = i;
          break;
        }
      }

      for (i = start; i < end; i++) {
        cells.appendChild(makeCell(slots[i], meta, {
          rowEdge: rowEdge,
          flagHere: i === firstExtrapInThisRow
        }));
      }

      row.appendChild(bands);
      row.appendChild(cells);
      strip.appendChild(row);
    }

    /* Delegated once, on the container: a re-layout replaces every cell, and
       re-binding per render would stack duplicate handlers. */
    if (!strip.hasAttribute('data-bound')) {
      strip.setAttribute('data-bound', 'true');
      strip.addEventListener('focusin', onStripFocusIn);
      strip.addEventListener('click', onStripClick);
    }
  }

  function makeCell(slot, meta, opt) {
    var b = document.createElement('button');
    b.type = 'button';                    // in the tab order by construction
    b.className = 'strip-cell' + (slot.kind === 'gap' ? ' is-gap' : '');
    b.setAttribute('data-idx', String(slot.idx));
    b.setAttribute('aria-pressed', 'false');

    b.appendChild(el('span', 'strip-lead', slot.lead_h + ' h'));
    b.appendChild(el('span', 'strip-time', utcShort(slot.valid_time)));

    if (slot.kind === 'gap') { fillGapCell(b, slot); return b; }

    var row = slot.row;
    var extrap = row.is_extrapolated_lead === true;

    /* Band read off the payload, never recomputed. A neutral ordinal ladder —
       never a model colour: the bands are not models, and a model colour on
       cell chrome would collide with the member marks that do carry identity. */
    b.setAttribute('data-band', String(row.weights_fitted_at_lead_h));
    if (extrap) {
      b.setAttribute('data-extrapolated', 'true');
      b.setAttribute('aria-describedby', 'skill-beyond-fitted');
      if (opt.flagHere) b.appendChild(el('span', 'strip-flag', 'UNVERIFIED'));
      if (!opt.rowEdge && slot.idx === state.firstExtrapIdx) {
        b.setAttribute('data-boundary-start', 'true');
      }
    }
    if (slot.idx === state.currentIdx) b.setAttribute('data-current', 'true');

    var value = el('span', 'strip-value', fmt(row.blend_f, 1));
    value.appendChild(el('span', 'strip-unit', ' ' + unitSymbol(meta.units)));
    b.appendChild(value);

    /* ── Member marks ────────────────────────────────────────────────────
       Four discrete marks in their own row, on their own axis, below the value
       and detached from it. TWO RESTRICTIONS, restated here because this is
       where they get broken:

       1. Nothing is drawn around blend_f — no band, no ribbon, no shaded
          envelope, no whisker, no geometry of any kind attached to the blend
          value. blend_f is NEVER plotted on the member axis: the moment it
          appears there the four marks become a range around it, which is the
          same claim by another route.
       2. member_spread_f renders in degrees F, labelled "Model spread", and is
          never converted into a percentage. Disagreement between models is not
          calibrated skill and the page must not imply that it is.

       Nothing is filled between the marks. */
    var members = row.members || {};
    var names = meta.models_included || Object.keys(members);
    var lo = null;
    names.forEach(function (m) {
      var v = Number(members[m]);
      if (isFinite(v) && (lo === null || v < lo)) lo = v;
    });
    var band = el('div', 'strip-members');
    names.forEach(function (m) {
      var mark = el('span', 'strip-mark');
      var v = Number(members[m]);
      /* Guard the degenerate case: when every model agrees the domain is 0 and
         the division is undefined. Every mark then sits at the left anchor. */
      var pos = (state.domain > 0 && isFinite(v) && lo !== null) ? (v - lo) / state.domain : 0;
      mark.style.setProperty('--mark-pos', String(pos));
      mark.style.setProperty('--mark-color', modelVar(m));
      /* De-emphasis is computed per cell from the weight, never from a model
         name: today's zero-weight model is not necessarily tomorrow's, and the
         two payloads this page renders disagree about which one it is. The
         mark is shown, de-emphasised, and never dropped — the weight is a real
         fitted result and the page shows findings. */
      if (Number(row.weights[m]) === 0) mark.setAttribute('data-zero-weight', 'true');
      mark.setAttribute('aria-hidden', 'true');
      band.appendChild(mark);
    });
    b.appendChild(band);

    b.setAttribute('aria-label', 'Lead ' + row.lead_h + ' hours, ' +
      withUnit(fmt(row.blend_f, 1), meta.units) + (extrap ? ', unverified' : ''));
    return b;
  }

  /* ── The gap cell ────────────────────────────────────────────────────
     Visibly absent — not an empty slot, not a blank, not a shorter strip. It
     states missing_models and reason on its face. No member marks, no spread,
     no data-band and no data-extrapolated: a gap has no weights, and that holds
     even for a gap that lies past the fitted-range boundary. Extrapolated means
     "we have a number and nothing measured it"; a gap means "we do not have a
     number", and the two must not share a visual language.

     THE THREE NEVERS, in words because CSS cannot enforce them:
       A gap is never interpolated across.
       A gap is never back-filled from an earlier cycle, a neighbouring step or
       a fallback model.
       A gap is never renormalized over the remaining models.
     The third will be proposed as a fix, so it earns its own sentence: a
     three-model renormalization is a different blend than the one that was
     fitted, and none of the skill numbers on this page apply to it. Every
     figure in the trust panel was measured on a four-model vector; dropping one
     model and rescaling the rest to sum to 1.0 produces a number with no
     backtest behind it, displayed under a panel that appears to vouch for it.
     A gap is honest; a substituted blend is not. */
  function fillGapCell(b, slot) {
    var g = slot.row;
    b.appendChild(el('span', 'strip-value', '—'));   // where blend_f would be. No number.

    var miss = el('div', 'strip-missing');
    (g.missing_models || []).forEach(function (m) {
      var chip = el('span', 'strip-missing-chip', m);
      chip.style.setProperty('--mark-color', modelVar(m));
      miss.appendChild(chip);
    });
    b.appendChild(miss);
    b.appendChild(el('div', 'strip-reason', String(g.reason == null ? '' : g.reason)));

    b.setAttribute('aria-label', 'Lead ' + slot.lead_h + ' hours, no data, missing ' +
      (g.missing_models || []).join(', '));
  }

  /* ── 3.6 detail panel and the keyboard contract ─────────────────────── */

  function cellFromEvent(e) {
    var n = e.target;
    while (n && n !== $('forecast-strip')) {
      if (n.classList && n.classList.contains('strip-cell')) return n;
      n = n.parentNode;
    }
    return null;
  }

  /* focusin, so Tab traversal live-updates the panel. There is deliberately no
     hover handler: a pointer sweeping the strip must not strobe the panel, and
     hover raises the cell only. */
  function onStripFocusIn(e) {
    var c = cellFromEvent(e);
    if (!c) return;
    selectCell(Number(c.getAttribute('data-idx')), false);
  }

  /* Enter and Space both fire click on a native button, so pinning needs one
     handler and no key mapping. */
  function onStripClick(e) {
    var c = cellFromEvent(e);
    if (!c) return;
    selectCell(Number(c.getAttribute('data-idx')), true);
  }

  function selectCell(idx, pin) {
    var slots = state.slots;
    if (!slots.length) return;
    if (!isFinite(idx) || idx < 0 || idx >= slots.length) idx = 0;
    state.selected = idx;
    if (pin) {
      state.pinned = idx;
      /* Pinned draws border and ring only — never a surface repaint, because
         the surface is carrying the weight band and the unverified state. */
      var all = $('forecast-strip').querySelectorAll('.strip-cell');
      Array.prototype.forEach.call(all, function (c) {
        c.setAttribute('aria-pressed', Number(c.getAttribute('data-idx')) === idx ? 'true' : 'false');
      });
    }
    renderDetail(slots[idx]);
  }

  function detailRow(host, label, value, color, zero) {
    var r = el('div', 'strip-detail-row');
    if (color) r.style.setProperty('--mark-color', color);
    if (zero) r.setAttribute('data-zero-weight', 'true');
    r.appendChild(el('span', null, label));
    r.appendChild(el('span', 'strip-detail-num num', value));
    host.appendChild(r);
    return r;
  }

  function renderDetail(slot) {
    var meta = state.meta;
    var title = $('strip-detail-title');
    var body = $('strip-detail-body');       // write into the BODY, never the panel
    body.textContent = '';
    title.textContent = utcPretty(slot.valid_time);

    if (slot.kind === 'gap') {
      var g = slot.row;
      detailRow(body, 'Lead', slot.lead_h + ' h');
      detailRow(body, 'Blend', '—');
      (g.missing_models || []).forEach(function (m) {
        detailRow(body, m, 'missing', modelVar(m));
      });
      body.appendChild(el('p', 'strip-reason', String(g.reason == null ? '' : g.reason)));
      body.appendChild(el('p', 'strip-detail-note',
        'No value is shown for this step, and none is interpolated, back-filled or ' +
        'renormalized over the remaining models.'));
      return;
    }

    var row = slot.row;
    var names = meta.models_included || Object.keys(row.members || {});

    detailRow(body, 'Lead', row.lead_h + ' h');
    detailRow(body, 'Blend', withUnit(fmt(row.blend_f, 1), meta.units));

    names.forEach(function (m) {
      var w = Number(row.weights[m]);
      /* One decimal, always: a fitted weight of exactly zero renders 0.0 —
         never 0, never blank, never dropped from the vector. */
      detailRow(body, m, fmt(w, 1), modelVar(m), w === 0);
    });
    body.appendChild(el('p', 'strip-detail-note',
      'Weights fitted at a ' + row.weights_fitted_at_lead_h + '-hour lead'));

    names.forEach(function (m) {
      detailRow(body, m, withUnit(fmt(row.members[m], 1), meta.units), modelVar(m));
    });
    body.appendChild(el('p', 'strip-detail-note',
      'Model spread ' + withUnit(fmt(row.member_spread_f, 1), meta.units) +
      ' (max ' + MINUS + ' min across ' + names.length + ' models)'));

    if (row.is_extrapolated_lead === true) {
      /* The sentence, verbatim, with no number beside it. */
      var note = el('p', 'strip-detail-note',
        'No skill measurement exists beyond a 24-hour lead. These hours use the ' +
        '24-hour weights and are unverified.');
      note.setAttribute('data-tone', 'warn');
      body.appendChild(note);
    }
  }

  /* ── 3.7 truncated-horizon note, skill shell, 503 ───────────────────── */

  /* Derived, never typed. A silently shorter strip is a lie by omission: it
     lets a viewer conclude that the archive is all NOAA publishes, when it is
     our step grid that ended. Rendered by setting text — the CSS hides the
     element with :empty, so there is no display write here either. */
  function renderNote() {
    var host = $('strip-note');
    var meta = state.meta;
    if (!(Number(meta.horizon_h) < FULL_HORIZON_H)) { host.textContent = ''; return; }

    var order = meta.models_included || [];
    var seen = {}, named = [];
    (state.data.gaps || []).forEach(function (g) {
      (g.missing_models || []).forEach(function (m) { seen[m] = true; });
    });
    order.forEach(function (m) { if (seen[m]) named.push(m); });
    Object.keys(seen).forEach(function (m) { if (named.indexOf(m) === -1) named.push(m); });

    var clause = named.length
      ? '; ' + named.join(', ') + ' did not publish past ' + meta.horizon_h + ' h in this cycle.'
      : '.';
    host.textContent = 'Horizon truncated to ' + meta.horizon_h + ' h. ' +
      'The step grid is the intersection of all ' + order.length + ' models' + clause +
      ' Steps beyond it are shown as gaps, never filled in.';
  }

  /* SHELL ONLY, and nothing numeric from skill[]. No MAE, no improvement
     figure, no best-single-model name — those all vary by lead in one of the
     two payloads this page renders, so a literal here would survive one and lie
     about the other. That content belongs to a later ticket. What this fills is
     provenance: dates, paths and counts from meta.weights_source. */
  function renderSkillShell() {
    var ws = state.meta.weights_source;
    if (!ws) return;
    var w = ws.window || {}, sp = ws.split || {};

    $('skill-window').textContent = utcDate(w.start) + ' → ' + utcDate(w.end) + ' UTC · ' +
      w.days + ' days · fitted on the first ' + sp.train_days +
      ', scored on the last ' + sp.test_days;

    var host = $('skill-weights-age');
    host.textContent = '';
    function line(label, value, mono) {
      var p = el('p', 'skill-weights-line');
      p.appendChild(el('span', 'skill-weights-label', label));
      p.appendChild(el('span', mono ? 'skill-weights-value num' : 'skill-weights-value', ' ' + value));
      host.appendChild(p);
    }
    line('Fitted window', w.start + ' → ' + w.end, true);
    line('Split', sp.train_days + ' train days / ' + sp.test_days + ' test days · ' + sp.method, true);
    line('Fitted at', ws.generated_at, true);
    line('Age', ws.weights_age_days + ' days', true);
    line('Fitted leads', (ws.fitted_leads || []).join(', '), true);
    line('Source', String(ws.path), true);

    /* Present regardless of age. There is no green "fresh" badge below the
       threshold: freshness is not an achievement, and green here would read as
       an endorsement of numbers whose shelf life nobody has measured. */
    host.appendChild(el('p', 'skill-weights-regime',
      'Weights fitted on ' + w.days + ' days of ' + utcMonthName(w.start) +
      ' do not necessarily hold in December. These weights were fitted on ' +
      utcDate(w.start) + ' → ' + utcDate(w.end) + '. The atmosphere’s regime changes; ' +
      'a blend tuned on summer convection has no claim on winter inversions, and ' +
      state.meta.site.id + ' has both.'));

    if (Number(ws.weights_age_days) > 45) {
      host.appendChild(el('p', 'strip-note',
        'These weights are ' + ws.weights_age_days + ' days old, fitted on ' +
        utcDate(w.start) + ' → ' + utcDate(w.end) + '.'));
    }
  }

  /* ── The 503 ─────────────────────────────────────────────────────────
     Icon, title, one human sentence, then the server's reason verbatim in mono.
     Never blank-but-styled: either the payload rendered, or this card is on
     screen naming what went wrong. Never apologize, and the next action is a
     command — there is no refetch endpoint by design, and a button that cannot
     fetch is worse than no button. Pattern: app.js:487-509. */
  function renderEmptyState(detail) {
    var shell = $('shell');
    if (shell) shell.classList.add('is-hidden');
    var host = $('error-slot');
    host.textContent = '';

    /* The run label renders above the card IFF a cycle is knowable. If nothing
       is known it is omitted entirely — never a dashed-out label, never one
       guessed from the wall clock. A faked run label is worse than none. */
    if (state.meta && state.meta.cycle && state.meta.cycle.init_time) {
      var label = el('div', 'stat-meta cycle-run-label');
      renderRunLabel(label, state.meta);
      host.appendChild(label);
    }

    var card = el('div', 'card empty-state');
    card.id = 'empty-state';
    card.appendChild(el('div', 'empty-icon', '◍'));
    card.appendChild(el('p', 'empty-title', 'No forecast cache. Fetch a cycle.'));
    card.appendChild(el('p', 'empty-body', 'Run: uv run python -m forecast.refresh'));
    card.appendChild(el('p', 'empty-detail', String(detail)));   // the server's reason, verbatim
    host.appendChild(card);
  }

})();
