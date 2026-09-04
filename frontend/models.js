/* models.js — canonical model order, colors, and the weight-vector algebra.
   No dependencies. Globals on window. */
(function () {
  'use strict';

  /* Canonical order. Every weight vector, bar segment and slider row is laid
     out in this order so the page is deterministic. */
  var MODELS = ['HRRR', 'GFS', 'NAM', 'NBM'];

  /* Colors are read back out of the CSS custom properties declared in
     tokens.css, so tokens.css stays the single source of truth for the
     model -> color map. Resolved lazily (fonts/CSS may not be applied yet
     at script-parse time under defer). */
  var _colors = null;
  function modelColors() {
    if (_colors) return _colors;
    var cs = getComputedStyle(document.documentElement);
    _colors = {};
    MODELS.forEach(function (m) {
      var v = cs.getPropertyValue('--model-' + m.toLowerCase()).trim();
      _colors[m] = v || 'var(--accent)';
    });
    return _colors;
  }

  /* The grid is a 0.1 lattice, so slider positions snap to 10 (percent units). */
  function snapTo10(v) {
    var n = Math.round(Number(v) / 10) * 10;
    if (!isFinite(n)) return 0;
    if (n < 0) return 0;
    if (n > 100) return 100;
    return n;
  }

  /* renormalize(weights, movedModel, value, enabledModels)
   *
   * Sets movedModel to `value` (a fraction 0..1) and distributes 1 - value
   * across the other ENABLED models in proportion to their current weights.
   * Rounds to the 0.1 lattice by LARGEST REMAINDER, working in integer tenths,
   * so the returned vector sums to exactly 1.0 (10 tenths) with no float drift
   * in the rounding step. Deterministic: remainder ties break by canonical
   * model order.
   *
   * Disabled models always come back as exactly 0.
   * Pass movedModel === null to just renormalize the enabled subset in place.
   */
  function renormalize(weights, movedModel, value, enabledModels) {
    var w = weights || {};
    var enabledSet = {};
    (enabledModels || MODELS).forEach(function (m) { enabledSet[m] = true; });
    var enabled = MODELS.filter(function (m) { return enabledSet[m]; });

    var out = {};
    MODELS.forEach(function (m) { out[m] = 0; });
    if (enabled.length === 0) return out;            // caller guards; degenerate

    var moved = (movedModel && enabledSet[movedModel]) ? movedModel : null;
    var movedTenths = 0;
    if (moved) {
      movedTenths = Math.round(Number(value) * 10);
      if (!isFinite(movedTenths) || movedTenths < 0) movedTenths = 0;
      if (movedTenths > 10) movedTenths = 10;
    }

    var others = enabled.filter(function (m) { return m !== moved; });
    if (others.length === 0) {
      out[moved || enabled[0]] = 1;                  // single enabled model owns everything
      return out;
    }
    if (!moved) movedTenths = 0;

    var remaining = 10 - movedTenths;
    var sum = others.reduce(function (a, m) { return a + (Number(w[m]) || 0); }, 0);
    var raw = others.map(function (m) {
      var p = sum > 0 ? (Number(w[m]) || 0) / sum : 1 / others.length;
      return remaining * p;
    });
    var floors = raw.map(function (x) { return Math.floor(x); });
    var used = floors.reduce(function (a, b) { return a + b; }, 0);
    var left = remaining - used;

    /* Largest remainder, ties broken by canonical model order. */
    var order = others.map(function (m, i) {
      return { i: i, rem: raw[i] - floors[i], canon: MODELS.indexOf(m) };
    }).sort(function (a, b) {
      if (b.rem !== a.rem) return b.rem - a.rem;
      return a.canon - b.canon;
    });
    for (var k = 0; k < left && order.length > 0; k++) {
      floors[order[k % order.length].i] += 1;
    }

    if (moved) out[moved] = movedTenths / 10;
    others.forEach(function (m, i) { out[m] = floors[i] / 10; });
    return out;
  }

  /* Integer-tenths sum check, used by the console self-test during build. */
  function sumsToOne(w) {
    var t = MODELS.reduce(function (a, m) { return a + Math.round((w[m] || 0) * 10); }, 0);
    return t === 10;
  }

  /* Exact lattice lookup — the only way an error value ever reaches the screen.
     Never interpolate, never compute. Returns null on a miss. */
  function findBlend(blends, weights) {
    for (var i = 0; i < blends.length; i++) {
      var bw = blends[i].weights;
      var ok = true;
      for (var j = 0; j < MODELS.length; j++) {
        var m = MODELS[j];
        var d = (Number(bw[m]) || 0) - (Number(weights[m]) || 0);
        if (d > 1e-9 || d < -1e-9) { ok = false; break; }
      }
      if (ok) return blends[i];
    }
    return null;
  }

  window.BharModels = {
    MODELS: MODELS,
    modelColors: modelColors,
    snapTo10: snapTo10,
    renormalize: renormalize,
    sumsToOne: sumsToOne,
    findBlend: findBlend
  };
})();
