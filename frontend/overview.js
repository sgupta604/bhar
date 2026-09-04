/* overview.js — one fetch, one view-model, declarative binding, five hand-built
   diagrams, and a deliberate refusal to ever put a result number in the HTML.

   Contract with overview.html:
     <span data-live="dot.path" data-fmt="degF">—</span>
   Resolve the dot path against the view-model, format by data-fmt, write
   textContent. A missing or null value leaves (or restores) the em dash and
   never throws. If the fetch fails the walk never runs at all, so the page
   degrades to prose with dashes rather than to an empty state — the opposite
   of the product page's behaviour, on purpose: this is the first thing the
   room sees and a blank landing page is a worse failure than a stale one.

   Colour rule for every diagram in here: model colour is applied as
   style="fill: var(--model-hrrr)", a CSS custom property, NEVER a resolved
   hex and never modelColors(). models.js memoizes that map and app.js/chart.js
   bake the result inline; by using the variable directly these diagrams
   repaint on a theme change with no cache to invalidate. BharChart.render is
   never called from this page for exactly that reason — only slicePoints. */
(function () {
  'use strict';

  var M = window.BharModels, F = window.BharFormat;
  var MODELS = M.MODELS;

  /* The exact expression from app.js:9, duplicated deliberately. The two
     pages do not share a data layer and will not be refactored to. */
  var API_BASE = new URLSearchParams(location.search).get('api') || 'http://localhost:8000';

  var state = { vm: null, lead: null };

  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── boot ─────────────────────────────────────────────────────────── */

  fetch(API_BASE + '/api/results')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (payload) { boot(payload); })
    .catch(function (err) {
      /* Log and stop. Render NOTHING destructive: no empty state, no error
         card, no cleared sections. Every placeholder stays "—" and all the
         prose still reads. FR8. */
      console.warn('overview: results unavailable, rendering prose with placeholders —', err);
    });

  function boot(payload) {
    var vm = buildVM(payload);
    state.vm = vm;
    state.lead = vm.leads.length ? vm.leads[0] : null;
    applySynthetic(payload.meta);
    renderLeadToggle();
    refresh();
  }

  /* Everything that depends on the selected lead. */
  function refresh() {
    var vm = state.vm;
    if (!vm) return;
    vm.sel = vm.per[String(state.lead)] || null;
    bindAll(vm);
    hideEmptyLeadSlots(vm);
    renderDeltas(vm);
    renderDiagrams();
    renderGfsVerdict(vm);
  }

  /* ── view-model ───────────────────────────────────────────────────── */

  function buildVM(payload) {
    var vm = {
      meta: payload.meta,
      leads: payload.lead_times || [],
      leadsLabel: (payload.lead_times || []).map(function (l) { return l + 'h'; }).join(', '),
      per: {},
      byIndex: [],
      sel: null,
      guardOk: true
    };

    vm.leads.forEach(function (lead) {
      /* results is keyed by STRINGS ("6"); lead_times are INTS (6).
         Every index goes through String(lead). Named trap, app.js:22-24. */
      var L = payload.results[String(lead)];
      if (!L) return;

      var blends = L.blends || [];
      var models = (L.models || []).slice().sort(function (a, b) { return a.mae - b.mae; });

      /* The winner carries no weights and need not be blends[0]: it was
         picked in-sample and blends is sorted out-of-sample. Match on label.
         NEVER blends[0] — the winner ranked 5th / 23rd / 5th of 286 on the
         run this was built against. */
      var winnerRow = null;
      for (var i = 0; i < blends.length; i++) {
        if (blends[i].label === L.winner.label) { winnerRow = blends[i]; break; }
      }

      /* The un-fitted comparison: drop GFS, average what is left. Derived,
         not typed — renormalize spreads ten tenths over the remaining models
         by largest remainder in canonical order, which is the nearest point
         on the 0.1 lattice to an equal split. findBlend then looks it up
         exactly, and returns null on a miss. */
      var noGfs = MODELS.filter(function (m) { return m !== 'GFS'; });
      var unfittedWeights = M.renormalize({}, null, 0, noGfs);
      var dropGfs = blends.length ? M.findBlend(blends, unfittedWeights) : null;

      var bestSingle = L.best_single_model || {};
      var entry = {
        lead: lead,
        leadLabel: lead + 'h',
        nModels: (payload.meta.models_included || []).length,
        nBlends: blends.length,
        /* Kept on the entry so D-4 can call slicePoints without reaching
           back into the raw payload. */
        blendsRef: blends,
        nSamples: {
          train: L.n_samples ? L.n_samples.train : null,
          test: L.n_samples ? L.n_samples.test : null,
          total: L.n_samples ? (L.n_samples.train + L.n_samples.test) : null
        },
        join: L.join_diagnostics || {},
        models: models,
        bestSingle: { model: bestSingle.model, mae_oos: bestSingle.mae_out_of_sample },
        winner: {
          label: L.winner.label,
          mae_oos: L.winner.mae_out_of_sample,
          improvement_pct: L.winner.improvement_pct_vs_best_single,
          weights: winnerRow ? winnerRow.weights : null
        },
        winnerRank: winnerRow ? winnerRow.rank : null,
        dropGfs: dropGfs,
        dropGfsImprovementPct: null,
        unfittedWeights: unfittedWeights
      };

      /* Integrity guard on the one derived number on this page.
         Apply the improvement formula to the WINNER first and require it to
         reproduce the served improvement_pct to 2 dp. If the served document
         computes it any other way, this page has no licence to compute it for
         the un-fitted blend either: suppress every derived percentage and
         show raw errors only. Never quietly publish a number the pipeline
         would disagree with. */
      var base = entry.bestSingle.mae_oos;
      if (typeof base === 'number' && base > 0) {
        var reproduced = pctVs(base, entry.winner.mae_oos);
        var served = entry.winner.improvement_pct;
        if (typeof served === 'number' && Math.abs(reproduced - served) < 0.005) {
          if (dropGfs) entry.dropGfsImprovementPct = pctVs(base, dropGfs.mae_out_of_sample);
        } else {
          vm.guardOk = false;
          console.warn('overview: derived-improvement guard failed at lead ' + lead +
            ' (reproduced ' + reproduced + ' vs served ' + served +
            '). Suppressing every derived percentage; raw errors only.');
        }
      }

      vm.per[String(lead)] = entry;
      vm.byIndex.push(entry);
    });

    /* One failed guard suppresses the derived percentage everywhere, not
       just at the lead that failed. */
    if (!vm.guardOk) {
      vm.byIndex.forEach(function (e) { e.dropGfsImprovementPct = null; });
    }
    return vm;
  }

  function pctVs(base, x) {
    if (typeof base !== 'number' || typeof x !== 'number' || !(base > 0)) return null;
    return (base - x) / base * 100;
  }

  /* ── synthetic signals — the same ONE boolean, the same three signals,
        byte-for-byte the pattern at app.js:57-64. Never re-derived from
        meta.source. Never softened, in either theme (SPEC §10). ── */
  function applySynthetic(meta) {
    if (!meta.is_synthetic) return;
    document.documentElement.setAttribute('data-synthetic', 'true');
    document.title = '[SYNTHETIC] ' + document.title;
    $('synthetic-banner').textContent =
      'SYNTHETIC DEMO DATA — these numbers are fabricated. Not a real backtest. Generated ' +
      meta.generated_at + '.';
  }

  /* ── binding ──────────────────────────────────────────────────────── */

  var DASH = '—';

  function resolve(root, path) {
    var parts = String(path).split('.');
    var cur = root;
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined) return null;
      cur = cur[parts[i]];
    }
    return (cur === undefined) ? null : cur;
  }

  function format(v, kind) {
    if (v === null || v === undefined) return DASH;
    switch (kind) {
      case 'degF':      return F.fmtF(v);
      case 'pct':       return F.fmtSignedPct(v);
      case 'pctPlain':  return (typeof v === 'number' && isFinite(v)) ? v.toFixed(2) + '%' : DASH;
      case 'int':       return (typeof v === 'number' && isFinite(v)) ? String(Math.round(v)) : DASH;
      case 'num2':      return F.fmtNum(v, 2);
      case 'list':      return (v && v.length) ? v.join(', ') : DASH;
      case 'datetime':  return String(v).replace('T', ' ').replace(':00Z', 'Z');
      case 'excluded':
        /* models_excluded is a LIST and it being empty is a result worth
           stating, not an absence worth hiding. */
        if (!v || !v.length) return 'models_excluded: [] — nothing was excluded';
        return 'models_excluded: ' + v.map(function (x) { return x.model; }).join(', ');
      case 'raw':
      default:
        return (v === '') ? DASH : String(v);
    }
  }

  function bindAll(vm) {
    var els = document.querySelectorAll('[data-live]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var v = resolve(vm, el.getAttribute('data-live'));
      /* A miss restores the dash rather than leaving a stale value from the
         previously selected lead. The surrounding sentences are written so
         they still read correctly without the number. */
      el.textContent = (v === null) ? DASH : format(v, el.getAttribute('data-fmt'));
    }
  }

  /* A run with fewer lead times must not leave an all-dashes tile on screen. */
  function hideEmptyLeadSlots(vm) {
    var slots = document.querySelectorAll('[data-lead-slot]');
    for (var i = 0; i < slots.length; i++) {
      var idx = Number(slots[i].getAttribute('data-lead-slot'));
      slots[i].hidden = !vm.byIndex[idx];
    }
  }

  /* The signed change gets its colour from the sign of the value — never
     assumed positive, never abs()'d. A negative result is a finding. */
  function renderDeltas(vm) {
    var els = document.querySelectorAll('[data-delta-slot]');
    for (var i = 0; i < els.length; i++) {
      var e = vm.byIndex[Number(els[i].getAttribute('data-delta-slot'))];
      var v = e ? e.winner.improvement_pct : null;
      els[i].classList.remove('up', 'down', 'flat');
      if (typeof v !== 'number' || !isFinite(v)) continue;
      els[i].classList.add(v > 0.05 ? 'up' : (v < -0.05 ? 'down' : 'flat'));
    }
  }

  /* ── lead toggle ──────────────────────────────────────────────────── */
  function renderLeadToggle() {
    var box = $('overview-lead-toggle');
    if (!box) return;
    box.textContent = '';
    state.vm.leads.forEach(function (lead) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-lead', String(lead));
      b.setAttribute('aria-pressed', lead === state.lead ? 'true' : 'false');
      b.textContent = lead + 'h';
      b.addEventListener('click', function () {
        if (state.lead === lead) return;
        state.lead = lead;
        var btns = box.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
          btns[i].setAttribute('aria-pressed',
            btns[i].getAttribute('data-lead') === String(lead) ? 'true' : 'false');
        }
        refresh();
      });
      box.appendChild(b);
    });
  }

  /* ── diagram helpers ──────────────────────────────────────────────── */

  function modelVar(m) { return 'var(--model-' + m.toLowerCase() + ')'; }

  function svgOpen(w, h, label) {
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(label) + '">';
  }

  function text(x, y, cls, anchor, s) {
    return '<text class="' + cls + '" x="' + x + '" y="' + y + '" text-anchor="' + anchor +
      '">' + esc(s) + '</text>';
  }

  function setDiagram(id, captionId, svg, caption) {
    var host = $(id);
    if (host) host.innerHTML = svg || '';
    var cap = $(captionId);
    if (cap) cap.textContent = caption || '';
  }

  function renderDiagrams() {
    try { renderD1(); } catch (e) { console.warn('D-1 skipped', e); }
    try { renderD2(); } catch (e) { console.warn('D-2 skipped', e); }
    try { renderD3(); } catch (e) { console.warn('D-3 skipped', e); }
    try { renderD4(); } catch (e) { console.warn('D-4 skipped', e); }
    try { renderD5(); } catch (e) { console.warn('D-5 skipped', e); }
  }

  /* ── D-1: what a blend is ─────────────────────────────────────────── */
  function renderD1() {
    var e = state.vm && state.vm.sel;
    if (!e || !e.models.length) return;

    var W = 680, LEFT = 84, RIGHT = 560, ROW = 30, TOP = 48;
    var rows = e.models;
    var haveBlend = (typeof e.winner.mae_oos === 'number');
    var vals = rows.map(function (r) { return r.mae; });
    if (haveBlend) vals.push(e.winner.mae_oos);
    var max = Math.max.apply(null, vals) || 1;
    var span = RIGHT - LEFT;
    var blendY = TOP + rows.length * ROW + 22;
    var H = blendY + 96;

    var s = svgOpen(W, H, 'Each model\'s error, and the winning blend of them');
    s += text(LEFT, 22, 'dg-axis', 'start', 'Out-of-sample error at ' + e.leadLabel +
      ' — every bar starts at the observation, so shorter is better');

    /* The observation is the reference: zero error, at the origin. One rule
       down the whole diagram so the blend is measured against the same zero
       as the single models. */
    s += '<line class="dg-rule-strong" x1="' + LEFT + '" x2="' + LEFT + '" y1="' + (TOP - 10) +
      '" y2="' + (blendY + 26) + '"/>';
    s += text(LEFT - 8, TOP - 14, 'dg-axis', 'end', 'observed');

    rows.forEach(function (r, i) {
      var y = TOP + i * ROW;
      var w = Math.max(2, (r.mae / max) * span);
      s += text(LEFT - 8, y + 11, 'dg-label', 'end', r.model);
      s += '<rect x="' + LEFT + '" y="' + y + '" width="' + w.toFixed(1) +
        '" height="14" rx="3" style="fill: ' + modelVar(r.model) + '"/>';
      s += text(LEFT + w + 8, y + 11, 'dg-value', 'start', F.fmtF(r.mae));
    });

    s += '<line class="dg-rule" x1="' + LEFT + '" x2="' + RIGHT + '" y1="' + (blendY - 14) +
      '" y2="' + (blendY - 14) + '"/>';

    /* The blend row uses the SAME error scale as the bars above — its length
       is its error — while the segment widths inside it are the weights, in
       canonical model order. One bar, both facts, no second axis to confuse
       with the first. */
    if (haveBlend) {
      var total = (e.winner.mae_oos / max) * span;
      var wts = e.winner.weights;
      s += text(LEFT - 8, blendY + 13, 'dg-label', 'end', 'blend');
      if (wts) {
        var x = LEFT;
        MODELS.forEach(function (m) {
          var wv = Number(wts[m]) || 0;
          if (wv <= 0) return;
          var segW = wv * total;
          s += '<rect x="' + x.toFixed(1) + '" y="' + blendY + '" width="' + segW.toFixed(1) +
            '" height="20" style="fill: ' + modelVar(m) + '"/>';
          if (segW > 46) {
            s += '<text class="dg-label" x="' + (x + segW / 2).toFixed(1) + '" y="' +
              (blendY + 14) + '" text-anchor="middle" style="fill: var(--bg-elev)">' +
              esc(m + ' ' + F.fmtPct0(wv)) + '</text>';
          }
          x += segW;
        });
      } else {
        s += '<rect class="dg-track" x="' + LEFT + '" y="' + blendY + '" width="' +
          total.toFixed(1) + '" height="20" rx="3"/>';
      }
      s += text(LEFT + total + 8, blendY + 14, 'dg-value', 'start', F.fmtF(e.winner.mae_oos));
      s += text(LEFT, blendY + 44, 'dg-axis', 'start', e.winner.label);
    }
    s += '</svg>';

    setDiagram('d1', 'd1-caption', s,
      'Four models, four errors, and one blend of them. The blend bar is drawn on the same ' +
      'error scale as the models above it — its length is its error — while the coloured ' +
      'segments inside it are the weights. The weights sum to 1 and the grid step is 0.1, ' +
      'so each model\'s share moves in tenths. The blend\'s error is looked up on the grid, ' +
      'never interpolated between the bars above it.');
  }

  /* ── D-2: the ±30 minute join ─────────────────────────────────────── */
  function renderD2() {
    var e = state.vm && state.vm.sel;
    if (!e) return;

    var W = 680, H = 232, LEFT = 110, RIGHT = 610;
    var AX = 96, RTOP = 58, RBOT = 146;
    /* Axis runs to just past the window edge so the ±30 rule fills the strip
       and a offset of a few minutes is actually visible. */
    var SPAN_MIN = 35;
    var mid = (LEFT + RIGHT) / 2;
    var perMin = ((RIGHT - LEFT) / 2) / SPAN_MIN;
    var x = function (m) { return mid + m * perMin; };

    /* The ±30 window and the :52 reporting pattern are structural facts about
       the join rule and about METAR, not results, so they are literal. The
       OFFSET is data: it is the mean absolute offset this run measured. */
    var off = e.join.mean_abs_offset_min;
    var haveOff = (typeof off === 'number' && isFinite(off));
    var obsX = x(-(haveOff ? Math.min(off, SPAN_MIN) : 8));

    var s = svgOpen(W, H, 'The plus or minus thirty minute join between forecasts and observations');

    s += '<rect class="dg-window" x="' + x(-30).toFixed(1) + '" y="' + RTOP + '" width="' +
      (60 * perMin).toFixed(1) + '" height="' + (RBOT - RTOP) + '" rx="4"/>';
    s += '<line class="dg-rule" x1="' + LEFT + '" x2="' + RIGHT + '" y1="' + AX + '" y2="' + AX + '"/>';

    /* Observation, placed by the measured offset — above the axis. */
    s += '<circle class="dg-obs" cx="' + obsX.toFixed(1) + '" cy="' + AX + '" r="5"/>';
    s += text(obsX, RTOP - 12, 'dg-strong', 'middle', 'observation reported at :52');
    s += '<line class="dg-rule-strong" x1="' + obsX.toFixed(1) + '" x2="' + obsX.toFixed(1) +
      '" y1="' + (RTOP - 6) + '" y2="' + (AX - 8) + '"/>';

    /* Forecast valid time — below the axis. */
    s += '<circle class="dg-dot" cx="' + mid + '" cy="' + AX + '" r="5"/>';
    s += '<line class="dg-rule-strong" x1="' + mid + '" x2="' + mid + '" y1="' + (AX + 8) +
      '" y2="' + (RBOT + 8) + '"/>';
    s += text(mid, RBOT + 26, 'dg-strong', 'middle', 'forecast valid 18:00Z');

    /* The offset itself, measured between the two, inside the window. */
    if (haveOff) {
      s += '<line class="dg-rule-strong" x1="' + obsX.toFixed(1) + '" x2="' + mid +
        '" y1="' + (AX + 18) + '" y2="' + (AX + 18) + '"/>';
      s += text((obsX + mid) / 2, AX + 34, 'dg-value', 'middle', F.fmtNum(off, 2) + ' min');
    }

    s += text(x(-30), RBOT + 26, 'dg-axis', 'middle', '−30 min');
    s += text(x(30), RBOT + 26, 'dg-axis', 'middle', '+30 min');
    s += text(mid, RTOP - 34, 'dg-axis', 'middle', 'the ±30 minute matching window');

    var matched = (typeof e.join.matched_pct === 'number')
      ? F.fmtNum(e.join.matched_pct, 2) + '%' : DASH;
    var n = (e.nSamples.total === null) ? DASH : String(e.nSamples.total);
    s += text(LEFT - 30, H - 8, 'dg-value', 'start',
      matched + ' of forecast rows matched  ·  ' + n + ' pairs at ' + e.leadLabel);
    s += '</svg>';

    setDiagram('d2', 'd2-caption', s,
      'An exact-timestamp join matches zero rows — and a zero-row join does not error, it ' +
      'scores perfectly, because the mean of an empty set of errors is vacuously excellent. ' +
      'That the mean offset is a few minutes rather than 0.00 is the evidence the join is ' +
      'doing real work: it is the station\'s :52 reporting pattern showing up as data. ' +
      'Observations are never interpolated — a missing one is dropped, never invented.');
  }

  /* ── D-3: the split, as a timeline ────────────────────────────────── */
  function renderD3() {
    var vm = state.vm, e = vm && vm.sel;
    if (!e) return;
    var sp = vm.meta.split || {}, win = vm.meta.window || {};
    var days = win.days, train = sp.train_days, test = sp.test_days;
    if (typeof days !== 'number' || typeof train !== 'number') return;

    var W = 680, H = 176, LEFT = 40, RIGHT = 640, TOP = 56;
    var cellGap = 2;
    var cw = (RIGHT - LEFT - (days - 1) * cellGap) / days;

    var s = svgOpen(W, H, 'The chronological train and test split across the scored window');
    s += text(LEFT, 22, 'dg-axis', 'start', 'The scored window, one cell per day');

    for (var i = 0; i < days; i++) {
      var cx = LEFT + i * (cw + cellGap);
      s += '<rect class="' + (i < train ? 'dg-train' : 'dg-test') + '" x="' + cx.toFixed(1) +
        '" y="' + TOP + '" width="' + cw.toFixed(1) + '" height="34" rx="2"/>';
    }

    var bx = LEFT + train * (cw + cellGap) - cellGap / 2;
    s += '<line class="dg-rule-strong" x1="' + bx.toFixed(1) + '" x2="' + bx.toFixed(1) +
      '" y1="' + (TOP - 12) + '" y2="' + (TOP + 46) + '"/>';

    var trainMid = LEFT + (train * (cw + cellGap)) / 2;
    var testMid = bx + ((RIGHT - bx) / 2);
    s += text(trainMid, TOP - 18, 'dg-strong', 'middle', 'fit the weights here');
    s += text(testMid, TOP - 18, 'dg-strong', 'middle', 'score here, unseen');
    s += text(trainMid, TOP + 62, 'dg-value', 'middle', train + ' days · ' +
      (e.nSamples.train === null ? DASH : e.nSamples.train) + ' samples');
    s += text(testMid, TOP + 62, 'dg-value', 'middle',
      (typeof test === 'number' ? test : days - train) + ' days · ' +
      (e.nSamples.test === null ? DASH : e.nSamples.test) + ' samples');

    if (win.start) s += text(LEFT, TOP + 84, 'dg-axis', 'start', String(win.start));
    if (win.end) s += text(RIGHT, TOP + 84, 'dg-axis', 'end', String(win.end));
    s += '</svg>';

    setDiagram('d3', 'd3-caption', s,
      'The split is chronological, not shuffled. A random split would leak tomorrow\'s ' +
      'weather regime into today\'s training set, and the resulting number would flatter ' +
      'the method for a reason that has nothing to do with the method.');
  }

  /* ── D-4: the error-vs-weight dip ─────────────────────────────────── */
  function renderD4() {
    var vm = state.vm, e = vm && vm.sel;
    if (!e || !e.models.length) return;
    var blends = e.blendsRef;
    if (!blends || !blends.length) return;

    /* The two lowest-error single models at THIS lead — read from the data,
       never hardcoded to a pair of names. */
    var a = e.models[0] && e.models[0].model;
    var b = e.models[1] && e.models[1].model;
    if (!a || !b) return;

    /* slicePoints ONLY. BharChart.render bakes resolved hexes. */
    var pts = window.BharChart.slicePoints(blends, a, b).filter(function (p) { return p.y !== null; });
    if (pts.length < 2) return;

    var W = 680, H = 300, PL = 62, PR = 96, PT = 26, PB = 46;
    var iw = W - PL - PR, ih = H - PT - PB;
    var ys = pts.map(function (p) { return p.y; });
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    var pad = (hi - lo) * 0.15 || 1, y0 = lo - pad, y1 = hi + pad;
    var sx = function (v) { return (PL + (v / 100) * iw).toFixed(1); };
    var sy = function (v) { return (PT + ih - ((v - y0) / (y1 - y0)) * ih).toFixed(1); };

    var s = svgOpen(W, H, 'Out-of-sample error against the weight given to ' + a);

    for (var g = 0; g <= 4; g++) {
      var yv = y0 + (y1 - y0) * (g / 4), yy = sy(yv);
      s += '<line class="dg-rule" x1="' + PL + '" x2="' + (PL + iw) + '" y1="' + yy +
        '" y2="' + yy + '"/>';
      s += text(PL - 8, Number(yy) + 3.5, 'dg-axis', 'end', yv.toFixed(1));
    }
    for (var k = 0; k <= 10; k += 2) {
      s += text(sx(k * 10), PT + ih + 18, 'dg-axis', 'middle', (k * 10) + '%');
    }
    s += text(PL + iw / 2, H - 8, 'dg-axis', 'middle',
      a + ' weight  (remainder to ' + b + ')');

    /* Curve in the leading model's colour, via the CSS variable. */
    s += '<path class="dg-line" style="stroke: ' + modelVar(a) + '" d="' +
      pts.map(function (p, i) { return (i ? 'L' : 'M') + sx(p.x) + ' ' + sy(p.y); }).join(' ') + '"/>';

    var minP = null;
    pts.forEach(function (p) { if (!minP || p.y < minP.y) minP = p; });

    pts.forEach(function (p) {
      var end = (p.x === 0 || p.x === 100);
      var col = end ? modelVar(p.x === 100 ? a : b) : modelVar(a);
      s += '<circle class="dg-dot" cx="' + sx(p.x) + '" cy="' + sy(p.y) + '" r="' +
        (end ? 5 : 3.5) + '" style="fill: ' + col + '"/>';
    });
    if (minP) {
      s += '<circle class="dg-min" cx="' + sx(minP.x) + '" cy="' + sy(minP.y) +
        '" r="7" style="stroke: ' + modelVar(a) + '"/>';
      s += text(sx(minP.x), Number(sy(minP.y)) - 15, 'dg-value', 'middle',
        'lowest here · ' + F.fmtF(minP.y));
    }
    var p0 = pts[0], pN = pts[pts.length - 1];
    if (p0 && p0.x === 0) {
      s += '<text class="dg-label" x="' + (Number(sx(0)) + 8) + '" y="' + (Number(sy(p0.y)) - 10) +
        '" text-anchor="start" style="fill: ' + modelVar(b) + '">' + esc('pure ' + b) + '</text>';
    }
    if (pN && pN.x === 100) {
      s += '<text class="dg-label" x="' + (Number(sx(100)) + 8) + '" y="' + (Number(sy(pN.y)) + 4) +
        '" text-anchor="start" style="fill: ' + modelVar(a) + '">' + esc('pure ' + a) + '</text>';
    }
    s += '</svg>';

    var held = MODELS.filter(function (m) { return m !== a && m !== b; });
    setDiagram('d4', 'd4-caption', s,
      a + ' against ' + b + ' at ' + e.leadLabel + ', with ' + held.join(' and ') +
      ' held at 0. Both ends of the curve are genuinely pure single models, and the dip in ' +
      'between is the whole idea. But the leaderboard on the live page searches the full ' +
      'four-model space, not this slice — so if the chart\'s best point disagrees with the ' +
      'leaderboard\'s winner, the leaderboard is right. It searched more.');
  }

  /* ── D-5: the GFS panel [NEVER CUT] ───────────────────────────────── */
  function bar(weights) {
    if (!weights) return '';
    var h = '<div class="gfs-bar">';
    MODELS.forEach(function (m) {
      var w = Number(weights[m]) || 0;
      if (w <= 0) return;
      h += '<span class="wbar-seg" style="width: ' + (w * 100) + '%; --seg-color: ' +
        modelVar(m) + '" title="' + esc(m + ' ' + F.fmtPct0(w)) + '"></span>';
    });
    return h + '</div>';
  }

  function col(kind, label, weights, mae, rank, nBlends, pct, better) {
    var h = '<div class="gfs-col' + (better ? ' is-better' : '') + '">';
    h += '<div class="gfs-col-kind"><span>' + esc(kind) + '</span>' +
      (better ? '<span class="gfs-flag">lower error</span>' : '') + '</div>';
    h += '<div class="gfs-col-label">' + esc(label || DASH) + '</div>';
    h += bar(weights);
    h += '<div class="gfs-col-value">' + esc(typeof mae === 'number' ? F.fmtF(mae) : DASH) + '</div>';
    h += '<div class="stat-row"><span>Out-of-sample rank</span><span class="num">' +
      esc(rank ? rank + ' of ' + nBlends : DASH) + '</span></div>';
    h += '<div class="stat-row"><span>vs best single model</span><span class="num">' +
      esc(typeof pct === 'number' ? F.fmtSignedPct(pct) : DASH) + '</span></div>';
    return h + '</div>';
  }

  function renderD5() {
    var vm = state.vm, e = vm && vm.sel;
    if (!e) return;

    var d = e.dropGfs;
    var winnerBetter = d && typeof d.mae_out_of_sample === 'number' &&
      typeof e.winner.mae_oos === 'number' && e.winner.mae_oos < d.mae_out_of_sample;
    var unfittedBetter = d && typeof d.mae_out_of_sample === 'number' &&
      typeof e.winner.mae_oos === 'number' && d.mae_out_of_sample <= e.winner.mae_oos;

    var h = '<div class="gfs-cols">';
    h += col('Fitted winner', e.winner.label, e.winner.weights, e.winner.mae_oos,
      e.winnerRank, e.nBlends, e.winner.improvement_pct, winnerBetter);
    h += col('Un-fitted: drop GFS, average the rest', d ? d.label : null,
      d ? d.weights : e.unfittedWeights, d ? d.mae_out_of_sample : null,
      d ? d.rank : null, e.nBlends, e.dropGfsImprovementPct, unfittedBetter);
    h += '</div>';

    /* All three leads at once, so "what about the other leads?" is answered
       without touching the toggle. */
    h += '<table class="gfs-table"><thead><tr><th>Lead</th>' +
      '<th class="right">Un-fitted, drop GFS</th>' +
      '<th class="right">Fitted winner</th>' +
      '<th class="right">Best single model</th>' +
      '<th class="right">Un-fitted rank</th></tr></thead><tbody>';
    vm.byIndex.forEach(function (x) {
      var dd = x.dropGfs;
      h += '<tr><td>' + esc(x.leadLabel) + '</td>' +
        '<td class="right mono">' + esc(dd ? F.fmtF(dd.mae_out_of_sample) : DASH) + '</td>' +
        '<td class="right mono">' + esc(F.fmtF(x.winner.mae_oos)) + '</td>' +
        '<td class="right mono">' + esc((x.bestSingle.model || '') + ' ' +
          F.fmtF(x.bestSingle.mae_oos)) + '</td>' +
        '<td class="right mono">' + esc(dd ? dd.rank + ' of ' + x.nBlends : DASH) + '</td></tr>';
    });
    h += '</tbody></table>';

    setDiagram('d5', 'd5-caption', h,
      'Both columns are exact lookups on the same grid and are scored by the same code. ' +
      'The un-fitted blend uses no optimisation, no training window and no search — it ' +
      'simply drops GFS and splits the remainder as evenly as the 0.1 grid allows. ' +
      'Whichever column carries the lower error is marked from that comparison, not from ' +
      'an assumption about which one ought to win.');
  }

  /* ── the §6 verdict, assembled at runtime ─────────────────────────── */
  function renderGfsVerdict(vm) {
    var line = $('gfs-verdict'), detail = $('gfs-verdict-detail');
    var claim = $('gfs-surviving-claim');
    if (!line) return;
    line.textContent = '';
    if (detail) detail.textContent = '';

    var usable = vm.byIndex.filter(function (e) {
      return e.dropGfs && typeof e.dropGfs.mae_out_of_sample === 'number' &&
        typeof e.winner.mae_oos === 'number';
    });
    if (!usable.length) {
      /* Never guess. The prose around this block reads correctly with the
         verdict absent. */
      if (claim) claim.textContent = DASH;
      return;
    }

    var matchedOrBeat = usable.filter(function (e) {
      return e.dropGfs.mae_out_of_sample <= e.winner.mae_oos;
    });
    var lost = usable.filter(function (e) {
      return e.dropGfs.mae_out_of_sample > e.winner.mae_oos;
    });
    var names = function (arr) { return arr.map(function (e) { return e.leadLabel; }).join(' and '); };

    if (matchedOrBeat.length === usable.length) {
      line.textContent = 'The un-fitted blend matches or beats the fitted winner at every ' +
        'lead time measured (' + names(usable) + '). Fitting the weights bought nothing here.';
    } else if (matchedOrBeat.length) {
      line.textContent = 'The un-fitted blend matches or beats the fitted winner at ' +
        names(matchedOrBeat) + ', and loses to it only at ' + names(lost) + '.';
    } else {
      line.textContent = 'The fitted winner beats the un-fitted blend at every lead time ' +
        'measured (' + names(usable) + '), so on this run the fitting is doing real work.';
    }

    /* Name any lead where the un-fitted vector is the floor of the whole
       space — that is the strongest form of the finding and it must not be
       left to the reader to spot in the table. */
    var floors = usable.filter(function (e) { return e.dropGfs.rank === 1; });
    if (detail) {
      var bits = [];
      if (floors.length) {
        bits.push('At ' + names(floors) + ' the un-fitted blend is rank 1 of ' +
          floors[0].nBlends + ' — the lowest out-of-sample error of every vector searched.');
      }
      bits.push('Every figure in this section is looked up from the served document at ' +
        'load time, so a re-run that reverses this finding will say so here without anyone ' +
        'editing the page.');
      detail.textContent = bits.join(' ');
    }

    if (claim) {
      claim.textContent = lost.length
        ? ('a little at ' + names(lost) + ', and nothing measurable at ' + names(matchedOrBeat))
        : 'nothing measurable at any lead time tested';
    }
  }

  /* ── theme ────────────────────────────────────────────────────────── */
  /* The diagrams use var(--model-*) and semantic tokens throughout, so they
     repaint themselves. Re-rendering anyway costs nothing and removes a whole
     class of "one surface stayed light" bug from this page. The prose
     bindings are colour-free and are not touched. */
  if (window.BharTheme) {
    window.BharTheme.mount($('theme-toggle'));
    window.BharTheme.onChange(function () {
      M.resetColors();
      renderDiagrams();
    });
  }

  window.BharOverview = { state: state };
})();
