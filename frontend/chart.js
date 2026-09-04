/* chart.js — hand-drawn inline SVG. No chart library, no CDN, no imports.
   Every plotted y value is an exact lattice lookup out of the payload;
   nothing here interpolates or computes an error value.
   The SVG is built as markup and handed to innerHTML so the HTML parser
   applies the SVG namespace for us — that keeps every URL out of this file. */
(function () {
  'use strict';

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* The 11 slice points: x = weight of model A (0 -> 100%), the other two
     models pinned at 0. Each point is looked up, never derived. */
  function slicePoints(blends, a, b) {
    var M = window.BharModels, pts = [];
    for (var i = 0; i <= 10; i++) {
      var w = {};
      M.MODELS.forEach(function (m) { w[m] = 0; });
      w[a] = i / 10;
      w[b] = (10 - i) / 10;
      var hit = M.findBlend(blends, w);
      pts.push({ x: i * 10, blend: hit, y: hit ? hit.mae_out_of_sample : null });
    }
    return pts;
  }

  function render(o) {
    var pts = slicePoints(o.blends, o.a, o.b);
    var colors = window.BharModels.modelColors();
    var W = 660, H = 300, PL = 54, PR = 118, PT = 22, PB = 42;
    var iw = W - PL - PR, ih = H - PT - PB;
    var ok = pts.filter(function (p) { return p.y !== null; });
    if (!ok.length) {
      console.warn('no grid points for pair', o.a, o.b);
      o.wrapEl.textContent = 'no grid point for these weights';
      return;
    }
    var ys = ok.map(function (p) { return p.y; });
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    var pad = (hi - lo) * 0.15 || 1, y0 = lo - pad, y1 = hi + pad;
    var sx = function (x) { return (PL + (x / 100) * iw).toFixed(1); };
    var sy = function (y) { return (PT + ih - ((y - y0) / (y1 - y0)) * ih).toFixed(1); };

    var s = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' +
      esc('Out-of-sample MAE against ' + o.a + ' weight') + '">';

    for (var g = 0; g <= 4; g++) {                                   /* gridlines + y ticks */
      var yv = y0 + (y1 - y0) * (g / 4), yy = sy(yv);
      s += '<line class="gridline" x1="' + PL + '" x2="' + (PL + iw) + '" y1="' + yy + '" y2="' + yy + '"/>';
      s += '<text class="axis-label" x="' + (PL - 8) + '" y="' + (Number(yy) + 3.5) +
        '" text-anchor="end">' + yv.toFixed(1) + '</text>';
    }
    for (var k = 0; k <= 10; k += 2) {                               /* x ticks */
      s += '<text class="axis-label" x="' + sx(k * 10) + '" y="' + (PT + ih + 16) +
        '" text-anchor="middle">' + (k * 10) + '%</text>';
    }
    s += '<text class="axis-title" x="' + (PL + iw / 2) + '" y="' + (H - 8) +
      '" text-anchor="middle">' + esc(o.a + ' weight  (remainder to ' + o.b + ')') + '</text>';
    s += '<text class="axis-title" x="13" y="' + (PT + ih / 2) + '" text-anchor="middle" transform="rotate(-90 13 ' +
      (PT + ih / 2) + ')">Out-of-sample MAE (°F)</text>';

    s += '<g style="--series-color: ' + esc(colors[o.a]) + '">';
    s += '<path class="series-line" d="' +
      ok.map(function (p, i) { return (i ? 'L' : 'M') + sx(p.x) + ' ' + sy(p.y); }).join(' ') + '"/>';

    var minP = null;
    pts.forEach(function (p) { if (p.y !== null && (!minP || p.y < minP.y)) minP = p; });

    pts.forEach(function (p) {
      if (p.y === null) return;
      var end = (p.x === 0 || p.x === 100);
      var style = end ? ' style="--series-color: ' + esc(colors[p.x === 100 ? o.a : o.b]) + '"' : '';
      s += '<circle class="series-point' + (end ? ' is-endpoint' : '') + '" cx="' + sx(p.x) +
        '" cy="' + sy(p.y) + '" r="' + (end ? 5 : 3.5) + '"' + style + '><title>' +
        esc((p.blend ? p.blend.label : '') + ' — ' + p.y.toFixed(2) + '°F') + '</title></circle>';
    });
    if (minP) {
      s += '<circle class="series-min-marker" cx="' + sx(minP.x) + '" cy="' + sy(minP.y) + '" r="7"/>';
      s += '<text class="axis-label" x="' + sx(minP.x) + '" y="' + (Number(sy(minP.y)) - 15) +
        '" text-anchor="middle">min ' + minP.y.toFixed(2) + '°F</text>';
    }
    /* Endpoint labels, each in its own pure model's color. */
    [{ p: pts[0], m: o.b }, { p: pts[10], m: o.a }].forEach(function (e) {
      if (!e.p || e.p.y === null) return;
      s += '<text class="axis-label" x="' + (Number(sx(e.p.x)) + 8) + '" y="' +
        (Number(sy(e.p.y)) + 3.5) + '" text-anchor="start" style="fill: ' + esc(colors[e.m]) +
        '">' + esc('pure ' + e.m) + '</text>';
    });
    s += '</g></svg>';

    o.wrapEl.innerHTML = s;

    /* Mandatory caption — pair and held-out names substituted from the data. */
    var held = window.BharModels.MODELS.filter(function (m) { return m !== o.a && m !== o.b; });
    o.captionEl.textContent = o.a + ' vs ' + o.b + ' · ' + held.join(' and ') +
      ' held at 0. The leaderboard above searches the full 4-model weight space; ' +
      'this chart is a 2-model slice.';
  }

  window.BharChart = { render: render, slicePoints: slicePoints };
})();
