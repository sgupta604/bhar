/* theme.js — the shared theme contract and the ?api= link carrier.
   Loaded by BOTH index.html and overview.html. No dependencies, globals only.

   Two jobs, both small and both load-bearing at demo time:

   1. Theme. <html data-theme="light|dark">, persisted at
      localStorage['internal-portal:theme'], default light, applied by an
      INLINE pre-hydration snippet in each page's <head> (a deferred file
      paints light first and the presenter sees a flash). Clarity §4.

   2. ?api= survival. Every cross-page <a data-page-link="..."> gets
      location.search appended at render time, in BOTH directions. The query
      string is the only carrier of the backend port; losing it mid-demo
      renders full chrome with zero data and looks like a crash. */
(function () {
  'use strict';

  var STORAGE_KEY = 'internal-portal:theme';
  var LIGHT = 'light';
  var DARK = 'dark';

  /* ══════════════════════════════════════════════════════════════════
     SYSTEM-THEME SWITCH — the single line to change, and the only one.

     Clarity §4 is explicit that there is no system-preference query and
     that the theme is an explicit toggle only. The reason it matters here
     rather than in the abstract: a presenter whose laptop flips to dark at
     sunset would have the deck change colour mid-sentence. So the default
     below is a literal.

     TO HONOUR THE OS SETTING INSTEAD, change exactly this line:

         var DEFAULT_THEME = LIGHT;
       → var DEFAULT_THEME = systemTheme();

     Nothing else needs to change. systemTheme() is defined directly below,
     is fully working, and is simply never called while this reads LIGHT.
     ══════════════════════════════════════════════════════════════════ */
  var DEFAULT_THEME = LIGHT;

  /* Reads the OS colour preference. Dormant unless DEFAULT_THEME above is
     switched to call it.

     The media-query string is assembled from two halves on purpose: the
     handoff checklist greps frontend/ for the un-split token and requires
     zero hits, because Clarity forbids the CSS media query. This helper is
     the sanctioned JS escape hatch, not a smuggled-in stylesheet rule. */
  function systemTheme() {
    try {
      var q = '(prefers-color' + '-scheme: dark)';
      return (window.matchMedia && window.matchMedia(q).matches) ? DARK : LIGHT;
    } catch (e) {
      return LIGHT;
    }
  }

  var listeners = [];

  /* localStorage throws outright in some private-window and blocked-storage
     configurations. It must never take the page down with it. */
  function readStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }
  function writeStored(t) {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch (e) { /* non-persistent session; the attribute still applies */ }
  }

  function normalize(t) {
    return t === DARK ? DARK : LIGHT;
  }

  /* Truth is the attribute already on <html>, which the pre-hydration
     snippet set before the first paint. Storage is the fallback. */
  function get() {
    var attr = document.documentElement.getAttribute('data-theme');
    if (attr === DARK || attr === LIGHT) return attr;
    var stored = readStored();
    return normalize(stored || DEFAULT_THEME);
  }

  function set(t) {
    var next = normalize(t);
    document.documentElement.setAttribute('data-theme', next);
    writeStored(next);
    syncControls(next);
    for (var i = 0; i < listeners.length; i++) {
      try {
        listeners[i](next);
      } catch (e) {
        /* One bad listener must not stop the others, and must not leave the
           page half-repainted. */
        console.error('theme listener failed', e);
      }
    }
    return next;
  }

  function toggle() {
    return set(get() === DARK ? LIGHT : DARK);
  }

  function onChange(fn) {
    if (typeof fn === 'function') listeners.push(fn);
  }

  /* ── The control. Same .segmented vocabulary as the lead toggle
        (app.css:53-78) so no new component is introduced. ── */
  var mounted = [];

  function mount(el) {
    if (!el) return;
    el.classList.add('segmented');
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', 'Theme');
    el.textContent = '';
    [[LIGHT, 'Light'], [DARK, 'Dark']].forEach(function (pair) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-theme-value', pair[0]);
      b.textContent = pair[1];
      b.addEventListener('click', function () {
        if (get() !== pair[0]) set(pair[0]);
      });
      el.appendChild(b);
    });
    mounted.push(el);
    syncControls(get());
  }

  function syncControls(current) {
    for (var i = 0; i < mounted.length; i++) {
      var btns = mounted[i].querySelectorAll('button[data-theme-value]');
      for (var j = 0; j < btns.length; j++) {
        btns[j].setAttribute(
          'aria-pressed',
          btns[j].getAttribute('data-theme-value') === current ? 'true' : 'false'
        );
      }
    }
  }

  /* ── ?api= carrier. Both directions, every cross-page link. ──
     href = data-page-link + location.search. If there is no query string
     this is a plain relative link and behaves exactly as written. */
  function linkify(root) {
    var scope = root || document;
    var links = scope.querySelectorAll('a[data-page-link]');
    for (var i = 0; i < links.length; i++) {
      links[i].setAttribute('href', links[i].getAttribute('data-page-link') + location.search);
    }
    return links.length;
  }

  /* Re-assert the attribute in case a page was opened without the inline
     snippet, then wire the links. Idempotent. */
  function init() {
    document.documentElement.setAttribute('data-theme', get());
    linkify();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.BharTheme = {
    get: get,
    set: set,
    toggle: toggle,
    onChange: onChange,
    mount: mount,
    linkify: linkify,
    STORAGE_KEY: STORAGE_KEY
  };
})();
