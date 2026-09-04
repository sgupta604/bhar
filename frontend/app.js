/* app.js — data layer, state, and every render. Plain script, globals only. */
(function () {
  'use strict';

  var M = window.BharModels, F = window.BharFormat;
  var MODELS = M.MODELS;

  /* API base. The only place the default port is written down. */
  var API_BASE = new URLSearchParams(location.search).get('api') || 'http://localhost:8000';

  var state = {
    data: null,
    lead: null,            // int, as it appears in meta.lead_times
    enabled: MODELS.slice(),
    weights: null,
    pair: null             // [a, b] for the chart slice
  };

  var $ = function (id) { return document.getElementById(id); };

  /* results is keyed by STRINGS ("6"), lead_times are INTS (6).
     Every index into results goes through String(lead). Named trap. */
  function leadData(lead) {
    return state.data.results[String(lead)];
  }

  /* ── boot ─────────────────────────────────────────────────────────── */

  fetch(API_BASE + '/api/results')
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

  function boot(payload) {
    state.data = payload;
    state.lead = payload.lead_times[0];
    applySynthetic(payload.meta);
    renderHeader();
    renderLeadToggle();
    renderModelBar();
    renderLead();
  }

  /* ── D2: all synthetic signals from the ONE boolean meta.is_synthetic ── */
  function applySynthetic(meta) {
    if (!meta.is_synthetic) return;         // attribute absent => banner, frame, prefix all vanish
    document.documentElement.setAttribute('data-synthetic', 'true');
    document.title = '[SYNTHETIC] ' + document.title;
    $('synthetic-banner').textContent =
      'SYNTHETIC DEMO DATA — these numbers are fabricated. Not a real backtest. Generated ' +
      meta.generated_at + '.';
  }

  /* ── header ───────────────────────────────────────────────────────── */
  function renderHeader() {
    var meta = state.data.meta;
    /* Candidate count comes from the data (blends.length), never hardcoded. */
    var n = leadData(state.lead).blends.length;
    $('header-scope').textContent = 'Last ' + meta.window.days + ' days · 2m temperature, ' +
      n + ' candidate blends scored vs METAR';
    $('header-site').textContent = meta.site.name;
  }

  /* ── lead toggle (Clarity .segmented) ─────────────────────────────── */
  function renderLeadToggle() {
    var box = $('lead-toggle');
    box.textContent = '';
    state.data.lead_times.forEach(function (lead) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-lead', String(lead));
      b.setAttribute('aria-pressed', lead === state.lead ? 'true' : 'false');
      b.textContent = lead + 'h';
      b.addEventListener('click', function () {
        if (state.lead === lead) return;
        state.lead = lead;
        Array.prototype.forEach.call(box.querySelectorAll('button'), function (x) {
          x.setAttribute('aria-pressed', x.getAttribute('data-lead') === String(lead) ? 'true' : 'false');
        });
        renderHeader();
        renderLead();          // re-renders EVERY panel from the same payload — no refetch
      });
      box.appendChild(b);
    });
  }

  /* ── model checkboxes ─────────────────────────────────────────────── */
  function renderModelBar() {
    var bar = $('model-bar'), colors = M.modelColors();
    Array.prototype.forEach.call(bar.querySelectorAll('.model-chip, .model-warn'), function (n) { n.remove(); });
    MODELS.forEach(function (m) {
      var on = state.enabled.indexOf(m) !== -1;
      var lab = document.createElement('label');
      lab.className = 'model-chip' + (on ? '' : ' is-off');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.setAttribute('data-model', m);
      cb.checked = on;
      cb.addEventListener('change', function () { onModelToggle(m, cb); });
      var dot = document.createElement('span');
      dot.className = 'model-dot';
      dot.style.setProperty('--model-color', colors[m]);
      var txt = document.createElement('span');
      txt.textContent = m;
      lab.appendChild(cb); lab.appendChild(dot); lab.appendChild(txt);
      bar.appendChild(lab);
    });
  }

  function setModelWarning(msg) {
    var bar = $('model-bar');
    var w = bar.querySelector('.model-warn');
    if (!msg) { if (w) w.remove(); return; }
    if (!w) { w = document.createElement('span'); w.className = 'model-warn'; bar.appendChild(w); }
    w.textContent = msg;
  }

  function onModelToggle(model, cb) {
    if (!cb.checked) {
      if (state.enabled.length <= 1) {         // refuse the last uncheck; never zero models
        cb.checked = true;
        setModelWarning('Select at least one model.');
        return;
      }
      state.enabled = state.enabled.filter(function (x) { return x !== model; });
    } else if (state.enabled.indexOf(model) === -1) {
      state.enabled = MODELS.filter(function (x) {
        return x === model || state.enabled.indexOf(x) !== -1;
      });
    }
    setModelWarning('');
    renderModelBar();
    /* Zero the disabled model and renormalize what is left onto the lattice. */
    state.weights = M.renormalize(state.weights, null, 0, state.enabled);
    renderLeaderboard();
    renderSliders();
    renderReadout();
    renderChartRegion();
    renderFooter();
  }

  /* ── lead-scoped render ───────────────────────────────────────────── */
  function renderLead() {
    var L = leadData(state.lead);
    /* Sliders initialize to the WINNER's weights, on load and every lead change.
       Winner is matched by label, never by index 0. */
    var wb = winnerBlend(L);
    state.weights = M.renormalize(wb ? wb.weights : {}, null, 0, state.enabled);
    state.pair = null;
    renderLeaderboard();
    renderSliders();
    renderReadout();
    renderChartRegion();
    renderFooter();
  }

  /* D13: the winner is the IN-SAMPLE pick and need not be OOS rank 1.
     Match on winner.label. Never blends[0]. */
  function winnerBlend(L) {
    for (var i = 0; i < L.blends.length; i++) {
      if (L.blends[i].label === L.winner.label) return L.blends[i];
    }
    return null;
  }

  function improvementState(v) {
    if (v > 0.05) return 'positive';
    if (v < -0.05) return 'negative';
    return 'tie';
  }

  function passesFilter(b) {
    for (var i = 0; i < MODELS.length; i++) {
      var m = MODELS[i];
      if (state.enabled.indexOf(m) === -1 && (Number(b.weights[m]) || 0) > 1e-9) return false;
    }
    return true;
  }

  /* ── leaderboard ──────────────────────────────────────────────────── */
  function renderLeaderboard() {
    var L = leadData(state.lead), tb = $('leaderboard-rows'), colors = M.modelColors();
    tb.textContent = '';
    var visible = L.blends.filter(passesFilter);
    var pures = visible.filter(function (b) { return b.is_pure; });
    var top5 = visible.filter(function (b) { return !b.is_pure; }).slice(0, 5);
    var rows = top5.concat(pures);
    var wb = winnerBlend(L);
    if (wb && passesFilter(wb)) rows.push(wb);          // winner always visible
    var seen = {}, dedup = [];
    rows.forEach(function (b) { if (!seen[b.label]) { seen[b.label] = 1; dedup.push(b); } });
    dedup.sort(function (a, b) { return a.mae_out_of_sample - b.mae_out_of_sample; });

    var tone = improvementState(L.winner.improvement_pct_vs_best_single);

    if (!dedup.length) {
      var tr0 = document.createElement('tr');
      var td0 = document.createElement('td');
      td0.colSpan = 4; td0.className = 'empty-rows';
      td0.textContent = 'No blends match the selected models.';
      tr0.appendChild(td0); tb.appendChild(tr0);
    }

    dedup.forEach(function (b) {
      var tr = document.createElement('tr');
      tr.setAttribute('data-row', 'blend');
      var isWinner = wb && b.label === wb.label;
      if (isWinner) {
        tr.setAttribute('data-winner', 'true');
        tr.className = 'is-winner tone-' + tone;   // never green when improvement <= +0.05
      }

      var tdR = document.createElement('td');
      tdR.className = 'col-rank';
      tdR.textContent = '#' + b.rank;
      tr.appendChild(tdR);

      var tdL = document.createElement('td');
      tdL.className = 'col-label';
      tdL.appendChild(document.createTextNode(b.label));
      if (isWinner) {
        var badge = document.createElement('span');
        badge.className = 'badge-winner';
        badge.textContent = 'winner';
        tdL.appendChild(badge);
      }
      tr.appendChild(tdL);

      var tdB = document.createElement('td');
      tdB.className = 'col-bar';
      var bar = document.createElement('div');
      bar.className = 'wbar';
      MODELS.forEach(function (m) {                 // canonical order, left to right
        var w = Number(b.weights[m]) || 0;
        if (w <= 0) return;
        var seg = document.createElement('span');
        seg.style.width = (w * 100) + '%';
        seg.style.background = colors[m];
        seg.title = m + ' ' + Math.round(w * 100) + '%';
        bar.appendChild(seg);
      });
      tdB.appendChild(bar);
      tr.appendChild(tdB);

      var tdE = document.createElement('td');
      tdE.className = 'col-err';
      var cell = document.createElement('div');
      cell.className = 'err-cell';
      var oos = document.createElement('span');
      oos.className = 'err-oos';
      oos.textContent = F.fmtF(b.mae_out_of_sample);
      var ins = document.createElement('span');
      ins.className = 'err-ins';
      var insLab = document.createElement('span');
      insLab.className = 'ins-label';
      insLab.textContent = 'in-sample ';
      ins.appendChild(insLab);
      ins.appendChild(document.createTextNode(F.fmtF(b.mae_in_sample)));
      cell.appendChild(oos); cell.appendChild(ins);
      tdE.appendChild(cell);
      tr.appendChild(tdE);

      tb.appendChild(tr);
    });

    $('leaderboard-sub').textContent =
      'out-of-sample MAE · ' + dedup.length + ' of ' + L.blends.length + ' blends';
  }

  /* ── sliders ──────────────────────────────────────────────────────── */
  function renderSliders() {
    var host = $('slider-rows'), colors = M.modelColors();
    host.textContent = '';
    MODELS.forEach(function (m) {
      var on = state.enabled.indexOf(m) !== -1;
      var row = document.createElement('div');
      row.className = 'slider-row' + (on ? '' : ' is-off');

      var name = document.createElement('span');
      name.className = 'slider-name';
      var dot = document.createElement('span');
      dot.className = 'model-dot';
      dot.style.setProperty('--model-color', colors[m]);
      name.appendChild(dot);
      name.appendChild(document.createTextNode(m));

      var s = document.createElement('input');
      s.type = 'range';
      s.className = 'weight-slider';
      s.min = '0'; s.max = '100'; s.step = '10';
      s.setAttribute('data-model', m);
      s.disabled = !on;
      var pct = Math.round((Number(state.weights[m]) || 0) * 100);
      s.value = String(pct);
      s.style.setProperty('--slider-fill', colors[m]);
      s.style.setProperty('--slider-pct', pct + '%');
      /* Bound to `input` on the element itself so a programmatically
         dispatched input event drives it exactly like a drag. */
      s.addEventListener('input', function () { onSliderInput(m, s); });

      var val = document.createElement('span');
      val.className = 'slider-val';
      val.setAttribute('data-slider-val', m);
      val.textContent = pct + '%';

      row.appendChild(name); row.appendChild(s); row.appendChild(val);
      host.appendChild(row);
    });
  }

  function onSliderInput(model, s) {
    var v = M.snapTo10(s.value);
    state.weights = M.renormalize(state.weights, model, v / 100, state.enabled);
    syncSliders();
    renderReadout();
  }

  function syncSliders() {
    MODELS.forEach(function (m) {
      var s = document.querySelector('input[type=range][data-model="' + m + '"]');
      if (!s) return;
      var pct = Math.round((Number(state.weights[m]) || 0) * 100);
      if (s.value !== String(pct)) s.value = String(pct);
      s.style.setProperty('--slider-pct', pct + '%');
      var v = document.querySelector('[data-slider-val="' + m + '"]');
      if (v) v.textContent = pct + '%';
    });
  }

  /* EXACT LATTICE LOOKUP. No arithmetic on an error value, no interpolation,
     no network call. On a miss we say so and refuse to invent a number. */
  function renderReadout() {
    var L = leadData(state.lead);
    var out = $('weight-readout'), note = $('readout-note');
    var w = {};
    MODELS.forEach(function (m) { w[m] = Number(state.weights[m]) || 0; });
    out.setAttribute('data-weights', JSON.stringify(w));

    var hit = M.findBlend(L.blends, w);
    if (!hit) {
      console.warn('no grid point for these weights', w);
      out.textContent = '—';
      out.removeAttribute('data-mae-oos');
      note.textContent = 'no grid point for these weights';
      return;
    }
    out.setAttribute('data-mae-oos', String(hit.mae_out_of_sample));
    out.textContent = F.fmtF(hit.mae_out_of_sample);
    note.textContent = hit.label + ' · in-sample ' + F.fmtF(hit.mae_in_sample) +
      ' · OOS rank #' + hit.rank + ' of ' + L.blends.length;
  }

  /* ── chart ────────────────────────────────────────────────────────── */
  function enabledPairs() {
    var out = [];
    for (var i = 0; i < MODELS.length; i++) {
      for (var j = i + 1; j < MODELS.length; j++) {
        if (state.enabled.indexOf(MODELS[i]) !== -1 && state.enabled.indexOf(MODELS[j]) !== -1) {
          out.push([MODELS[i], MODELS[j]]);
        }
      }
    }
    return out;
  }

  function defaultPair(L) {
    /* The two lowest-OOS-MAE pure models that are currently enabled. */
    var pures = L.blends.filter(function (b) {
      return b.is_pure && passesFilter(b);
    }).slice().sort(function (a, b) { return a.mae_out_of_sample - b.mae_out_of_sample; });
    var names = pures.map(function (b) {
      for (var i = 0; i < MODELS.length; i++) {
        if ((Number(b.weights[MODELS[i]]) || 0) > 0.999) return MODELS[i];
      }
      return null;
    }).filter(Boolean);
    if (names.length >= 2) return [names[0], names[1]];
    return null;
  }

  function renderChartRegion() {
    var L = leadData(state.lead);
    var card = $('chart-card'), sel = $('chart-pair');
    var pairs = enabledPairs();
    if (pairs.length === 0) { card.classList.add('is-hidden'); return; }
    card.classList.remove('is-hidden');

    var cur = state.pair;
    var ok = cur && pairs.some(function (p) { return p[0] === cur[0] && p[1] === cur[1]; });
    if (!ok) { cur = defaultPair(L) || pairs[0]; state.pair = cur; }

    sel.textContent = '';
    pairs.forEach(function (p) {
      var o = document.createElement('option');
      o.value = p[0] + '|' + p[1];
      o.textContent = p[0] + ' vs ' + p[1];
      if (p[0] === cur[0] && p[1] === cur[1]) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = function () {
      state.pair = sel.value.split('|');
      window.BharChart.render({ wrapEl: $('chart-wrap'), captionEl: $('chart-caption'),
        blends: leadData(state.lead).blends, a: state.pair[0], b: state.pair[1] });
    };

    window.BharChart.render({ wrapEl: $('chart-wrap'), captionEl: $('chart-caption'),
      blends: L.blends, a: cur[0], b: cur[1] });
  }

  /* ── footer / honesty panel ───────────────────────────────────────── */
  function line(parent, nodes) {
    var p = document.createElement('p');
    p.className = 'honesty-line';
    nodes.forEach(function (n) { p.appendChild(typeof n === 'string' ? document.createTextNode(n) : n); });
    parent.appendChild(p);
    return p;
  }
  function strong(text) { var b = document.createElement('b'); b.textContent = text; return b; }
  function mono(text) { var s = document.createElement('span'); s.className = 'mono-value'; s.textContent = text; return s; }

  function renderFooter() {
    var meta = state.data.meta, L = leadData(state.lead);
    var v = L.winner.improvement_pct_vs_best_single;
    var st = improvementState(v);
    var bestName = L.best_single_model.model;

    var imp = $('improvement-line');
    imp.setAttribute('data-improvement', String(v));
    imp.setAttribute('data-improvement-state', st);
    /* Copy templates per the design target §3, names substituted from the data.
       The signed value is always printed with a real minus — never abs, never clamped. */
    if (st === 'positive') {
      imp.textContent = 'Winner (' + L.winner.label + ') beats the best single model (' +
        bestName + ') by ' + F.fmtSignedPct(v) + '.';
    } else if (st === 'tie') {
      imp.textContent = 'Best blend (' + L.winner.label + ') ties the best single model (' +
        bestName + '). No improvement — ' + F.fmtSignedPct(v) + '.';
    } else {
      imp.textContent = 'No blend beat the best single model. The best blend (' + L.winner.label +
        ') is ' + F.fmtSignedPct(v) + ' vs ' + bestName + ' — worse.';
    }

    var g = $('honesty-grid');
    g.textContent = '';
    var shown = document.querySelectorAll('[data-row="blend"]').length;
    line(g, ['Showing top ', strong(String(shown)), ' of ', strong(String(L.blends.length)),
      ' candidate blends (top non-pure blends, every pure model, plus the winner).']);
    line(g, ['Data source: ', mono(meta.source)]);

    if (meta.models_excluded && meta.models_excluded.length) {
      meta.models_excluded.forEach(function (x) {
        var dot = document.createElement('span'); dot.className = 'warn-dot';
        line(g, [dot, 'Excluded: ', strong(x.model), ' — coverage ',
          mono(F.fmtNum(x.coverage_pct, 1) + '%'), ' · ' + x.reason]);
      });
    } else {
      line(g, ['No models excluded (all met the 90% coverage floor).']);
    }

    line(g, ['Included: ', strong(meta.models_included.join(', '))]);
    line(g, ['Join at ' + state.lead + 'h: matched ',
      mono(F.fmtNum(L.join_diagnostics.matched_pct, 2) + '%'), ' · mean |offset| ',
      mono(F.fmtNum(L.join_diagnostics.mean_abs_offset_min, 2) + ' min')]);
    line(g, ['Samples: train ', mono(String(L.n_samples.train)), ' · test ',
      mono(String(L.n_samples.test))]);
    line(g, ['Split: ' + meta.split.method + ' — train ', mono(String(meta.split.train_days) + 'd'),
      ' / test ', mono(String(meta.split.test_days) + 'd')]);
    line(g, ['Window: ' + meta.window.start + ' → ' + meta.window.end +
      ' · runs ' + meta.init_runs.join(', ') + ' · ' + meta.units]);
    line(g, ['Best single model at ' + state.lead + 'h: ', strong(bestName), ' at ',
      mono(F.fmtF(L.best_single_model.mae_out_of_sample))]);
  }

  /* ── error path ───────────────────────────────────────────────────── */
  function renderEmptyState(detail) {
    var shell = $('shell');
    if (shell) shell.classList.add('is-hidden');
    var host = $('error-slot');
    host.textContent = '';
    var card = document.createElement('div');
    card.className = 'card empty-state';
    card.id = 'empty-state';
    var icon = document.createElement('div');
    icon.className = 'empty-icon';
    icon.textContent = '◍';
    var h = document.createElement('p');
    h.className = 'empty-title';
    h.textContent = 'No results file. Run the pipeline.';
    var b = document.createElement('p');
    b.className = 'empty-body';
    b.textContent = 'Run: uv run python -m backend.make_fixture';
    var d = document.createElement('p');
    d.className = 'empty-detail';
    d.textContent = detail;                 // the server's message, verbatim
    card.appendChild(icon); card.appendChild(h); card.appendChild(b); card.appendChild(d);
    host.appendChild(card);
  }

  /* ── Theme (R1) ───────────────────────────────────────────────────
     models.js MEMOIZES the model -> colour map, and this file bakes the
     resolved hex inline: stacked bar segments (renderLeaderboard),
     model dots (renderModelBar, renderSliders) and slider fills
     (renderSliders). chart.js does the same for the series, points, min
     marker and endpoint labels. Repainting the background is therefore not
     enough — without dropping the cache and re-rendering every panel that
     carries a colour, the page goes dark and every coloured mark stays on
     the light palette. This is an acceptance criterion, not polish.

     The five renders below are exactly the body of renderLead(), called
     directly rather than through it so that a theme toggle does NOT reset
     the presenter's slider position or chart pair back to the winner's
     defaults mid-demo. */
  if (window.BharTheme) {
    window.BharTheme.mount($('theme-toggle'));
    window.BharTheme.onChange(function () {
      M.resetColors();
      if (!state.data) return;          // empty state carries no coloured marks
      renderModelBar();
      renderLeaderboard();
      renderSliders();
      renderReadout();
      renderChartRegion();
      renderFooter();
    });
  }

  window.BharApp = { state: state, renormalize: M.renormalize };
})();
