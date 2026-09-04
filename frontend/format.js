/* format.js — numeric formatting. No dependencies. Globals on window. */
(function () {
  'use strict';

  /* Degrees F, two decimals, at the display boundary. */
  function fmtF(x) {
    if (x === null || x === undefined || typeof x !== 'number' || !isFinite(x)) return '—';
    return x.toFixed(2) + '°F';
  }

  /* Signed percentage, always with an explicit sign, using a real minus U+2212.
   *
   * FORBIDDEN HERE: Math.abs() and any clamping of the value.
   * improvement_pct_vs_best_single is a signed result and must be reported with
   * its true sign — a negative blend result is a finding, not a rendering bug.
   * See SPEC §10 (integrity rules) and plan decision D4 (three signed states).
   * The sign is derived by inspecting the formatted string, never by abs().
   */
  function fmtSignedPct(x, digits) {
    if (x === null || x === undefined || typeof x !== 'number' || !isFinite(x)) return '—';
    var d = (digits === undefined) ? 2 : digits;
    var s = x.toFixed(d);
    if (s.charAt(0) === '-') {
      return '−' + s.slice(1) + '%';   // U+2212 MINUS SIGN, not an ASCII hyphen
    }
    return '+' + s + '%';
  }

  /* Plain number with fixed decimals, no unit. */
  function fmtNum(x, digits) {
    if (x === null || x === undefined || typeof x !== 'number' || !isFinite(x)) return '—';
    return x.toFixed(digits === undefined ? 2 : digits);
  }

  /* Weight as a whole percent, e.g. 0.7 -> "70%". */
  function fmtPct0(w) {
    return Math.round(w * 100) + '%';
  }

  window.BharFormat = {
    fmtF: fmtF,
    fmtSignedPct: fmtSignedPct,
    fmtNum: fmtNum,
    fmtPct0: fmtPct0
  };
})();
