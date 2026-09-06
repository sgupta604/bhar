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
    pinned: 0,
    history: null,      // the /api/forecast/history payload, or null until it lands
    dayIdx: 0           // the day the stepper is on, an index over history.days
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

  /* ── 4.2 the second fetch — the scored past ───────────────────────────
     ITS OWN CHAIN, ITS OWN SUBTREE, ON PURPOSE. A 503 here resolves in this
     .catch, writes one card into #history-unavailable and touches nothing
     else: it never calls renderEmptyState, never hides the shell and never
     reaches a forward-page node. The forward view renders regardless of what
     this endpoint does, and this region names what went wrong in the
     server's own words rather than going blank-but-styled. */
  fetch(API_BASE + '/api/forecast/history')
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
    .then(function (payload) {
      state.history = payload;
      state.dayIdx = 0;
      renderHistory();
      renderSkillRealized();   // no-op until the forward payload is in
    })
    .catch(function (err) {
      renderHistoryUnavailable(err && err.userDetail ? err.userDetail
        : (err && err.message ? err.message : String(err)));
    });

  mountStepper();    // the buttons are in the markup, so they bind once, up front

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
    renderSkillLeads();
    renderSkillBasis();
    renderSkillCrossLink();
    renderSkillRealized();      // no-op until the archive payload is in
    layoutStrip();
    renderNote();
    selectCell(0, true);          // the panel is never empty on first paint
    window.addEventListener('resize', onResize);
    /* The two fetches settle in either order and the history note names the
       forward step, so the history is re-rendered here if it landed first. */
    renderHistory();
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
      host.appendChild(el('p', 'skill-weights-note',
        'These weights are ' + ws.weights_age_days + ' days old, fitted on ' +
        utcDate(w.start) + ' → ' + utcDate(w.end) + '.'));
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
     SKILL PANEL CONTENT — F7, design-target §1.5 and §4

     Everything the trust panel says about what already happened is composed
     below. Every sentence is past tense, names its window and its lead, and
     stops there. Nothing here becomes a claim about a forward value.

     PLACED ABOVE THE F6 HISTORY BANNER ON PURPOSE. F6's region extractor
     slices this file from its own banner to end of file, so anything appended
     at the tail would land inside F6's region and be read by F6's guards.
     ══════════════════════════════════════════════════════════════════════ */

  /* ══ PANEL COPY — pinned by tests/test_forecast_skill_panel_copy.py ══ */

  /* CONTAINMENT RULE. String constants and pure template functions only. No
     DOM handle, no element builder, no node insertion, no read of the page's
     own data object — prose in, prose out. A renderer belongs outside this
     block; a sentence that reaches the page belongs inside it.

     ARGUMENT CONVENTION, written down once so no call site re-decides it:
     every numeric value arrives ALREADY FORMATTED, as a display string
     carrying its unit wherever the sentence shows one. The call site does
     fmt(v, 2) for a mean error, fmt(v, 1, true) for a signed improvement, and
     appends the unit symbol derived from meta.units. Nothing below calls fmt,
     so the U+2212 substitution happens in exactly one place and never twice.
     Counts, the site id, the model name and the lead hour arrive as plain
     values and are stringified by concatenation.

     Nothing below types a model name, a site name, a unit glyph, a sign or a
     lead hour. Every one of those differs between the two payloads this page
     is rendered against, so a literal here would read fine on one and lie
     about the other. */

  /* The tie window for improvement_pct, read from
     .claude/features/demo-shell/design-target.md §3 (D4) and never re-derived
     here. The tone token and the comparison clause are both selected by
     improvementState(), so a clause and a colour can never disagree about
     what the same number said. */
  var IMPROVE_TIE_BOUND = 0.05;

  function improvementState(pct) {
    var n = Number(pct);
    if (!isFinite(n)) return 'tie';
    if (n > IMPROVE_TIE_BOUND) return 'win';
    if (n < -IMPROVE_TIE_BOUND) return 'loss';
    return 'tie';
  }

  /* Three variants, all shipped, all reachable. On one of the two payloads
     this page renders, the longest fitted lead came out WORSE than the best
     single model — so a lone "better than" template would read fine there and
     say something untrue. The loss variant is not a fallback; it is the
     sentence that payload asks for, and it renders at the same size, position
     and weight as a win. */
  var COMPARISON_CLAUSE = {
    win: 'better than the best single model',
    tie: 'level with the best single model',
    loss: 'worse than the best single model'
  };

  function copyComparisonClause(tone, model, bestMaeText) {
    var opening = COMPARISON_CLAUSE[tone] || COMPARISON_CLAUSE.tie;
    return opening + ' (' + model + ', ' + bestMaeText + ') over the same period.';
  }

  function copyLeadOpening(days, siteId, leadH, blendMaeText) {
    return 'Over the last ' + days + ' days at ' + siteId +
      ', this blend\'s typical miss at a ' + leadH + '-hour lead was ' +
      blendMaeText + ' — ';
  }

  function copyInSample(trainDays, inSampleText) {
    return 'In-sample, on the ' + trainDays +
      ' days the weights were fitted on, it was ' + inSampleText + '.';
  }

  /* The coincidence clause is gated on the DATA condition below — the two
     figures being all but equal with the fitted one no lower — and never on a
     lead hour. A lead-keyed gate would print the coincidence sentence on a
     refit where the coincidence had gone. */
  var COINCIDENCE_TOL = 0.01;

  function isCoincidence(blendMae, inSampleMae) {
    var out = Number(blendMae), fitted = Number(inSampleMae);
    if (!isFinite(out) || !isFinite(fitted)) return false;
    return out <= fitted && (fitted - out) < COINCIDENCE_TOL;
  }

  function copyInSampleCoincidence(trainDays, inSampleText, toleranceText, nTest) {
    return 'In-sample, on the ' + trainDays +
      ' days the weights were fitted on, it was also ' + inSampleText +
      '; the two differ by less than ' + toleranceText +
      ', and at this lead the fit did not degrade on unseen days. That is a ' +
      nTest + '-sample coincidence, not evidence that the fit generalised ' +
      'better than it was measured to.';
  }

  function copySampleClause(nTest, independentDays, pairs) {
    return 'That is ' + nTest + ' scored forecasts, which is roughly ' +
      independentDays + ' independent days, not ' + pairs + '.';
  }

  var COPY_CLOSER = 'That is history, not a promise about this forecast.';

  /* README C2's reason, in the customer's language. Two variants: the count
     word when the runs-per-day derivation is a whole number, and the
     unquantified opener when it is not — which is the case on one of the two
     payloads, where the figure lands between two whole numbers. */
  var BASIS_SEVERAL = 'Several';

  function capitaliseWord(word) {
    var w = String(word);
    return w.charAt(0).toUpperCase() + w.slice(1);
  }

  function copyBasisSentence(runs, days, pairs, independentDays) {
    var n = Number(runs);
    var opener = (isFinite(n) && n === Math.round(n))
      ? capitaliseWord(countWord(n))
      : BASIS_SEVERAL;
    return opener + ' initialisations a day over ' + days +
      ' days share a weather regime, so the ~' + pairs +
      ' forecast-observation pairs at each lead are closer to ~' +
      independentDays + ' independent days.';
  }

  /* WHEN THE PAYLOAD IS FABRICATED, THE TWO FIGURES IN THIS BLOCK CAME FROM
     DIFFERENT WORLDS, AND THE PAGE BANNER DOES NOT SAY SO. The banner speaks
     about the forecast; the realized figure is loaded from the archive by a
     separate request, which no fixture replaces. So on a fixture payload an
     invented backtest number sits inches from a genuinely measured one, and
     both readings a viewer can take are wrong: trusting the banner discards a
     real measurement, and reading the pair as a comparison reads a difference
     between an invention and an observation. The sentence below says which is
     which, and it is repeated in every lead block rather than stated once at
     the top of the panel, because the juxtaposition it defuses is per-lead and
     a reader scrolled to one block must see it there. */
  var COPY_SYNTHETIC_MIXING =
    'The blend and best-single figures above are fabricated. The realized miss ' +
    'below was measured from real observations at this site, so the two are not ' +
    'comparable and the difference between them means nothing.';

  /* The realized figure is pooled over EVERY archived day, the fitted ones
     included, which is a reason for it to sit lower that has nothing to do
     with skill. Suppressing it would itself be selection, so it ships with
     the caveat that makes it unreadable as a score. */
  function copyRealizedLeadIn(realizedMaeText) {
    return 'Against the observations already in, the blend\'s realized miss at ' +
      'this lead came out at ' + realizedMaeText + '.';
  }

  function copyRealizedCaveat(archivedDays, trainDays) {
    return 'That pools all ' + archivedDays + ' archived days, including the ' +
      trainDays + ' the weights were fitted on, so it is not comparable to the ' +
      'out-of-sample figure beside it, and neither number says anything about ' +
      'this forecast.';
  }

  /* Parameterised on the real boundary lead read from the payload — the first
     slot the payload marks as beyond the fitted range — never on a typed hour
     count, which a horizon change would leave behind. */
  function copyCrossLink(boundaryLeadH) {
    return 'Those are the shaded cells from a ' + boundaryLeadH +
      '-hour lead onward on the strip above.';
  }

  /* The whole per-lead sentence, joined here so the spaces between its clauses
     live inside the pinned block too. Fields arrive already formatted. */
  function copyLeadSentence(p) {
    return copyLeadOpening(p.days, p.siteId, p.leadH, p.blendMaeText) +
      copyComparisonClause(p.tone, p.bestModel, p.bestMaeText) + ' ' +
      (p.coincidence
        ? copyInSampleCoincidence(p.trainDays, p.inSampleText, p.toleranceText, p.nTest)
        : copyInSample(p.trainDays, p.inSampleText)) + ' ' +
      copySampleClause(p.nTest, p.independentDays, p.pairs) + ' ' +
      COPY_CLOSER;
  }

  /* ══ END PANEL COPY ══ */

  /* The two derivations the copy above is parameterised on. Arithmetic, not
     prose, so they sit outside the pinned block — but they are written down
     once, here, and never recomputed at a call site.

     Scored rows are the test split only; the pair count the sentence contrasts
     with is the whole window's, which is why the split ratio is applied. Runs
     per day then falls out of the pair count and the window length, and is a
     whole number on one payload and not on the other. */
  function pairsPerLead(nTest, trainDays, testDays) {
    var n = Number(nTest), train = Number(trainDays), test = Number(testDays);
    if (!isFinite(n) || !isFinite(train) || !isFinite(test) || test === 0) return null;
    return Math.round(n * (train + test) / test);
  }

  function runsPerDay(pairs, windowDays) {
    var p = Number(pairs), d = Number(windowDays);
    if (!isFinite(p) || !isFinite(d) || d === 0) return null;
    return p / d;
  }

  /* ── The renderers ──────────────────────────────────────────────

     Prose lives in the pinned block above; everything below is DOM. Nothing
     here types a sentence, a model name, a site id, a unit glyph or a lead
     hour — all of those are read from the payload and handed to a template.

     A note on the two precisions, because it is the whole point of the panel.
     The sentence rounds a mean error to two places, where at one lead both
     figures read the same and the ordering disappears — which is why the
     sentence states the direction in words. The cells below carry whatever
     precision the payload carries, so the ordering stays inspectable by
     anyone who looks. Neither rendering is dropped to simplify the other. */

  /* The payload's enum, in the customer's words, with the raw value as the
     fallback: an unrecognised basis renders as itself rather than vanishing,
     because a missing provenance line reads as no provenance at all. */
  var BASIS_PROSE = {
    historical_out_of_sample: 'Historical, out of sample.'
  };

  /* Whatever precision the payload carries, and not one digit more. A fixed
     decimal count here would print trailing zeros the backtest never
     measured on one of the two payloads. */
  function exactValue(v) {
    var n = Number(v);
    return isFinite(n) ? String(n) : '';
  }

  /* One cell of the five. Label above value, always in this order, and the
     label is never omitted — a reader who cannot remember which figure is
     which reads the label, which is always there. */
  function skillNumCell(host, label, value, cls) {
    var cell = el('div', cls ? 'skill-num ' + cls : 'skill-num');
    cell.appendChild(el('div', 'skill-num-label', label));
    cell.appendChild(el('div', 'skill-num-value num', value));
    host.appendChild(cell);
  }

  /* The fitted vector actually used at this lead. Looked up by matching the
     forward row's fitted-lead field AGAINST the skill lead, never the other
     way round: that field is the lead the weights came from, not the row's
     own lead, so indexing skill by it would read the wrong entry for every
     extrapolated row. No matching row means no chips — an invented vector
     would be a claim about a fit that is not in the payload. */
  function weightsForLead(rows, leadH) {
    var found = null;
    (rows || []).forEach(function (row) {
      if (found || !row || !row.weights) return;
      if (Number(row.weights_fitted_at_lead_h) === Number(leadH)) found = row.weights;
    });
    return found;
  }

  /* Canonical order from the payload's own model list. A weight of exactly
     zero renders as zero and is marked so the chip can be de-emphasised: the
     backtest looked at that model and gave it nothing, which is a finding.
     Dropping it, or renormalising the rest, would hide it. */
  function renderSkillWeights(block, weights, models) {
    var chips = el('div', 'skill-weights');
    models.forEach(function (model) {
      var w = weights[model];
      if (w == null) return;
      var chip = el('span', 'skill-weight-chip', model);
      chip.style.setProperty('--mark-color', modelVar(model));
      if (Number(w) === 0) chip.setAttribute('data-zero-weight', 'true');
      chip.appendChild(el('span', 'skill-weight-num', ' ' + fmt(w, 1)));
      chips.appendChild(chip);
    });
    block.appendChild(chips);
  }

  /* One block per fitted lead, in PAYLOAD ORDER. Never sorted by any metric:
     a panel that reorders itself by result is a panel that can be made to
     lead with its best number. */
  function renderSkillLeads() {
    var data = state.data, meta = state.meta;
    var skill = data && data.skill;
    var host = $('skill-leads');
    if (!host || !skill || !skill.by_lead) return;
    host.textContent = '';

    var units = meta.units;
    var win = skill.window || {};
    var ws = meta.weights_source || {};
    var split = ws.split || {};
    var models = meta.models_included || [];
    var toleranceText = withUnit(fmt(COINCIDENCE_TOL, 2), units);

    skill.by_lead.forEach(function (lead) {
      var tone = improvementState(lead.improvement_pct);
      var improveText = fmt(lead.improvement_pct, 1, true);
      var pairs = pairsPerLead(lead.n_test, split.train_days, split.test_days);
      var block = el('div', 'skill-lead');
      /* The block's own lead, on the block, so the realized renderer can
         find it later without depending on child order or on the two
         renderers agreeing about an index. Always set, always to the
         payload's value. */
      block.setAttribute('data-lead-h', lead.lead_h);

      var head = el('div', 'skill-lead-head');
      head.appendChild(el('span', 'badge-pill', lead.lead_h + '-hour lead'));
      var improve = el('span', 'skill-improve num', improveText + '%');
      /* Set to the state it is in, always a positive value. A zero or a loss
         is a legitimate outcome and gets the same size, position and weight
         as a win — only the tone token differs, and the clause in the
         sentence is picked by the same call, so the two cannot disagree. */
      improve.setAttribute('data-improve', tone);
      head.appendChild(improve);
      block.appendChild(head);

      block.appendChild(el('p', 'skill-copy', copyLeadSentence({
        days: win.days,
        siteId: meta.site.id,
        leadH: lead.lead_h,
        blendMaeText: withUnit(fmt(lead.blend_mae, 2), units),
        tone: tone,
        bestModel: lead.best_single_model,
        bestMaeText: withUnit(fmt(lead.best_single_mae, 2), units),
        /* Gated on the two figures, never on a lead hour. */
        coincidence: isCoincidence(lead.blend_mae, lead.blend_mae_in_sample),
        trainDays: split.train_days,
        inSampleText: withUnit(fmt(lead.blend_mae_in_sample, 2), units),
        toleranceText: toleranceText,
        nTest: lead.n_test,
        independentDays: lead.independent_days_approx,
        pairs: pairs
      })));

      /* Five cells, fixed DOM order, never reordered by magnitude. The
         out-of-sample figure is first and larger; the fitted-days figure is
         second, labelled, muted, and never promoted. No difference between
         the two is drawn as a toned or arrowed figure — at one lead it would
         favour the fit, and colouring it there would assert exactly what the
         sample size does not support. */
      var nums = el('div', 'skill-nums');
      skillNumCell(nums, 'BLEND MAE (OUT-OF-SAMPLE)',
        withUnit(exactValue(lead.blend_mae), units), 'skill-num-oos');
      skillNumCell(nums, 'IN-SAMPLE (FITTED DAYS)',
        withUnit(exactValue(lead.blend_mae_in_sample), units));
      skillNumCell(nums, 'BEST SINGLE (' + lead.best_single_model + ')',
        withUnit(exactValue(lead.best_single_mae), units));
      /* The one cell in this grid that is not in the temperature unit, so
         it says so. improvement_pct is a percentage; a bare +9.0 sitting
         between four °F figures reads as nine degrees. The number itself
         still comes from the shared formatter, so the minus stays the
         real U+2212 one and is never substituted twice. The sentence
         above quotes the comparison clause, not this figure, and is
         unchanged. */
      skillNumCell(nums, 'IMPROVEMENT', improveText + '%');
      skillNumCell(nums, 'SAMPLE', lead.n_test + ' test rows · ~' +
        lead.independent_days_approx + ' independent days');
      block.appendChild(nums);

      var weights = weightsForLead(data.forecast, lead.lead_h);
      if (weights) renderSkillWeights(block, weights, models);

      host.appendChild(block);
    });
  }

  /* The provenance line, once, under all three blocks. Always visible: the
     reason the sample is smaller than the pair count suggests is not a
     footnote to be opened, it is part of the claim. */
  function renderSkillBasis() {
    var node = $('skill-basis');
    var skill = state.data && state.data.skill;
    if (!node || !skill) return;
    var win = skill.window || {};
    var split = (state.meta.weights_source || {}).split || {};
    var first = (skill.by_lead && skill.by_lead[0]) || {};
    var pairs = pairsPerLead(first.n_test, split.train_days, split.test_days);
    var parts = [];
    if (skill.basis != null) {
      parts.push(BASIS_PROSE[skill.basis] || String(skill.basis));
    }
    /* The server's own words, unedited. A note that says the numbers are
       fabricated has to reach the page saying that. */
    if (skill.note != null) parts.push(String(skill.note));
    parts.push(copyBasisSentence(runsPerDay(pairs, win.days), win.days, pairs,
      first.independent_days_approx));
    node.textContent = parts.join(' ');
  }

  /* Panel to strip, in words. A SIBLING of the verbatim extrapolation
     sentence, never inside it: that node's digits are pinned, and a derived
     hour count landing in it would break the pin the moment the horizon
     moved. The boundary is the first slot the payload marks as beyond the
     fitted range; no such slot means no sentence, and the node stays empty
     rather than being hidden by script. */
  function renderSkillCrossLink() {
    var node = $('skill-extrapolated-link');
    if (!node) return;
    node.textContent = '';
    var boundary = null;
    ((state.data && state.data.forecast) || []).forEach(function (row) {
      if (boundary === null && row && row.is_extrapolated_lead === true) {
        boundary = row.lead_h;
      }
    });
    if (boundary === null) return;
    node.textContent = copyCrossLink(boundary);
  }

  /* ── 3.1 the realized block ───────────────────────────────────────────

     THE MOST MISREADABLE NUMBER ON THIS PAGE, so it is built to be hard to
     misread. Realized error is what the archive already scored at this lead.
     It is NOT a second, friendlier version of the out-of-sample figure: it
     pools every archived day, the fitted ones included, so it sits lower for
     a reason that has nothing to do with skill. It therefore lives BELOW the
     numeric grid, in its own node, in the subordinate muted face — never in a
     cell of .skill-nums, never in the out-of-sample tone, never beside it in
     a way that invites a reader to compare the two as like for like. The
     caveat that says so is rendered with it, always, not on demand.

     Pooled over the individual scored entries at this lead, and never over
     the days' own mae_f. A mean of daily means gives a day with three scored
     slots the same weight as a day with six, and the archive's days do not
     all carry the same count — the two derivations disagree, and the pooled
     one is the one the sentence claims.

     Magnitude is folded by hand rather than with the absolute-value call this
     file bans outside a threshold test. The ban exists so a displayed
     improvement can never quietly lose its sign; here the sign is genuinely
     not wanted — a miss two degrees high and a miss two degrees low are the
     same size of miss — so the fold is written out where it can be seen. */
  function errorMagnitude(v) {
    var n = Number(v);
    if (!isFinite(n)) return null;
    return n < 0 ? -n : n;
  }

  function pooledRealizedMae(days, leadH) {
    var total = 0, count = 0;
    (days || []).forEach(function (day) {
      ((day && day.entries) || []).forEach(function (entry) {
        if (!entry || Number(entry.lead_h) !== Number(leadH)) return;
        var m = errorMagnitude(entry.error_f);
        if (m === null) return;
        total += m;
        count += 1;
      });
    });
    /* No scored entry at this lead means no figure and no node. Zero rows
       would average to a perfect zero, which is the fake-perfect result this
       project's integrity rules exist to refuse. */
    return count ? total / count : null;
  }

  /* One mark per archived day that actually scored this lead, in archive
     order. A day the archive scored at other leads but not at this one is
     SKIPPED — not zeroed, not carried forward from its neighbour, not
     interpolated — because a mark drawn for a day with no measurement is a
     measurement invented. The archive's first day is exactly that case at the
     longest lead, so the shortest row is a true row and not a bug. */
  function realizedDayMarks(days, leadH) {
    var marks = [];
    (days || []).forEach(function (day) {
      var byLead = (day && day.mae_f) || {};
      var raw = byLead[String(leadH)];
      if (raw == null) return;
      var v = Number(raw);
      if (!isFinite(v)) return;
      marks.push(v);
    });
    return marks;
  }

  /* THE SCALE THE MARKS ARE DRAWN ON, DERIVED AND STATED IN ONE PLACE.
     The largest daily mean absolute error the archive holds at any lead.
     Read off the data every render, never a typed ceiling — a typed one stops
     being true the first time a worse day lands — and never a per-lead
     maximum, which would rescale each row to its own worst day and make three
     leads with very different spreads look alike. One scale for all three
     rows, so a tall mark means the same thing wherever it appears. */
  function realizedMarkScaleMax(days) {
    var max = 0;
    (days || []).forEach(function (day) {
      var byLead = (day && day.mae_f) || {};
      Object.keys(byLead).forEach(function (key) {
        var v = Number(byLead[key]);
        if (isFinite(v) && v > max) max = v;
      });
    });
    return max > 0 ? max : null;
  }

  /* GUARDED ON BOTH PAYLOADS, CALLED FROM BOTH CHAINS. The forward fetch and
     the archive fetch settle in either order; each chain calls this, and this
     returns untouched until the other one's payload is in. Whichever settles
     second builds the content, so the settle order cannot change the final
     DOM. The archive failing leaves the whole block unbuilt — no node, no
     dash, no placeholder, no label with nothing under it — and the forward
     panel above is not touched by any path through here. Nothing is hidden by
     script; a node that should not be read is a node that was never made. */
  function renderSkillRealized() {
    var data = state.data, archive = state.history;
    var skill = data && data.skill;
    var host = $('skill-leads');
    if (!host || !skill || !skill.by_lead || !archive || !archive.days) return;

    var days = archive.days;
    /* The fitted-days count comes from the SAME field the in-sample sentence
       above reads, so the caveat and that sentence can never name different
       numbers of fitted days. Both counts in the caveat are payload values;
       neither is typed here. */
    var trainDays = ((state.meta.weights_source || {}).split || {}).train_days;
    var units = state.meta.units;
    var scaleMax = realizedMarkScaleMax(days);

    skill.by_lead.forEach(function (lead) {
      var block = host.querySelector('[data-lead-h="' + lead.lead_h + '"]');
      if (!block) return;

      /* Idempotent by construction: a second call replaces the block's
         realized node rather than appending a second copy, so calling from
         both chains cannot double the content. */
      var prior = block.querySelector('.skill-realized');
      if (prior) block.removeChild(prior);

      var pooled = pooledRealizedMae(days, lead.lead_h);
      if (pooled === null) return;

      var realized = el('div', 'skill-realized');

      /* GATED ON meta.is_synthetic AND ON NOTHING ELSE — the same single
         boolean applySynthetic() reads for the page banner. Not a second flag,
         not a re-derivation from the payload, and never the data-synthetic
         attribute read back off the documentElement: a second source of truth
         is how a page ends up with a banner that says fabricated and a block
         that does not. Read as the boolean it is, never compared against a
         string, since a negated string literal is still truthy. On a real
         payload the node is never built, so there is no empty node, no
         placeholder and no dash left carrying a label. */
      if (state.meta.is_synthetic) {
        realized.appendChild(el('p', 'skill-realized-mixing', COPY_SYNTHETIC_MIXING));
      }

      realized.appendChild(el('p', 'skill-realized-lead-in',
        copyRealizedLeadIn(withUnit(fmt(pooled, 2), units))));

      /* The marks detail the figure just stated, so they sit with it and
         above the caveat that qualifies both. Each carries its day's value as
         a fraction of the archive maximum; one CSS rule turns that into the
         only channel the mark has. */
      var marks = realizedDayMarks(days, lead.lead_h);
      if (marks.length && scaleMax !== null) {
        var row = el('div', 'skill-realized-marks');
        marks.forEach(function (value) {
          var mark = el('span', 'skill-realized-mark');
          mark.style.setProperty('--mark-scale', String(value / scaleMax));
          row.appendChild(mark);
        });
        realized.appendChild(row);
      }

      realized.appendChild(el('p', 'skill-realized-caveat',
        copyRealizedCaveat(days.length, trainDays)));
      block.appendChild(realized);
    });
  }

  /* ══ END SKILL PANEL CONTENT — F7 ══ */

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

  /* ══════════════════════════════════════════════════════════════════════
     4.2-4.4 THE BACK-ARROW HISTORY REGION — design-target §1.6

     Nothing rendered below is a forecast. Every value here has already been
     settled by an observation, and it is presented as one: no band, no
     ribbon, no shaded envelope, no whisker, and no plus-or-minus figure
     attached to any value, here or anywhere on this page.

     Every string this block puts on the page that names a lead, a model, a
     site, a tolerance or a count is composed FROM THE PAYLOAD. The lead keys
     are the bare decimal hour count — String(lead_h) — which is the form the
     §10 contract locks; a padded or suffixed key would miss every lookup and
     render a quietly empty table.
     ══════════════════════════════════════════════════════════════════════ */

  /* Counts read as words in prose and as digits in data. Nine is plenty: past
     that the sentence takes the digits, which is better than a wrong word. */
  var COUNT_WORDS = ['no', 'one', 'two', 'three', 'four', 'five',
    'six', 'seven', 'eight', 'nine'];

  function countWord(n) {
    return (n >= 0 && n < COUNT_WORDS.length) ? COUNT_WORDS[n] : String(n);
  }

  /* "6, 12 and 24" — built from whatever the payload lists, in its order. */
  function joinList(values) {
    var parts = values.map(function (v) { return String(v); });
    if (parts.length < 2) return parts.join('');
    return parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1];
  }

  function historyDays() {
    return (state.history && state.history.days) ? state.history.days : [];
  }

  /* The leads a given day actually carries, ascending. Read from the day's own
     summary rather than from meta.leads_available: the two partial days at the
     edges of the window match at only some leads, and padding the row set out
     to the full lead list would invent an entry that was never scored. */
  function leadsPresent(day) {
    return Object.keys(day.mae_f || {}).map(Number).sort(function (a, b) { return a - b; });
  }

  function leadLabel(lead) { return String(lead) + ' h'; }

  function mountStepper() {
    var prev = $('day-prev');
    var next = $('day-next');
    if (prev) prev.addEventListener('click', function () { stepDay(-1); });
    if (next) next.addEventListener('click', function () { stepDay(1); });
  }

  /* At either end the button is present, focusable and dimmed, and the step is
     a no-op. It is never removed: a control that vanishes is a control the
     viewer thinks they broke. */
  function stepDay(delta) {
    var days = historyDays();
    if (!days.length) return;
    var target = state.dayIdx + delta;
    if (target < 0 || target > days.length - 1) return;
    state.dayIdx = target;
    renderHistory();
  }

  function setEndState(button, atEnd) {
    if (!button) return;
    /* Set when the condition holds, ABSENT when it does not — the same rule
       the state attributes on <html> follow. */
    if (atEnd) button.setAttribute('aria-disabled', 'true');
    else button.removeAttribute('aria-disabled');
  }

  function renderHistory() {
    var doc = state.history;
    if (!doc || !doc.meta) return;
    var meta = doc.meta;
    var days = historyDays();

    if (!days.length) {
      /* An empty history renders an empty back-arrow and scores perfectly
         against nothing. Say so; do not draw a stepper over it. */
      renderHistoryUnavailable('The history document carries no scored day. A window with ' +
        'nothing in it scores perfectly against nothing and must not be rendered as history.');
      return;
    }

    if (state.dayIdx > days.length - 1) state.dayIdx = days.length - 1;
    if (state.dayIdx < 0) state.dayIdx = 0;

    var slot = $('history-unavailable');
    if (slot) slot.textContent = '';

    renderLeadsNote(meta);
    renderStepper(days);
    renderDayCard(days[state.dayIdx], meta);
    renderOmitted(meta);

    document.documentElement.setAttribute('data-history', 'ready');
  }

  function renderStepper(days) {
    var pill = $('day-pill');
    if (pill) pill.textContent = String(days[state.dayIdx].date);
    setEndState($('day-prev'), state.dayIdx <= 0);
    setEndState($('day-next'), state.dayIdx >= days.length - 1);
  }

  /* 4.4 — why the past is at these leads, stated on the page, not collapsed
     behind a disclosure. The lead list and the forward step both come from
     their own payloads; neither is typed here. */
  function renderLeadsNote(meta) {
    var host = $('history-leads-note');
    if (!host) return;
    var leads = meta.leads_available || [];
    var word = countWord(leads.length);
    var step = (state.meta && state.meta.step_h != null)
      ? String(state.meta.step_h) + '-hourly' : '';

    var text = 'The past view shows ' + word + ' leads because ' + word +
      ' leads is what the archive was fetched at — it is not a downsample of the forward view.';
    if (step) {
      text += ' The forward strip is ' + step + '; the archive is ' + joinList(leads) +
        ' hours. A ' + step + ' past curve means refetching the archive at every step, ' +
        'and that is v2.';
    } else {
      text += ' The archive is ' + joinList(leads) + ' hours. A past curve on the forward ' +
        'strip’s step means refetching the archive at every step, and that is v2.';
    }
    host.textContent = text;
  }

  /* 4.3 — one .card for the day the stepper is on. */
  function renderDayCard(day, meta) {
    var host = $('history-days');
    if (!host) return;
    host.textContent = '';

    var card = el('section', 'card history-day-card');

    var header = el('div', 'card-header');
    header.appendChild(el('h3', 'card-title', String(day.date)));

    /* The aggregate is UNSIGNED BY CONSTRUCTION and is labelled so it is not
       read as a bias, and every figure carries the count it was taken over:
       a one-sample daily mean must not read like a four-sample one. */
    var summary = el('div', 'history-mae');
    summary.appendChild(el('span', 'history-mae-label', 'Mean absolute error'));
    leadsPresent(day).forEach(function (lead) {
      var key = String(lead);
      var item = el('span', 'history-mae-item');
      item.appendChild(el('span', 'badge-pill', leadLabel(lead)));
      item.appendChild(el('span', 'num history-mae-value',
        withUnit(fmt(day.mae_f[key], 2), meta.units)));
      item.appendChild(el('span', 'num history-mae-n',
        'n = ' + String((day.n_by_lead || {})[key])));
      summary.appendChild(item);
    });
    header.appendChild(summary);
    card.appendChild(header);

    var body = el('div', 'card-body');
    body.appendChild(historyTable(day, meta));
    body.appendChild(offsetNote(meta));
    card.appendChild(body);

    host.appendChild(card);
  }

  /* The comparison model is named by the payload. Where the backtest picked
     the same one at every lead the header can say which; where it did not,
     the header stays generic and each row names its own. */
  function bestSingleNames(meta) {
    var byLead = meta.best_single_model_by_lead || {};
    var names = [];
    Object.keys(byLead).forEach(function (key) {
      var name = String(byLead[key]).toUpperCase();
      if (names.indexOf(name) === -1) names.push(name);
    });
    return names;
  }

  function historyColumns(meta) {
    var names = bestSingleNames(meta);
    var best = names.length === 1 ? 'Best single (' + names[0] + ')' : 'Best single';
    return [
      { label: 'Lead', cls: '' },
      { label: 'Init (UTC)', cls: '' },
      { label: 'Valid (UTC)', cls: '' },
      { label: 'We said', cls: 'col-right' },
      { label: 'Observed', cls: 'col-right' },
      { label: 'Error', cls: 'col-right' },
      { label: best, cls: 'col-right' },
      { label: 'Obs offset', cls: 'col-right' }
    ];
  }

  function historyTable(day, meta) {
    var wrap = el('div', 'history-table-wrap');
    var table = el('table', 'tbl history-tbl');

    var head = el('thead');
    var headRow = el('tr');
    historyColumns(meta).forEach(function (col) {
      headRow.appendChild(el('th', col.cls, col.label));
    });
    head.appendChild(headRow);
    table.appendChild(head);

    /* ONE ROW PER ENTRY. The row count is data: a day may match at some leads
       and not at others, and a missing observation drops its row entirely —
       no fill, no carry-forward, no placeholder standing in for it. */
    var bodyRows = el('tbody');
    (day.entries || []).forEach(function (entry) {
      bodyRows.appendChild(historyRow(entry, meta));
    });
    table.appendChild(bodyRows);

    wrap.appendChild(table);
    return wrap;
  }

  function historyRow(entry, meta) {
    var row = el('tr');

    var lead = el('td');
    lead.appendChild(el('span', 'badge-pill', leadLabel(entry.lead_h)));
    row.appendChild(lead);

    row.appendChild(el('td', 'num history-time', utcStamp(entry.init_time)));
    row.appendChild(el('td', 'num history-time', utcStamp(entry.valid_time)));
    row.appendChild(el('td', 'num history-value', withUnit(fmt(entry.blend_f, 1), meta.units)));
    row.appendChild(el('td', 'num history-value', withUnit(fmt(entry.observed_f, 1), meta.units)));
    row.appendChild(errorCell(entry, meta));
    row.appendChild(el('td', 'num history-secondary',
      withUnit(fmt(entry.best_single_model_f, 1), meta.units)));

    /* Signed, in minutes, because a matched observation can sit either side of
       the valid time and which side it sat is part of the record. */
    row.appendChild(el('td', 'num history-offset',
      fmt(entry.obs_offset_min, 0, true) + ' min'));

    return row;
  }

  /* 4.4 — the signed error, with the sign LABELLED. A bare negative does not
     tell a grower anything, so the direction is spelled out beside it in
     words. The value's tone is neutral in all three cases: a warm bias is a
     finding, not an error state. The sign itself is a real U+2212 in the text
     node, put there by the shared formatter — never a hyphen, never dropped,
     never split into a magnitude and a direction icon. */
  function errorCell(entry, meta) {
    var cell = el('td', 'num history-error-cell');
    var value = Number(entry.error_f);
    cell.appendChild(el('span', 'history-error-value',
      withUnit(fmt(entry.error_f, 1, true), meta.units)));
    cell.appendChild(el('span', 'history-error-word',
      value > 0 ? 'warm' : (value < 0 ? 'cold' : 'exact')));
    return cell;
  }

  /* 4.4 — the observation offset, stated once under the table. The window and
     the mean offset are both read from meta.join; neither is a literal here,
     because the join is a parameter of the backtest and a number typed on the
     page would outlive a change to it. */
  function offsetNote(meta) {
    var join = meta.join || {};
    var note = el('p', 'card-sub history-offset-note');
    note.textContent = 'Observations are matched within a ' + String(join.tolerance_min) +
      '-minute nearest-observation window; METAR at ' + String((meta.site || {}).id) +
      ' reports near :53, and the mean absolute offset over this window was ' +
      fmt(join.mean_abs_offset_min, 2) + ' minutes.';
    return note;
  }

  /* 4.4 — the dates the join could not match, listed once below the day card.
     They are absent from the stepper and are never drawn as a day with a
     perfect score. The human sentence says what happened; the payload's own
     recorded reason sits beneath it as machine output, verbatim, so a viewer
     can paste it into a bug report. */
  function renderOmitted(meta) {
    var host = $('history-omitted');
    if (!host) return;
    host.textContent = '';

    var omitted = meta.omitted_days || [];
    if (!omitted.length) return;      // :empty hides the block; no display write

    var card = el('div', 'card empty-state');
    card.appendChild(el('div', 'empty-icon', '◍'));
    card.appendChild(el('p', 'empty-title', countWord(omitted.length) +
      (omitted.length === 1 ? ' date is not in the stepper.' : ' dates are not in the stepper.')));

    omitted.forEach(function (day) {
      var item = el('div', 'history-omitted-item');
      item.appendChild(el('p', 'empty-body', String(day.date) +
        ' is not shown: no forecast-observation pair matched within the join window.'));
      item.appendChild(el('p', 'empty-detail', String(day.reason)));
      card.appendChild(item);
    });

    host.appendChild(card);
  }

  /* The history 503. The forward page above is already on screen and stays
     there; only this block changes. The next action is a command, because
     there is no refetch route by design. Never apologize. */
  function renderHistoryUnavailable(detail) {
    var host = $('history-unavailable');
    if (!host) return;
    host.textContent = '';

    var card = el('div', 'card empty-state');
    card.appendChild(el('div', 'empty-icon', '◍'));
    card.appendChild(el('p', 'empty-title', 'No scored history. Build it.'));
    card.appendChild(el('p', 'empty-body', 'Run: uv run python -m forecast.history'));
    card.appendChild(el('p', 'empty-detail', String(detail)));   // the server's reason, verbatim
    host.appendChild(card);
  }

})();
