/* Home presentation. Local artwork and decorative motion only. */
(() => {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const stops = ['#72c9d0', '#837ee0', '#db9cae', '#b7d2e4'];
  const flurryHues = ['#ff4ad8', '#8a4bff', '#3a6dff', '#3ee7ff', '#ffe14a', '#3dff7a'];
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

  function drawFlurry(ctx, tick) {
    const coreX = 960 * field.nx;
    const coreY = 540 * field.ny;
    ctx.fillStyle = 'rgba(0,0,0,0.2)';
    ctx.fillRect(0, 0, 960, 540);
    ctx.lineCap = 'round';
    for (let i = 0; i < 16; i += 1) {
      const angle = tick * 0.12 + i * 0.42;
      const sx = 480 + Math.cos(angle) * 560;
      const sy = 270 + Math.sin(angle * 1.25) * 360;
      ctx.strokeStyle = flurryHues[i % flurryHues.length];
      ctx.globalAlpha = 0.2;
      ctx.lineWidth = 22 - (i % 5) * 3;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.quadraticCurveTo((sx + coreX) / 2, (sy + coreY) / 2 + Math.sin(angle) * 50, coreX, coreY);
      ctx.stroke();
    }
    const glow = ctx.createRadialGradient(coreX, coreY, 0, coreX, coreY, 78);
    glow.addColorStop(0, 'rgba(255,255,255,0.95)');
    glow.addColorStop(0.35, 'rgba(190,240,255,0.45)');
    glow.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.globalAlpha = 1;
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(coreX, coreY, 78, 0, Math.PI * 2);
    ctx.fill();
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
    } else if (backdrop === 'aqua') {
      el.innerHTML = '<svg class="aqua-ribbons" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="ribbon-slate" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#256a9d"/><stop offset=".48" stop-color="#79c3d4"/><stop offset="1" stop-color="#5a4788"/></linearGradient></defs><g fill="none" stroke="url(#ribbon-slate)"><path class="aqua-band" stroke-width="190" opacity=".28" d="M-400 1100C300-240 660 1360 1210 650S1860 180 2300 0"/><path class="aqua-band" stroke-width="88" opacity=".55" d="M-300 1060C390 20 630 1270 1180 660S1850 320 2300 90"/><path class="aqua-band" stroke-width="3" opacity=".8" d="M-300 1000C390 20 620 1190 1160 620S1850 320 2300 90"/><path class="aqua-band" stroke-width="40" opacity=".3" d="M-300 1180C300 90 800 1400 1340 700S2000 180 2300 200"/></g></svg>';
    } else if (backdrop === 'flurry') {
      const canvas = document.createElement('canvas');
      canvas.className = 'flurry-field';
      el.append(canvas);
      canvas.width = 960;
      canvas.height = 540;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        let tick = 0;
        ctx.fillStyle = '#000';
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
    return () => { if (timer) clearInterval(timer); el.replaceChildren(); };
  }
  window.SlateLooks = { decorate };

  function tiles() { return [...document.querySelectorAll('#tiles .tile')]; }

  function setPage(next, focusIndex) {
    const all = tiles();
    const total = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    page = Math.max(0, Math.min(next, total - 1));
    all.forEach((tile, index) => { tile.hidden = profileDock() && Math.floor(index / PAGE_SIZE) !== page; });
    const indicator = document.getElementById('dock-pagination');
    if (indicator) {
      indicator.hidden = !profileDock() || total <= 1;
      indicator.textContent = `${page + 1} / ${total}`;
    }
    const nav = document.getElementById('tiles');
    if (nav) {
      nav.style.setProperty('--dock-count', Math.min(PAGE_SIZE, all.length));
      if (profileDock()) {
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
    const choice = ['sculptural', 'aqua', 'flurry'].includes(config.tvAppearance) ? config.tvAppearance : 'sculptural';
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
  document.addEventListener('keydown', event => {
    if (!isHome() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'Enter') flashSelection(document.activeElement);
    if (!profileDock()) return;
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
