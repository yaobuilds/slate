/* Home presentation. Local artwork and decorative motion only. */
(() => {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const stops = ['#72c9d0', '#837ee0', '#db9cae', '#b7d2e4'];
  /* Persisted as tvAquaPalette and tvFlurryPalette.
     The first entry in each set is its fallback: Tide or Spectrum. */
  const LOOK_PALETTES = {
    aqua: {
      tide:    { name: 'Tide',    base: '#0E2338', colors: ['#2F78B0', '#7CC4D6', '#6A57A0'] },
      glacier: { name: 'Glacier', base: '#121C28', colors: ['#5E86AD', '#C9DCEA', '#A9C2DA'] },
      lagoon:  { name: 'Lagoon',  base: '#0A2228', colors: ['#147C8C', '#4FD1C5', '#2C6DB5'] },
      dusk:    { name: 'Dusk',    base: '#1B1428', colors: ['#7A52B8', '#E58FB2', '#F2B57E'] },
      moss:    { name: 'Moss',    base: '#0E1D18', colors: ['#2F7D62', '#9CCB8B', '#D9C27A'] },
      ember:   { name: 'Ember',   base: '#21120F', colors: ['#A8402C', '#F08A4B', '#F3C46B'] },
    },
    flurry: {
      spectrum: { name: 'Spectrum', core: '#C9DCEA', colors: ['#E85BC8', '#8C63F0', '#4C7BEA', '#4CD3E8', '#E8CF5A', '#55D98A'] },
      ice:      { name: 'Ice',      core: '#C9DCEA', colors: ['#A9C2DA', '#6F98C2', '#D3E0EC', '#5A7FA6', '#8FB0CF'] },
      aurora:   { name: 'Aurora',   core: '#BFEFE6', colors: ['#19D3B5', '#9472FF', '#FF6F91', '#3FB8E0'] },
      ember:    { name: 'Ember',    core: '#F6D9B0', colors: ['#FFA51F', '#F0453A', '#D8337A', '#FFC93C'] },
      lagoon:   { name: 'Lagoon',   core: '#BFE9F5', colors: ['#1FC8F0', '#3A6BFF', '#2ED585', '#7BDFF2'] },
      bloom:    { name: 'Bloom',    core: '#F8D7E6', colors: ['#D946EF', '#FF7A30', '#FFC93C', '#F06AA8'] },
    },
  };
  const paletteFor = (look, key) => {
    const set = LOOK_PALETTES[look];
    if (!set) return null;
    return set[key] || set[Object.keys(set)[0]];
  };
  const rgba = (hex, a) => {
    const n = parseInt(String(hex).replace('#', ''), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const GRAIN = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .9 0 0 0 0 .88 0 0 0 0 .84 0 0 0 .55 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")";
  let ambientConfig = null;
  let ambientLoad = null;
  function loadAmbient() {
    if (!ambientLoad) {
      ambientLoad = fetch('ambient.json', { cache: 'no-store' })
        .then(r => (r.ok ? r.json() : {}))
        .catch(() => ({}))
        .then(cfg => { ambientConfig = cfg || {}; return ambientConfig; });
    }
    return ambientLoad;
  }
  /* Resolve Sculptural colors from the ambient preset; Off uses the fallback colors. */
  function ambientColorsFor(presetKey) {
    const cfg = ambientConfig || {};
    const preset = (cfg.presets || {})[presetKey] || {};
    if (preset.enabled === false) return stops;
    const pal = (cfg.palettes || {})[preset.palette || cfg.palette];
    return pal && Array.isArray(pal.colors) && pal.colors.length ? pal.colors : stops;
  }
  const flurryState = { hues: LOOK_PALETTES.flurry.spectrum.colors, core: LOOK_PALETTES.flurry.spectrum.core, still: false };
  const field = { nx: 0.68, ny: 0.42 };
  let stopBackdrop = () => {};
  let config = {};
  let page = 0;
  let lastFocus = null;
  let lastPointer = 0;
  const PAGE_SIZE = 6;
  const isHome = () => document.body.classList.contains('page-home');
  const androidTv = () => typeof onAndroidTv === 'function' && onAndroidTv();
  const tvFrame = () => typeof TV_LAYOUT !== 'undefined' && TV_LAYOUT.matches;
  const dockProfile = () => {
    const look = document.body.dataset.tvAppearance;
    return look === 'flurry' || look === 'aqua';
  };
  const profileDock = () => isHome() && androidTv() && tvFrame() && dockProfile();
  const motionLive = () => !reducedMotion.matches && config.tvMotion !== 'still';
  const THEME_COLOR = '#10141A';

  function normalizeAppearance(raw = {}) {
    let tvAppearance = raw.tvAppearance;
    if (tvAppearance === 'classic') tvAppearance = 'sculptural';
    else if (tvAppearance === 'scenic') tvAppearance = 'aqua';
    else if (tvAppearance !== 'sculptural' && tvAppearance !== 'aqua' && tvAppearance !== 'flurry') tvAppearance = 'sculptural';
    const tvMotion = ['still', 'drift', 'reactive'].includes(raw.tvMotion) ? raw.tvMotion : 'drift';
    const tvIntensity = ['soft', 'balanced', 'vivid'].includes(raw.tvIntensity) ? raw.tvIntensity : 'balanced';
    const aquaKeys = Object.keys(LOOK_PALETTES.aqua);
    const flurryKeys = Object.keys(LOOK_PALETTES.flurry);
    const tvAquaPalette = aquaKeys.includes(raw.tvAquaPalette) ? raw.tvAquaPalette : 'tide';
    const tvFlurryPalette = flurryKeys.includes(raw.tvFlurryPalette) ? raw.tvFlurryPalette : 'spectrum';
    return {
      tvAppearance,
      tvMotion,
      tvIntensity,
      tvAquaPalette,
      tvFlurryPalette,
      ambientPreset: raw.ambientPreset,
    };
  }

  function applyTheme(settings) {
    const norm = normalizeAppearance(settings || {});
    let motion = norm.tvMotion;
    if (reducedMotion.matches) motion = 'still';
    for (const el of [document.documentElement, document.body]) {
      el.dataset.tvAppearance = norm.tvAppearance;
      el.dataset.tvMotion = motion;
      el.dataset.tvIntensity = norm.tvIntensity;
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', THEME_COLOR);
  }

  function drawFlurry(ctx, tick) {
    /* During live motion, move the core along a small loop to spread its light. */
    const coreX = 960 * (field.nx + Math.sin(tick * 0.045) * 0.035);
    const coreY = 540 * (field.ny + Math.cos(tick * 0.037) * 0.04);
    ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(11,14,19,0.2)';
    ctx.fillRect(0, 0, 960, 540);
    ctx.lineCap = 'round';
    const hues = flurryState.hues;
    for (let i = 0; i < 16; i += 1) {
      const angle = tick * 0.12 + i * 0.42;
      const sx = 480 + Math.cos(angle) * 560;
      const sy = 270 + Math.sin(angle * 1.25) * 360;
      const hue = hues[i % hues.length];
      const grad = ctx.createLinearGradient(sx, sy, coreX, coreY);
      grad.addColorStop(0, rgba(hue, 0));
      grad.addColorStop(0.55, rgba(hue, 0.5));
      grad.addColorStop(1, rgba(hue, 0.9));
      ctx.strokeStyle = grad;
      ctx.globalAlpha = 0.2;
      ctx.lineWidth = 20 - (i % 5) * 3;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.quadraticCurveTo((sx + coreX) / 2, (sy + coreY) / 2 + Math.sin(angle) * 50, coreX, coreY);
      ctx.stroke();
    }
    const radius = 72 * (0.92 + Math.sin(tick * 0.4) * 0.08);
    const glow = ctx.createRadialGradient(coreX, coreY, 0, coreX, coreY, radius);
    /* The trail fade (0.2 per frame) stacks this glow about 5x, so the
       stops are low and taper slowly; higher values settle into a hard disc. */
    const peak = flurryState.still ? 0.1 : 0.16;
    glow.addColorStop(0, `rgba(230,225,215,${peak})`);
    glow.addColorStop(0.2, rgba(flurryState.core, peak * 0.6));
    glow.addColorStop(0.5, rgba(flurryState.core, peak * 0.22));
    glow.addColorStop(0.8, rgba(flurryState.core, peak * 0.05));
    glow.addColorStop(1, rgba(flurryState.core, 0));
    ctx.globalAlpha = 1;
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(coreX, coreY, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  function decorate(el, backdrop, motion, intensity, ambientColors = stops, paletteKey = '') {
    if (!el) return () => {};
    el.replaceChildren();
    el.dataset.backdrop = backdrop;
    el.dataset.motion = reducedMotion.matches ? 'still' : motion;
    el.dataset.intensity = intensity;
    el.style.setProperty('--look-x', '0px');
    el.style.setProperty('--look-y', '0px');
    let timer;
    if (backdrop === 'ambient') {
      const glow = document.createElement('div');
      glow.className = 'ambient-preview';
      glow.style.background = ambientColors.length
        ? `radial-gradient(ellipse at 20% 65%, ${ambientColors[0]}66, transparent 65%), radial-gradient(ellipse at 80% 70%, ${ambientColors[1] || ambientColors[0]}66, transparent 65%), #10141a`
        : '#10141a';
      el.append(glow);
    } else if (backdrop === 'sculptural') {
      const palette = ambientColors && ambientColors.length ? ambientColors : stops;
      for (let i = 0; i < 5; i += 1) {
        const form = document.createElement('i');
        const color = palette[i % palette.length];
        form.className = 'sculpt-form';
        form.style.setProperty('--form-i', i);
        form.style.setProperty('--form-color', color);
        form.style.setProperty('--form-core', rgba(color, 0.62));
        form.style.setProperty('--form-mid', rgba(color, 0.22));
        el.append(form);
      }
    } else if (backdrop === 'landscape') {
      const image = document.createElement('img');
      image.src = 'assets/wallpapers/alpine.jpg';
      image.alt = '';
      image.addEventListener('error', () => { el.dataset.backdrop = 'unavailable'; });
      el.append(image);
    } else if (backdrop === 'aqua') {
      const pal = paletteFor('aqua', paletteKey);
      const [a, b, c] = pal.colors;
      el.dataset.palette = Object.keys(LOOK_PALETTES.aqua).find(k => LOOK_PALETTES.aqua[k] === pal) || 'tide';
      el.style.setProperty('--aqua-base', pal.base);
      el.innerHTML = `<svg class="aqua-ribbons" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice"><defs>`
        + `<linearGradient id="ribbon-a" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${a}"/><stop offset=".48" stop-color="${b}"/><stop offset="1" stop-color="${c}"/></linearGradient>`
        + `<linearGradient id="ribbon-b" x1="0" y1="1" x2="1" y2="0"><stop stop-color="${c}"/><stop offset=".55" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient>`
        + `<linearGradient id="ribbon-sheen" x1="0" y1="0" x2="1" y2="0"><stop stop-color="${b}" stop-opacity="0"/><stop offset=".5" stop-color="#E6E1D7" stop-opacity=".9"/><stop offset="1" stop-color="${b}" stop-opacity="0"/></linearGradient>`
        + `</defs><g fill="none" stroke-linecap="round">`
        + `<path class="aqua-band aqua-glow" stroke="url(#ribbon-a)" stroke-width="460" opacity=".09" d="M-400 1120C300-200 660 1380 1210 670S1860 200 2300 20"/>`
        + `<path class="aqua-band" stroke="url(#ribbon-b)" stroke-width="120" opacity=".1" d="M560 -120C980 260 1460 40 2200 300"/>`
        + `<path class="aqua-band" stroke="url(#ribbon-a)" stroke-width="190" opacity=".3" d="M-400 1100C300-240 660 1360 1210 650S1860 180 2300 0"/>`
        + `<path class="aqua-band" stroke="url(#ribbon-b)" stroke-width="88" opacity=".5" d="M-300 1060C390 20 630 1270 1180 660S1850 320 2300 90"/>`
        + `<path class="aqua-band" stroke="url(#ribbon-sheen)" stroke-width="3" opacity=".7" d="M-300 1000C390 20 620 1190 1160 620S1850 320 2300 90"/>`
        + `<path class="aqua-band" stroke="url(#ribbon-a)" stroke-width="40" opacity=".32" d="M-300 1180C300 90 800 1400 1340 700S2000 180 2300 200"/>`
        + `</g></svg>`;
    } else if (backdrop === 'flurry') {
      const canvas = document.createElement('canvas');
      canvas.className = 'flurry-field';
      el.append(canvas);
      canvas.width = 960;
      canvas.height = 540;
      const ctx = canvas.getContext('2d');
      const pal = paletteFor('flurry', paletteKey);
      el.dataset.palette = Object.keys(LOOK_PALETTES.flurry).find(k => LOOK_PALETTES.flurry[k] === pal) || 'spectrum';
      flurryState.hues = pal.colors;
      flurryState.core = pal.core;
      flurryState.still = motion === 'still' || reducedMotion.matches;
      if (ctx) {
        let tick = 0;
        ctx.fillStyle = '#0B0E13';
        ctx.fillRect(0, 0, 960, 540);
        for (let n = 0; n < 40; n += 1) {
          tick += 0.08;
          drawFlurry(ctx, tick);
        }
        if (motion !== 'still' && !reducedMotion.matches) {
          timer = setInterval(() => {
            if (document.hidden || document.body.classList.contains('tv-motion-paused')) return;
            tick += 0.08;
            drawFlurry(ctx, tick);
          }, 50);
        }
      }
    } else if (backdrop === 'orbit') {
      for (let i = 0; i < 9; i += 1) {
        const ring = document.createElement('i');
        ring.className = 'orbit-ring';
        ring.style.setProperty('--ring-i', i);
        ring.style.setProperty('--ring-color', stops[i % stops.length]);
        el.append(ring);
      }
    }
    if (['sculptural', 'aqua', 'flurry'].includes(backdrop)) {
      const grain = document.createElement('i');
      grain.className = 'look-grain';
      grain.style.backgroundImage = GRAIN;
      el.append(grain);
    }
    return () => { if (timer) clearInterval(timer); el.replaceChildren(); };
  }
  window.SlateLooks = {
    decorate,
    palettes: LOOK_PALETTES,
    loadAmbient,
    ambientColorsFor,
    normalizeAppearance,
    applyTheme,
  };

  function tiles() { return [...document.querySelectorAll('#tiles .tile')]; }

  function setPage(next, focusIndex) {
    const all = tiles();
    const total = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    const target = Math.max(0, Math.min(next, total - 1));
    const pageChanged = target !== page;
    page = target;
    all.forEach((tile, index) => { tile.hidden = profileDock() && Math.floor(index / PAGE_SIZE) !== page; });
    const indicator = document.getElementById('dock-pagination');
    if (indicator) {
      indicator.hidden = !profileDock() || total <= 1;
      indicator.textContent = `${page + 1} / ${total}`;
    }
    const nav = document.getElementById('tiles');
    if (nav) {
      nav.style.setProperty('--dock-count', Math.min(PAGE_SIZE, all.length));
      if (profileDock() && pageChanged) {
        nav.classList.remove('menu-turn');
        void nav.offsetWidth;
        nav.classList.add('menu-turn');
      }
    }
    if (focusIndex !== undefined && all[focusIndex]) all[focusIndex].focus({ preventScroll: true });
  }

  function syncHomeSurface() {
    if (!isHome()) return;
    document.body.dataset.homeSurface = androidTv() && tvFrame() ? 'tv' : 'flex';
  }

  function paintBackdrop() {
    if (!isHome()) return;
    const choice = ['sculptural', 'aqua', 'flurry'].includes(config.tvAppearance) ? config.tvAppearance : 'sculptural';
    const motion = ['still', 'drift', 'reactive'].includes(config.tvMotion) ? config.tvMotion : 'drift';
    stopBackdrop();
    const halloween = document.documentElement.classList.contains('halloween');
    let colors = choice === 'sculptural' ? ambientColorsFor(config.ambientPreset) : stops;
    let key = choice === 'aqua' ? config.tvAquaPalette : choice === 'flurry' ? config.tvFlurryPalette : '';
    if (halloween) {
      if (choice === 'sculptural') colors = ['#FFA51F', '#F0453A', '#F3C46B'];
      else key = 'ember';
    }
    stopBackdrop = decorate(
      document.getElementById('tv-backdrop'),
      choice,
      reducedMotion.matches ? 'still' : motion,
      config.tvIntensity || 'balanced',
      colors,
      key,
    );
  }

  function apply(settings) {
    config = settings || {};
    applyTheme(config);
    if (!isHome()) return;
    const choice = ['sculptural', 'aqua', 'flurry'].includes(config.tvAppearance) ? config.tvAppearance : 'sculptural';
    document.body.dataset.tvAppearance = choice;
    syncHomeSurface();
    const motion = ['still', 'drift', 'reactive'].includes(config.tvMotion) ? config.tvMotion : 'drift';
    document.body.dataset.tvBackdrop = choice;
    document.body.dataset.tvMotion = reducedMotion.matches ? 'still' : motion;
    if (choice === 'sculptural' && !ambientConfig) {
      loadAmbient().then(() => { if (document.body.dataset.tvAppearance === 'sculptural') paintBackdrop(); });
    } else {
      paintBackdrop();
    }
    setPage(0);
  }

  function pullAmount() {
    if (config.tvIntensity === 'soft') return 16;
    if (config.tvIntensity === 'vivid') return 48;
    return 30;
  }

  function reactTo(x, y) {
    if (!isHome() || !motionLive()) return;
    const pull = pullAmount();
    const lean = config.tvMotion === 'reactive' ? 1 : 0.45;
    const el = document.getElementById('tv-backdrop');
    const dx = `${(x - 0.5) * pull * lean}px`;
    const dy = `${(y - 0.5) * pull * lean * 0.6}px`;
    document.body.style.setProperty('--look-x', dx);
    document.body.style.setProperty('--look-y', dy);
    el?.style.setProperty('--look-x', dx);
    el?.style.setProperty('--look-y', dy);
    field.nx = 0.62 + (x - 0.5) * (config.tvMotion === 'reactive' ? 0.28 : 0.1);
    field.ny = 0.42 + (y - 0.5) * (config.tvMotion === 'reactive' ? 0.2 : 0.08);
  }

  function showStreak(x, y, px, py) {
    if (!isHome() || !motionLive()) return;
    const host = document.getElementById('tv-backdrop');
    if (!host) return;
    const streak = document.createElement('i');
    streak.className = 'move-streak';
    streak.style.left = `${x * 100}%`;
    streak.style.top = `${y * 100}%`;
    streak.style.setProperty('--streak-angle', `${Math.atan2(py, px) * 180 / Math.PI}deg`);
    host.append(streak);
    setTimeout(() => streak.remove(), 460);
  }

  function flashSelection(el) {
    if (!el || !motionLive()) return;
    el.classList.remove('light-hit');
    void el.offsetWidth;
    el.classList.add('light-hit');
    const host = document.getElementById('tv-backdrop');
    if (!host) return;
    host.classList.remove('core-pulse');
    void host.offsetWidth;
    host.classList.add('core-pulse');
    document.body.classList.add('field-hot');
    setTimeout(() => document.body.classList.remove('field-hot'), 420);
  }

  document.addEventListener('slate:season', () => { if (isHome()) paintBackdrop(); });
  document.addEventListener('slate:appearance', event => apply(event.detail));
  document.addEventListener('slate:tiles', () => { if (isHome()) setPage(0); });
  document.addEventListener('focusin', event => {
    const rect = event.target.getBoundingClientRect?.();
    if (!rect || !rect.width) return;
    const x = (rect.left + rect.width / 2) / innerWidth;
    const y = (rect.top + rect.height / 2) / innerHeight;
    reactTo(x, y);
    if (lastFocus && lastFocus !== event.target) {
      const prev = lastFocus.getBoundingClientRect?.();
      if (prev) showStreak(x, y, rect.left - prev.left, rect.top - prev.top);
    }
    lastFocus = event.target;
  });
  document.addEventListener('pointermove', event => {
    const x = event.clientX / innerWidth;
    const y = event.clientY / innerHeight;
    reactTo(x, y);
    const now = Date.now();
    if (now - lastPointer < 180 || Math.hypot(event.movementX, event.movementY) < 8) return;
    lastPointer = now;
    showStreak(x, y, event.movementX, event.movementY);
    if (!isHome() && document.getElementById('preview-backdrop')?.dataset.backdrop === 'flurry') {
      field.nx = 0.62 + (x - 0.5) * 0.2;
      field.ny = 0.42 + (y - 0.5) * 0.16;
    }
  });
  document.addEventListener('click', event => {
    if (!isHome()) return;
    const tile = event.target.closest?.('.tile, #wx, .foot-link');
    if (tile) flashSelection(tile);
  });
  function visibleBox(el) {
    if (!el || !el.isConnected || el.hidden) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function dockRows() {
    const top = [document.getElementById('wx'), document.querySelector("a.foot-link[href='settings.html']")].filter(visibleBox);
    const middle = tiles().filter(visibleBox);
    const bottom = [...document.querySelectorAll('.home-tools .foot-link, #site-credit')].filter(visibleBox);
    return [top, middle, bottom].filter(row => row.length);
  }

  function nearestInRow(row, x) {
    let best = row[0];
    let bestDx = Infinity;
    for (const el of row) {
      const rect = el.getBoundingClientRect();
      const dx = Math.abs(rect.left + rect.width / 2 - x);
      if (dx < bestDx) {
        bestDx = dx;
        best = el;
      }
    }
    return best;
  }

  function moveDockFocus(key) {
    const rows = dockRows();
    const active = document.activeElement;
    let rowIndex = -1;
    let index = -1;
    rows.forEach((row, r) => {
      const found = row.indexOf(active);
      if (found >= 0) {
        rowIndex = r;
        index = found;
      }
    });
    if (rowIndex < 0) return false;
    if (key === 'ArrowLeft' || key === 'ArrowRight') {
      const step = key === 'ArrowRight' ? 1 : -1;
      if (active.classList.contains('tile')) {
        const all = tiles();
        const at = all.indexOf(active);
        const next = at + step;
        if (at >= 0 && next >= 0 && next < all.length) setPage(Math.floor(next / PAGE_SIZE), next);
        return true;
      }
      const next = rows[rowIndex][index + step];
      if (!next) return true;
      const here = active.getBoundingClientRect();
      const there = next.getBoundingClientRect();
      const gap = Math.abs((there.left + there.width / 2) - (here.left + here.width / 2));
      if (gap > 480) return true;
      next.focus({ preventScroll: true });
      return true;
    }
    const dir = key === 'ArrowDown' ? 1 : key === 'ArrowUp' ? -1 : 0;
    if (!dir) return false;
    const target = rows[rowIndex + dir];
    if (!target) return true;
    const rect = active.getBoundingClientRect();
    nearestInRow(target, rect.left + rect.width / 2).focus({ preventScroll: true });
    return true;
  }

  document.addEventListener('keydown', event => {
    if (!isHome() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'Enter') flashSelection(document.activeElement);
    if (!profileDock()) return;
    const fallback = document.getElementById('tv-app-fallback');
    if (fallback && !fallback.hidden) return;
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    if (!moveDockFocus(event.key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    document.body.classList.add('show-focus');
    if (typeof bumpIdle === 'function') bumpIdle();
  }, true);
  reducedMotion.addEventListener('change', () => {
    apply(config);
    document.dispatchEvent(new Event('slate:motion-preference'));
  });
  const setHidden = hidden => document.body.classList.toggle('tv-motion-paused', hidden);
  let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (!isHome()) return;
      const prevSurface = document.body.dataset.homeSurface;
      syncHomeSurface();
      if (document.body.dataset.homeSurface !== prevSurface) paintBackdrop();
    }, 180);
  });
  addEventListener('pagehide', () => { stopBackdrop(); setHidden(true); });
  document.addEventListener('visibilitychange', () => setHidden(document.hidden));
  // Pause CSS drift when the window loses focus (e.g. another app on the TV).
  addEventListener('blur', () => setHidden(true));
  addEventListener('focus', () => setHidden(document.hidden));
  addEventListener('pageshow', event => {
    setHidden(document.hidden);
    if (event.persisted) apply(config);
  });
  if (window.slateHomeSettings) apply(window.slateHomeSettings);
  else if (!isHome() && !document.documentElement.classList.contains('page-appearance')) {
    const promise = window.slateSettingsPromise
      || fetch('settings.json', { cache: 'no-store' }).then(response => response.json());
    if (!window.slateSettingsPromise) window.slateSettingsPromise = promise;
    promise.then(settings => apply(settings)).catch(() => apply({}));
  }
})();
