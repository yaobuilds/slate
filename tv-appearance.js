/* Home presentation. Local artwork and decorative motion only. */
(() => {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const stops = ['#72c9d0', '#837ee0', '#db9cae', '#b7d2e4'];
  const FLURRY_REST_NX = 0.62;
  const FLURRY_REST_NY = 0.42;
  const flurryStreams = [
    { slot: 0.15, rgb: [196, 52, 128], len: 0.55, phase: 0.2 },
    { slot: 1.35, rgb: [52, 92, 188], len: 0.75, phase: 1.1 },
    { slot: 2.55, rgb: [40, 160, 176], len: 0.95, phase: 2.4 },
    { slot: 3.85, rgb: [188, 156, 48], len: 0.70, phase: 3.6 },
    { slot: 5.15, rgb: [40, 150, 88], len: 0.85, phase: 4.8 },
  ];
  const field = { nx: FLURRY_REST_NX, ny: FLURRY_REST_NY, targetNx: FLURRY_REST_NX, targetNy: FLURRY_REST_NY };
  let stopBackdrop = () => {};
  let config = {};
  let page = 0;
  let lastFocus = null;
  let lastPointer = 0;
  const PAGE_SIZE = 6;
  const isHome = () => document.body.classList.contains('page-home');
  const androidTv = () => typeof onAndroidTv === 'function' && onAndroidTv();
  const tvFrame = () => typeof TV_LAYOUT !== 'undefined' && TV_LAYOUT.matches;
  const flurryDock = () => isHome() && androidTv() && tvFrame() && document.body.dataset.tvAppearance === 'flurry';
  const motionLive = () => !reducedMotion.matches && config.tvMotion !== 'still';

  function flurryBrushScale(intensity) {
    if (intensity === 'soft') return 0.9;
    if (intensity === 'vivid') return 1.12;
    return 1;
  }

  function buildFlurryBrushes() {
    const makeColor = (r, g, b) => {
      const brush = document.createElement('canvas');
      brush.width = 96;
      brush.height = 96;
      const bctx = brush.getContext('2d');
      if (!bctx) return brush;
      const grad = bctx.createRadialGradient(48, 48, 0, 48, 48, 48);
      grad.addColorStop(0, `rgba(${r},${g},${b},0.55)`);
      grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      bctx.fillStyle = grad;
      bctx.fillRect(0, 0, 96, 96);
      return brush;
    };
    const white = makeColor(255, 255, 255);
    return { colors: flurryStreams.map(s => makeColor(...s.rgb)), white };
  }

  function clampFlurryCore() {
    field.nx = Math.max(0.5, Math.min(0.76, field.nx));
    field.ny = Math.max(0.3, Math.min(0.56, field.ny));
  }

  function flurryAim(motion, frameCount) {
    const driftT = frameCount * 0.05 * (Math.PI * 2 / 40);
    const ellipseNx = FLURRY_REST_NX + Math.sin(driftT) * 0.02;
    const ellipseNy = FLURRY_REST_NY + Math.cos(driftT) * 0.015;
    if (motion === 'still') return { nx: ellipseNx, ny: ellipseNy };
    return {
      nx: ellipseNx * 0.5 + field.targetNx * 0.5,
      ny: ellipseNy * 0.5 + field.targetNy * 0.5,
    };
  }

  function drawFlurry(ctx, state) {
    const { spin, brushes, brushScale, motion, frameCount, firstFrame } = state;
    const aim = flurryAim(motion, frameCount);
    field.nx += (aim.nx - field.nx) * 0.08;
    field.ny += (aim.ny - field.ny) * 0.08;
    clampFlurryCore();
    const coreX = 960 * field.nx;
    const coreY = 540 * field.ny;
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.fillStyle = firstFrame ? '#000' : 'rgba(0,0,0,0.08)';
    ctx.fillRect(0, 0, 960, 540);
    state.firstFrame = false;
    ctx.globalCompositeOperation = 'lighter';
    const baseLen = 250;
    for (let i = 0; i < flurryStreams.length; i += 1) {
      const stream = flurryStreams[i];
      const angle = stream.slot + spin + 0.45 * Math.sin(spin * 0.55 + stream.slot);
      const length = baseLen * stream.len * (1 + 0.12 * Math.sin(spin * 0.3 + stream.phase));
      const headX = coreX - Math.cos(angle) * length;
      const headY = coreY - Math.sin(angle) * length;
      const perpX = -Math.sin(angle);
      const perpY = Math.cos(angle);
      const brush = brushes.colors[i];
      for (let s = 0; s < 6; s += 1) {
        const t = s / 5;
        const lx = headX + (coreX - headX) * t;
        const ly = headY + (coreY - headY) * t;
        const bend = Math.sin(t * Math.PI) * 50;
        const px = lx + perpX * bend;
        const py = ly + perpY * bend;
        const w = (48 + Math.sin(t * Math.PI) * 88) * brushScale;
        ctx.globalAlpha = 0.02 + Math.sin(t * Math.PI) * 0.03;
        ctx.drawImage(brush, px - w / 2, py - w / 2, w, w);
      }
    }
    const coreSize = 48 * brushScale;
    ctx.globalAlpha = 0.2;
    ctx.drawImage(brushes.white, coreX - coreSize / 2, coreY - coreSize / 2, coreSize, coreSize);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
  }

  function setFlurryTarget(x, y, motion) {
    const mx = motion === 'reactive' ? 0.16 : 0.06;
    const my = motion === 'reactive' ? 0.10 : 0.04;
    field.targetNx = FLURRY_REST_NX + (x - 0.5) * mx;
    field.targetNy = FLURRY_REST_NY + (y - 0.5) * my;
  }

  function flurryTargetLive(el) {
    if (!el || el.dataset.backdrop !== 'flurry') return false;
    const motion = el.dataset.motion;
    if (motion !== 'drift' && motion !== 'reactive') return false;
    if (isHome()) return motionLive();
    return !reducedMotion.matches;
  }

  function decorate(el, backdrop, motion, intensity, ambientColors = stops) {
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
      const palette = ambientColors.length ? ambientColors : stops;
      for (let i = 0; i < 5; i += 1) {
        const form = document.createElement('i');
        form.className = 'sculpt-form';
        form.style.setProperty('--form-i', i);
        form.style.setProperty('--form-color', palette[i % palette.length]);
        el.append(form);
      }
    } else if (backdrop === 'landscape') {
      const image = document.createElement('img');
      image.src = 'assets/wallpapers/alpine.jpg';
      image.alt = '';
      image.addEventListener('error', () => { el.dataset.backdrop = 'unavailable'; });
      el.append(image);
    } else if (backdrop === 'flurry' || backdrop === 'aqua') {
      const canvas = document.createElement('canvas');
      canvas.className = 'flurry-field';
      el.append(canvas);
      canvas.width = 960;
      canvas.height = 540;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        field.nx = FLURRY_REST_NX;
        field.ny = FLURRY_REST_NY;
        field.targetNx = FLURRY_REST_NX;
        field.targetNy = FLURRY_REST_NY;
        const liveMotion = reducedMotion.matches ? 'still' : motion;
        const brushes = buildFlurryBrushes();
        const brushScale = flurryBrushScale(intensity);
        let spin = 0;
        let frameCount = 0;
        const state = {
          spin, brushes, brushScale, motion: liveMotion, frameCount, firstFrame: true,
        };
        const step = () => {
          state.spin += 0.008;
          state.frameCount += 1;
          drawFlurry(ctx, state);
        };
        for (let n = 0; n < 48; n += 1) step();
        if (liveMotion !== 'still') {
          timer = setInterval(() => {
            if (document.hidden || document.body.classList.contains('tv-motion-paused')) return;
            step();
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
    return () => { if (timer) clearInterval(timer); el.replaceChildren(); };
  }
  window.SlateLooks = { decorate };

  function tiles() { return [...document.querySelectorAll('#tiles .tile')]; }

  function setPage(next, focusIndex) {
    const all = tiles();
    const total = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    page = Math.max(0, Math.min(next, total - 1));
    all.forEach((tile, index) => { tile.hidden = flurryDock() && Math.floor(index / PAGE_SIZE) !== page; });
    const indicator = document.getElementById('dock-pagination');
    if (indicator) {
      indicator.hidden = !flurryDock() || total <= 1;
      indicator.textContent = `${page + 1} / ${total}`;
    }
    const nav = document.getElementById('tiles');
    if (nav) {
      nav.style.setProperty('--dock-count', Math.min(PAGE_SIZE, all.length));
      if (flurryDock()) {
        nav.classList.remove('menu-turn');
        void nav.offsetWidth;
        nav.classList.add('menu-turn');
      }
    }
    if (focusIndex !== undefined && all[focusIndex]) all[focusIndex].focus({ preventScroll: true });
  }

  function apply(settings) {
    config = settings || {};
    if (!isHome()) return;
    const choice = config.tvAppearance === 'flurry' || config.tvAppearance === 'aqua' ? 'flurry' : 'sculptural';
    document.body.dataset.tvAppearance = choice;
    document.body.dataset.homeSurface = androidTv() && tvFrame() ? 'tv' : 'flex';
    const motion = ['still', 'drift', 'reactive'].includes(config.tvMotion) ? config.tvMotion : 'drift';
    document.body.dataset.tvBackdrop = choice;
    document.body.dataset.tvMotion = reducedMotion.matches ? 'still' : motion;
    stopBackdrop();
    stopBackdrop = decorate(document.getElementById('tv-backdrop'), choice, motion, config.tvIntensity || 'balanced');
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
    if (flurryTargetLive(el)) setFlurryTarget(x, y, config.tvMotion);
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
    const preview = document.getElementById('preview-backdrop');
    if (flurryTargetLive(preview)) {
      const previewMotion = preview.dataset.motion || 'drift';
      setFlurryTarget(x, y, previewMotion);
    }
  });
  document.addEventListener('click', event => {
    if (!isHome()) return;
    const tile = event.target.closest?.('.tile, #wx, .foot-link');
    if (tile) flashSelection(tile);
  });
  document.addEventListener('keydown', event => {
    if (!isHome() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'Enter') flashSelection(document.activeElement);
    if (!flurryDock()) return;
    const fallback = document.getElementById('tv-app-fallback');
    if (fallback && !fallback.hidden) return;
    const active = document.activeElement;
    if (active?.classList.contains('tile')) {
      const all = tiles();
      const index = all.indexOf(active);
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        const next = index + (event.key === 'ArrowRight' ? 1 : -1);
        if (next >= 0 && next < all.length) {
          event.preventDefault();
          event.stopImmediatePropagation();
          setPage(Math.floor(next / PAGE_SIZE), next);
          document.body.classList.add('show-focus');
          if (typeof bumpIdle === 'function') bumpIdle();
        }
      }
    }
  }, true);
  reducedMotion.addEventListener('change', () => {
    apply(config);
    document.dispatchEvent(new Event('slate:motion-preference'));
  });
  let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (isHome()) apply(config); }, 180);
  });
  addEventListener('pagehide', () => stopBackdrop());
  const setHidden = hidden => document.body.classList.toggle('tv-motion-paused', hidden);
  document.addEventListener('visibilitychange', () => setHidden(document.hidden));
  addEventListener('blur', () => setHidden(true));
  addEventListener('focus', () => setHidden(false));
  addEventListener('pageshow', event => { if (event.persisted) apply(config); });
  if (window.slateHomeSettings) apply(window.slateHomeSettings);
})();
