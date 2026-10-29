/* Slate ambient light: ambient.js (SPEC 16). Optional layer, build step 4b.
   Three soft colored lights drift slowly behind the screen. On load, one bright light sweeps in,
   passes the clock, the weather and the tiles, then splits into the three drifting lights.
   Decorative only: it never carries information, and the UI accent stays Ice steel.
   Plain JS (ES2017, no modules). Movement uses the Web Animations API on transform and opacity,
   which the browser can run off the main thread. No filters, no blur, no per-frame JS.
   The app copy leaves out the prototype URL controls (palette, time, intensity, night, arrival, seek).

   Adapter contract for real lights (SPEC 16.8). No light bridge is built yet:
     window.ambient.currentColors()  -> { colors: ['#RRGGBB' x3, left to right], intensity: 0..1,
                                          palette: 'aurora', mode: 'drift', updated: ISO time }
     window event 'slate:ambient'     -> same object in event.detail, about once per second. */
(function () {
  'use strict';
  var TAU = Math.PI * 2;
  var CONFIG_URL = 'ambient.json';
  var LINEN = '#E6E1D7';

  var DEFAULTS = {
    enabled: true, palette: 'aurora', intensity: 0.8, speed: 1, mode: 'drift', arrival: true,
    night: { from: '00:00', to: '06:00', intensity: 0.35, speed: 0.5 }, lights: [],
    palettes: { aurora: { name: 'Aurora', colors: ['#19D3B5', '#9472FF', '#FF6F91'] } }
  };

  /* ---------- the three light sources (design px, 1920 x 1080) ----------
     The three lights ride one wide tilted loop, a third of a turn apart, so they never pile up into
     a muddy blob. Each also wanders on its own small loop with a different period (61 / 73 / 83 s
     against the 88 s ride), so the picture never visibly repeats. The loop keeps the bright cores in
     the open band under the clock and weather and behind the glass tiles, not behind small text. */
  var RIDE = { T: 72, cx: 920, cy: 600, rx: 900, ry: 280, rot: 7 * Math.PI / 180 };
  var SRC = [
    { T: 53, ph: 0,     glow: [1500, 860, -12], wob: function (u) { var a = TAU * u; return [90 * Math.sin(a), 65 * Math.sin(2 * a + 0.6)]; } },
    { T: 61, ph: 1 / 3, glow: [1340, 780, 16],  wob: function (u) { var a = TAU * u; return [80 * Math.sin(a + 2.0), 70 * Math.cos(a + 0.4)]; } },
    { T: 67, ph: 2 / 3, glow: [1420, 820, -4],  wob: function (u) { var a = TAU * u; return [95 * Math.cos(a + 1.1), 58 * Math.sin(2 * a + 2.2)]; } }
  ];
  var ride = function (i, u) {
    var f = TAU * (u + SRC[i].ph), c = Math.cos(RIDE.rot), s = Math.sin(RIDE.rot);
    var ex = RIDE.rx * Math.cos(f), ey = RIDE.ry * Math.sin(f);
    return [RIDE.cx + ex * c - ey * s, RIDE.cy + ex * s + ey * c];
  };
  var frac = function (t, T) { return ((t / T) % 1 + 1) % 1; };
  var level = function (i, u) { return 0.86 + 0.14 * Math.sin(TAU * u + i * 2.1); };    // slow breathing, on the wander loop
  var STATIC_T = 30;                                                     // where the lights sit when nothing moves (drift seconds)
  var driftAt = function (i, t) { var r = ride(i, frac(t, RIDE.T)), w = SRC[i].wob(frac(t, SRC[i].T)); return [r[0] + w[0], r[1] + w[1]]; };

  /* ---------- arrival: one curved sweep, time in seconds ----------
     clock (top left) -> weather (top right) -> tiles (bottom, right to left) -> split point. */
  var ARR_KEYS = [[-0.35, -820, 860], [0, -300, 660], [0.55, 430, 500], [1.2, 1460, 630], [1.7, 1640, 800],
                  [2.2, 940, 840], [2.5, 760, 650], [2.85, 690, 560]];
  var ARR_END = 2.5, SPLIT_FROM = 2.15, SPLIT_TO = 3.8, LAG = [0, 0.09, 0.18], ARR_TOTAL = SPLIT_TO;
  function comet(t) {
    t = Math.max(0, Math.min(ARR_END, t));
    var k = 1; while (k < ARR_KEYS.length - 2 && ARR_KEYS[k + 1][0] < t) k++;
    var p0 = ARR_KEYS[k - 1], p1 = ARR_KEYS[k], p2 = ARR_KEYS[k + 1], p3 = ARR_KEYS[k + 2];
    var s = (t - p1[0]) / (p2[0] - p1[0]);
    // ease the time inside each segment a little so the light carries momentum through each stop
    var cr = function (a, b, c, d) { return 0.5 * ((2 * b) + (-a + c) * s + (2 * a - 5 * b + 4 * c - d) * s * s + (-a + 3 * b - 3 * c + d) * s * s * s); };
    return [cr(p0[1], p1[1], p2[1], p3[1]), cr(p0[2], p1[2], p2[2], p3[2])];
  }
  var ease = function (x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };
  // where source i is during the arrival (ta = arrival seconds, td = its drift time), as an offset from
  // its drift position, plus scale and opacity
  function arrival(i, ta, td) {
    var d = driftAt(i, td), c = comet(ta - LAG[i]), m = ease((ta - SPLIT_FROM) / (SPLIT_TO - SPLIT_FROM));
    return { dx: c[0] + (d[0] - c[0]) * m - d[0], dy: c[1] + (d[1] - c[1]) * m - d[1], s: 0.7 + 0.3 * m, o: ease((ta - LAG[i]) / 0.35) };
  }
  function spark(t) {                                                    // the bright leading light
    var p = comet(t), q = comet(t + 0.05), ang = Math.atan2(q[1] - p[1], q[0] - p[0]) * 180 / Math.PI;
    var o = ease(t / 0.25) * (1 - ease((t - 2.05) / 0.6));
    return { x: p[0], y: p[1], a: ang, o: o };
  }

  /* ---------- color helpers ---------- */
  var rgb = function (h) { h = h.replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; };
  var rgba = function (h, a) { var c = rgb(h); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a.toFixed(3) + ')'; };
  var mix = function (h1, h2, m) { var a = rgb(h1), b = rgb(h2); return '#' + a.map(function (v, i) { return Math.round(v + (b[i] - v) * m).toString(16).padStart(2, '0'); }).join('').toUpperCase(); };
  // a light: bright core, quick falloff, long faint tail. Alpha stops tuned on the ink base.
  function glowCss(hex, peak) {
    var stops = [];
    for (var j = 0; j <= 12; j++) {
      var r = j / 12;
      var a = peak * (0.3 * Math.exp(-Math.pow(r / 0.16, 2)) + 0.7 * Math.exp(-Math.pow(r / 0.55, 2))) * (1 - r * r);
      stops.push(rgba(hex, a) + ' ' + (r * 100).toFixed(1) + '%');
    }
    return 'radial-gradient(closest-side, ' + stops.join(', ') + ')';
  }

  /* ---------- state ---------- */
  var cfg, colors, mode, layer, frame, srcEls = [], wobEls = [], arrEls = [], wanders = [], sparkEl, anims = [], arrAnims = [];
  var arrivalOn = false, nightOn = false, lastPublished = '';
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function hourNow() {
    // Same New York window as the midnight-to-6 screen dim.
    try {
      var tz = (typeof window.slateTimezone === 'string' && window.slateTimezone) ? window.slateTimezone : 'America/New_York';
      var parts = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, hourCycle: 'h23', hour: '2-digit', minute: '2-digit'
      }).formatToParts(new Date());
      var hour = 0, minute = 0, i;
      for (i = 0; i < parts.length; i += 1) {
        if (parts[i].type === 'hour') hour = Number(parts[i].value);
        if (parts[i].type === 'minute') minute = Number(parts[i].value);
      }
      if (hour === 24) hour = 0;
      return hour + minute / 60;
    } catch (err) {
      var d = new Date();
      return d.getHours() + d.getMinutes() / 60;
    }
  }
  function isNight() {
    var n = cfg.night; if (!n) return false;
    var f = n.from.split(':'), to = n.to.split(':'), h = hourNow();
    var a = Number(f[0]) + Number(f[1]) / 60, b = Number(to[0]) + Number(to[1]) / 60;
    return a <= b ? (h >= a && h < b) : (h >= a || h < b);
  }
  var clamp01 = function (v) { return Math.max(0, Math.min(1, Number(v))); };
  function intensity() { if (mode === 'off') return 0; return clamp01(nightOn ? cfg.night.intensity : cfg.intensity); }
  function speed() { return Math.max(0.1, Number(cfg.speed) || 1) * (nightOn ? (Number(cfg.night.speed) || 1) : 1); }

  /* ---------- build ---------- */
  function scale() { var k = Math.min(innerWidth / 1920, innerHeight / 1080); document.documentElement.style.setProperty('--amb-k', k); return k; }
  function build() {
    layer = document.createElement('div'); layer.className = 'amb'; layer.setAttribute('aria-hidden', 'true');
    frame = document.createElement('div'); frame.className = 'amb-frame'; layer.append(frame);
    SRC.forEach(function (s, i) {
      var src = document.createElement('div'); src.className = 'amb-src';
      var wob = document.createElement('div'); wob.className = 'amb-src';
      var arr = document.createElement('div'); arr.className = 'amb-arr';
      var g = document.createElement('div'); g.className = 'amb-glow';
      g.style.width = s.glow[0] + 'px'; g.style.height = s.glow[1] + 'px';
      g.style.margin = (-s.glow[1] / 2) + 'px 0 0 ' + (-s.glow[0] / 2) + 'px';
      g.style.transform = 'rotate(' + s.glow[2] + 'deg)';
      g.style.background = glowCss(colors[i], 1);
      arr.append(g); wob.append(arr); src.append(wob); frame.append(src); srcEls.push(src); wobEls.push(wob); arrEls.push(arr);
    });
    sparkEl = document.createElement('div'); sparkEl.className = 'amb-arr';
    var sg = document.createElement('div'); sg.className = 'amb-glow';
    sg.style.width = '1300px'; sg.style.height = '520px'; sg.style.margin = '-260px 0 0 -650px';
    sg.style.background = glowCss(mix(colors[0], LINEN, 0.3), 1);
    sparkEl.append(sg); sparkEl.style.opacity = 0; frame.append(sparkEl);
    document.body.prepend(layer);
    document.body.classList.add('amb-on');
    scale(); addEventListener('resize', scale);
  }
  var tr = function (x, y, extra) { return 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)' + (extra || ''); };

  function startDrift() {
    SRC.forEach(function (s, i) {
      if (mode === 'static' || reduced || !srcEls[i].animate) {
        var r = ride(i, frac(STATIC_T, RIDE.T)), w = s.wob(frac(STATIC_T, s.T));
        srcEls[i].style.transform = tr(r[0], r[1]); wobEls[i].style.transform = tr(w[0], w[1]); wobEls[i].style.opacity = level(i, frac(STATIC_T, s.T)); return;
      }
      var kr = [], kw = [], j, u, p;
      for (j = 0; j <= 120; j++) { u = j / 120; p = ride(i, u); kr.push({ transform: tr(p[0], p[1]) }); }
      for (j = 0; j <= 90; j++) { u = j / 90; p = s.wob(u); kw.push({ transform: tr(p[0], p[1]), opacity: level(i, u) }); }
      anims[i] = srcEls[i].animate(kr, { duration: RIDE.T * 1000, iterations: Infinity, easing: 'linear' });
      wanders[i] = wobEls[i].animate(kw, { duration: s.T * 1000, iterations: Infinity, easing: 'linear' });
      anims[i].playbackRate = wanders[i].playbackRate = speed();
    });
  }
  function playArrival() {
    if (mode !== 'drift' || reduced || !cfg.arrival || !sparkEl.animate) return;
    arrAnims.forEach(function (a) { a.cancel(); }); arrAnims = [];
    var rate = speed();
    SRC.forEach(function (s, i) {
      var t0 = anims[i] ? anims[i].currentTime / 1000 : 0, kf = [];       // drift keeps moving underneath
      for (var j = 0; j <= 114; j++) {
        var t = ARR_TOTAL * j / 114, v = arrival(i, t, t0 + t * rate);
        kf.push({ transform: tr(v.dx, v.dy, ' scale(' + v.s.toFixed(3) + ')'), opacity: v.o });
      }
      arrAnims.push(arrEls[i].animate(kf, { duration: ARR_TOTAL * 1000, easing: 'linear' }));
    });
    var skf = [];
    for (var j = 0; j <= 90; j++) { var t = 2.7 * j / 90, sp = spark(t); skf.push({ transform: tr(sp.x, sp.y, ' rotate(' + sp.a.toFixed(1) + 'deg)'), opacity: sp.o }); }
    arrAnims.push(sparkEl.animate(skf, { duration: 2700, easing: 'linear' }));
    arrivalOn = true; arrAnims[0].onfinish = function () { arrivalOn = false; };
  }

  /* ---------- text shields: soft ink pools under text blocks, so a light never sits behind text at
     full strength. Static (painted once, re-measured on resize); the lights move underneath. ---------- */
  var SHIELD = ['.clock', '.date', '.wx-place', '.wx-now', '.wx-cond', '.wx-hours', '.wx-stale', '.dash-header', '.dash-date', '.dash-clock', '.data-stale'];
  var BAND = '.foot';   // the footer gets a soft full-width floor instead of small pools, which would read as dark pills
  var shieldWrap = null;
  function shields() {
    if (!layer) return;
    if (!shieldWrap) { shieldWrap = document.createElement('div'); shieldWrap.className = 'amb-shields'; frame.append(shieldWrap); }
    var k = Math.min(innerWidth / 1920, innerHeight / 1080), fx = (innerWidth - 1920 * k) / 2, fy = (innerHeight - 1080 * k) / 2;
    var out = [];
    SHIELD.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        var r = el.getBoundingClientRect(); if (!r.width) return;
        var d = document.createElement('div'); d.className = 'amb-shield';
        d.style.left = ((r.left - fx) / k - 12).toFixed(0) + 'px'; d.style.top = ((r.top - fy) / k - 12).toFixed(0) + 'px';
        d.style.width = (r.width / k + 24).toFixed(0) + 'px'; d.style.height = (r.height / k + 24).toFixed(0) + 'px';
        out.push(d);
      });
    });
    var f = document.querySelector(BAND);
    if (f) {
      var fr = f.getBoundingClientRect(), b = document.createElement('div'); b.className = 'amb-band';
      b.style.top = ((fr.top - fy) / k - 150).toFixed(0) + 'px'; out.push(b);
    }
    shieldWrap.replaceChildren.apply(shieldWrap, out);
  }

  /* ---------- glass rims: about 5 updates a second, only custom properties ---------- */
  function lightsNow() {
    var out = [];
    SRC.forEach(function (s, i) {
      var t = anims[i] ? anims[i].currentTime / 1000 : STATIC_T, p = driftAt(i, t), lv = level(i, frac(t, s.T)), sc = 1;
      var aa = arrAnims[i];
      if (aa && aa.playState !== 'finished' && aa.currentTime != null) {
        var v = arrival(i, aa.currentTime / 1000, t);
        p = [p[0] + v.dx, p[1] + v.dy]; lv *= v.o; sc = v.s;
      }
      out.push({ x: p[0], y: p[1], lv: lv * sc, hex: colors[i] });
    });
    var sa = arrAnims[3];
    if (sa && sa.playState !== 'finished' && sa.currentTime != null) { var sp = spark(sa.currentTime / 1000); out.push({ x: sp.x, y: sp.y, lv: sp.o * 1.4, hex: mix(colors[0], LINEN, 0.35) }); }
    return out;
  }
  function updateGlass() {
    if (mode === 'off') return;
    var k = Math.min(innerWidth / 1920, innerHeight / 1080), fx = (innerWidth - 1920 * k) / 2, fy = (innerHeight - 1080 * k) / 2;
    var L = lightsNow(), I = intensity();
    document.querySelectorAll('.tile, .box').forEach(function (el) {
      if (el.hidden) return;
      var r = el.getBoundingClientRect();
      var x0 = (r.left - fx) / k, y0 = (r.top - fy) / k, x1 = (r.right - fx) / k, y1 = (r.bottom - fy) / k;
      var best = null, sum = 0;
      L.forEach(function (l) {
        var dx = Math.max(x0 - l.x, 0, l.x - x1), dy = Math.max(y0 - l.y, 0, l.y - y1);
        var g = l.lv * Math.exp(-(dx * dx + dy * dy) / (380 * 380)); sum += g;
        if (!best || g > best.g) best = { g: g, l: l };
      });
      if (!best) return;
      var lit = Math.min(1, sum) * I;
      // Tile and box coordinates are design px. The stage scales them. Do not multiply by k.
      var lx = (best.l.x - x0).toFixed(0) + 'px', ly = (best.l.y - y0).toFixed(0) + 'px';
      var key = lit.toFixed(2) + lx + ly + best.l.hex;
      if (el._amb === key) return; el._amb = key;
      el.style.setProperty('--amb-lit', lit.toFixed(2));
      el.style.setProperty('--amb-lx', lx); el.style.setProperty('--amb-ly', ly);
      el.style.setProperty('--amb-lc', rgba(mix(best.l.hex, LINEN, 0.4), 1));
      el.style.setProperty('--amb-lf', rgba(best.l.hex, 0.10));
    });
  }

  /* ---------- adapter contract (SPEC 16.8) ---------- */
  var current = null;
  function currentColors() {
    var L = lightsNow().slice(0, 3).sort(function (a, b) { return a.x - b.x; });
    return { colors: L.map(function (l) { return l.hex; }), intensity: Number(intensity().toFixed(2)),
             palette: cfg.palette, mode: mode, updated: new Date().toISOString() };
  }
  function publish() {
    current = currentColors();
    var key = current.colors.join() + current.intensity + current.mode;
    if (key === lastPublished) return; lastPublished = key;
    try { window.dispatchEvent(new CustomEvent('slate:ambient', { detail: current })); } catch (e) { /* old browser */ }
  }

  /* ---------- night: dimmer and slower, checked once a minute ---------- */
  function applyNight(first) {
    var n = isNight(); if (!first && n === nightOn) return;
    var wasNight = nightOn; nightOn = n;
    layer.style.setProperty('--amb-fade', first ? '0ms' : '4000ms');
    layer.style.opacity = intensity();
    anims.concat(wanders).forEach(function (a) { if (a) a.playbackRate = speed(); });
    if (!first && wasNight && !n) playArrival();                          // morning: play the arrival once
  }

  /* ---------- start ---------- */
  function start(c) {
    cfg = Object.assign({}, DEFAULTS, c || {});
    cfg.night = Object.assign({}, DEFAULTS.night, cfg.night || {});
    var pals = Object.assign({}, DEFAULTS.palettes, cfg.palettes || {});
    var pr = cfg.presets && cfg.presets[cfg.preset];                     // a preset overrides palette / mode / enabled / intensity / speed
    if (pr) Object.keys(pr).forEach(function (k) { if (k !== 'name') cfg[k] = pr[k]; });
    mode = cfg.enabled === false ? 'off' : (cfg.mode || 'drift');
    var pal = pals[cfg.palette] || pals.aurora; colors = pal.colors.slice(0, 3);
    window.ambient = { currentColors: function () { return current || currentColors(); }, arrive: playArrival };
    if (mode === 'off') { window.ambient.currentColors = function () { return { colors: [], intensity: 0, palette: cfg.palette, mode: 'off', updated: new Date().toISOString() }; }; return; }
    build(); startDrift(); applyNight(true); playArrival();
    shields(); setTimeout(shields, 1500); addEventListener('resize', shields);   // re-measure once weather has filled in
    setInterval(function () { if (!document.hidden) updateGlass(); }, window.SlateTV ? 1000 : 200);
    setInterval(publish, 1000);
    setInterval(function () { applyNight(false); }, 60 * 1000);
    addEventListener('slate:timezone', function () { applyNight(false); });
    updateGlass(); publish();
  }
  var onHome = document.body.classList.contains('page-home');
  Promise.all([
    fetch(CONFIG_URL, { cache: 'no-store' }).then(function (r) { return r.json(); }),
    onHome ? (window.slateSettingsPromise || fetch('settings.json', { cache: 'no-store' }).then(function (r) { return r.json(); })) : Promise.resolve(null)
  ]).then(function (data) {
    var c = data[0], look = data[1];
    if (onHome && look && (look.tvAppearance === 'sculptural' || look.tvAppearance === 'flurry' || look.tvAppearance === 'aqua')) return;
    if (look && look.tvBackdrop && look.tvBackdrop !== 'ambient') return;
    if (look && (look.tvMotion === 'still' || matchMedia('(prefers-reduced-motion: reduce)').matches)) {
      var pr = c.presets && c.presets[c.preset];
      if (pr) { pr.mode = 'static'; pr.arrival = false; }
      c.mode = 'static'; c.arrival = false;
    }
    if (look && look.tvIntensity === 'soft') c.intensity = .4;
    if (look && look.tvIntensity === 'vivid') c.intensity = 1;
    start(c);
  }, function () { if (!onHome) start(null); });
})();
