/* TV Home presentation. Local artwork and decorative motion only. */
(() => {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const stops = ['#72c9d0', '#837ee0', '#db9cae', '#b7d2e4'];
  let stopBackdrop = () => {};
  let config = {};
  let page = 0;
  const PAGE_SIZE = 6;
  const isTvHome = () => document.body.classList.contains('page-home') && onAndroidTv();
  const scenic = () => document.body.dataset.tvAppearance === 'aqua';

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
    } else if (backdrop === 'orbit') {
      for (let i = 0; i < 9; i += 1) {
        const ring = document.createElement('i');
        ring.className = 'orbit-ring';
        ring.style.setProperty('--ring-i', i);
        ring.style.setProperty('--ring-color', stops[i % stops.length]);
        el.append(ring);
      }
    } else if (backdrop === 'flurry') {
      const canvas = document.createElement('canvas');
      el.append(canvas);
      canvas.width = 960;
      canvas.height = 540;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        let tick = 0;
        let last = [];
        const render = () => {
          tick += .035;
          ctx.fillStyle = 'rgba(16,20,26,.11)';
          ctx.fillRect(0, 0, 960, 540);
          for (let i = 0; i < 42; i += 1) {
            const phase = tick * (.3 + (i % 5) * .02) + i * .41;
            const x = 480 + Math.sin(phase * 1.7) * (150 + i * 4) + Math.cos(phase * .67) * 100;
            const y = 300 + Math.cos(phase * 1.2) * (60 + i * 2) + Math.sin(phase * 2.1) * 48;
            ctx.strokeStyle = stops[i % stops.length];
            ctx.lineWidth = 1.2 + (i % 3) * .6;
            ctx.globalAlpha = .24;
            ctx.beginPath();
            ctx.moveTo(last[i]?.[0] ?? x, last[i]?.[1] ?? y);
            ctx.lineTo(x, y);
            ctx.stroke();
            last[i] = [x, y];
          }
          ctx.globalAlpha = 1;
        };
        ctx.fillStyle = '#10141A';
        ctx.fillRect(0, 0, 960, 540);
        for (let n = 0; n < 100; n += 1) render();
        if (motion !== 'still' && !reducedMotion.matches) {
          timer = setInterval(() => {
            if (!document.hidden && !document.body.classList.contains('tv-motion-paused')) render();
          }, 42);
        }
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
    all.forEach((tile, index) => { tile.hidden = scenic() && Math.floor(index / PAGE_SIZE) !== page; });
    const indicator = document.getElementById('dock-pagination');
    if (indicator) {
      indicator.hidden = !scenic() || total <= 1;
      indicator.textContent = `${page + 1} / ${total}`;
    }
    const nav = document.getElementById('tiles');
    if (nav) {
      nav.style.setProperty('--dock-count', Math.min(PAGE_SIZE, all.length));
      if (scenic()) {
        nav.classList.remove('menu-turn');
        void nav.offsetWidth;
        nav.classList.add('menu-turn');
      }
    }
    if (focusIndex !== undefined && all[focusIndex]) all[focusIndex].focus({ preventScroll: true });
  }

  function apply(settings) {
    config = settings || {};
    if (!isTvHome()) return;
    document.body.dataset.tvAppearance = config.tvAppearance === 'aqua' && TV_LAYOUT.matches ? 'aqua' : 'sculptural';
    const backdrop = document.body.dataset.tvAppearance === 'aqua' ? 'aqua' : 'sculptural';
    const motion = ['still', 'drift', 'reactive'].includes(config.tvMotion) ? config.tvMotion : 'drift';
    document.body.dataset.tvBackdrop = backdrop;
    document.body.dataset.tvMotion = reducedMotion.matches ? 'still' : motion;
    stopBackdrop();
    stopBackdrop = decorate(document.getElementById('tv-backdrop'), backdrop, motion, config.tvIntensity || 'balanced');
    setPage(0);
  }

  function pullAmount() {
    if (config.tvIntensity === 'soft') return 14;
    if (config.tvIntensity === 'vivid') return 36;
    return 24;
  }

  function reactTo(x, y) {
    if (!isTvHome() || config.tvMotion !== 'reactive' || reducedMotion.matches) return;
    const pull = pullAmount();
    const el = document.getElementById('tv-backdrop');
    document.body.style.setProperty('--look-x', `${(x - .5) * pull}px`);
    document.body.style.setProperty('--look-y', `${(y - .5) * pull * .6}px`);
    el?.style.setProperty('--look-x', `${(x - .5) * pull}px`);
    el?.style.setProperty('--look-y', `${(y - .5) * pull * .6}px`);
  }

  function flashSelection(el) {
    if (!el || reducedMotion.matches || config.tvMotion === 'still') return;
    el.classList.remove('light-hit');
    void el.offsetWidth;
    el.classList.add('light-hit');
  }

  document.addEventListener('slate:appearance', event => apply(event.detail));
  document.addEventListener('slate:tiles', () => { if (isTvHome()) setPage(0); });
  document.addEventListener('focusin', event => {
    const rect = event.target.getBoundingClientRect?.();
    if (rect) reactTo((rect.left + rect.width / 2) / innerWidth, (rect.top + rect.height / 2) / innerHeight);
  });
  document.addEventListener('pointermove', event => reactTo(event.clientX / innerWidth, event.clientY / innerHeight));
  document.addEventListener('click', event => {
    if (!isTvHome()) return;
    const tile = event.target.closest?.('.tile, #wx, .foot-link');
    if (tile) flashSelection(tile);
  });
  document.addEventListener('keydown', event => {
    if (!isTvHome() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'Enter') flashSelection(document.activeElement);
    if (!scenic()) return;
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
    resizeTimer = setTimeout(() => { if (isTvHome()) apply(config); }, 180);
  });
  addEventListener('pagehide', () => stopBackdrop());
  const setHidden = hidden => document.body.classList.toggle('tv-motion-paused', hidden);
  document.addEventListener('visibilitychange', () => setHidden(document.hidden));
  addEventListener('blur', () => setHidden(true));
  addEventListener('focus', () => setHidden(false));
  addEventListener('pageshow', event => { if (event.persisted) apply(config); });
  if (window.slateHomeSettings) apply(window.slateHomeSettings);
})();
