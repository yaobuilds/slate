(function () {
  const TV_LAYOUT = window.matchMedia("(min-width: 960px) and (min-height: 540px) and (min-aspect-ratio: 16/9)");
  const DRIFT_MS = 3 * 60 * 1000;
  const DRIFT = [
    [0, 0], [1, 0], [2, 1], [2, 0], [1, -1], [0, -2], [-1, -2], [-2, -1],
    [-2, 0], [-1, 1], [0, 2], [1, 2], [2, 2], [1, 1], [-1, -1], [-2, -2],
  ];
  let driftIndex = 0;

  function shiftTerm(px) {
    if (px === 0) return "-50%";
    const text = Number(Math.abs(px).toFixed(4)).toString();
    return px > 0 ? `calc(-50% + ${text}px)` : `calc(-50% - ${text}px)`;
  }

  function detectSurface() {
    if (window.SlateTV || /Android TV|Google TV/i.test(navigator.userAgent || "")) return "tv";
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) return "pointer";
    if (window.matchMedia("(any-pointer: coarse)").matches) return "touch";
    return "remote";
  }

  function applyHtmlSurface() {
    document.documentElement.dataset.slateSurface = detectSurface();
  }

  function androidTv() {
    const ua = navigator.userAgent || "";
    return /Android TV|Google TV|AFT[A-Z0-9]|CrKey/i.test(ua);
  }

  function applyGallerySurface() {
    const tv = androidTv() && TV_LAYOUT.matches;
    document.body.dataset.slateSurface = tv ? "tv" : "flex";
    return tv;
  }

  function fitGalleryFrame(frame) {
    if (!frame) return;
    const tv = document.body.dataset.slateSurface === "tv";
    const [x, y] = DRIFT[driftIndex];
    if (tv) {
      const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
      frame.style.transform =
        `translate(${shiftTerm(x * scale)}, ${shiftTerm(y * scale)}) scale(${scale})`;
      return;
    }
    frame.style.transform = `translate(${x}px, ${y}px)`;
  }

  const REVEAL_PAD = 24;

  function overflowAxis(style, axis) {
    const key = axis === "y" ? "overflowY" : "overflowX";
    return style[key] || style.overflow || "visible";
  }

  function axisScrollport(el, axis) {
    if (!el || el.nodeType !== 1) return false;
    const style = getComputedStyle(el);
    const flow = overflowAxis(style, axis);
    if (flow !== "auto" && flow !== "scroll") return false;
    if (el === document.body && style.position === "fixed") return false;
    const size = axis === "y" ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
    return size > 1;
  }

  function inViewport(rect, pad) {
    return (
      rect.top >= pad &&
      rect.left >= pad &&
      rect.bottom <= window.innerHeight - pad &&
      rect.right <= window.innerWidth - pad
    );
  }

  function containerViewport(container) {
    if (container === document.scrollingElement || container === document.documentElement || container === document.body) {
      return { top: 0, left: 0, bottom: window.innerHeight, right: window.innerWidth };
    }
    const r = container.getBoundingClientRect();
    return { top: r.top, left: r.left, bottom: r.bottom, right: r.right };
  }

  function revealAxis(container, el, axis, pad) {
    const er = el.getBoundingClientRect();
    const cr = containerViewport(container);
    if (axis === "y") {
      if (er.top < cr.top + pad) {
        container.scrollTop += er.top - (cr.top + pad);
        return true;
      }
      if (er.bottom > cr.bottom - pad) {
        container.scrollTop += er.bottom - (cr.bottom - pad);
        return true;
      }
      return false;
    }
    if (er.left < cr.left + pad) {
      container.scrollLeft += er.left - (cr.left + pad);
      return true;
    }
    if (er.right > cr.right - pad) {
      container.scrollLeft += er.right - (cr.right - pad);
      return true;
    }
    return false;
  }

  function documentScrollport() {
    const el = document.scrollingElement || document.body;
    if (!el) return null;
    const style = getComputedStyle(el);
    const oy = overflowAxis(style, "y");
    if (oy !== "auto" && oy !== "scroll") return null;
    if (style.position === "fixed") return null;
    if (el.scrollHeight <= el.clientHeight + 1) return null;
    return el;
  }

  function reveal(el) {
    if (!el || typeof el.getBoundingClientRect !== "function") return;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 && rect.height <= 0) return;
    if (inViewport(rect, REVEAL_PAD)) return;

    let innerScrollport = false;
    let node = el.parentElement;
    while (node && node !== document.documentElement) {
      if (axisScrollport(node, "y")) {
        innerScrollport = true;
        revealAxis(node, el, "y", REVEAL_PAD);
      }
      if (axisScrollport(node, "x")) {
        innerScrollport = true;
        revealAxis(node, el, "x", REVEAL_PAD);
      }
      node = node.parentElement;
    }

    if (innerScrollport) return;

    const root = documentScrollport();
    if (!root) return;
    revealAxis(root, el, "y", REVEAL_PAD);
    revealAxis(root, el, "x", REVEAL_PAD);
  }

  document.addEventListener("focusin", (event) => {
    const target = event.target;
    if (!target || target === document.body || typeof target.getBoundingClientRect !== "function") return;
    const surface = document.documentElement.dataset.slateSurface;
    if (surface === "tv") {
      reveal(target);
      return;
    }
    const rect = target.getBoundingClientRect();
    if (rect.width <= 0 && rect.height <= 0) return;
    if (!inViewport(rect, REVEAL_PAD)) reveal(target);
  });

  window.SlateSurface = {
    TV_LAYOUT,
    applySurface: applyGallerySurface,
    fitGalleryFrame,
    reveal,
    onDrift(callback) {
      setInterval(() => {
        driftIndex = (driftIndex + 1) % DRIFT.length;
        callback(DRIFT[driftIndex]);
      }, DRIFT_MS);
    },
  };

  applyHtmlSurface();
  const hover = window.matchMedia("(hover: hover)");
  const coarse = window.matchMedia("(any-pointer: coarse)");
  if (hover.addEventListener) {
    hover.addEventListener("change", applyHtmlSurface);
    coarse.addEventListener("change", applyHtmlSurface);
    TV_LAYOUT.addEventListener("change", applyHtmlSurface);
  } else if (hover.addListener) {
    hover.addListener(applyHtmlSurface);
    coarse.addListener(applyHtmlSurface);
    TV_LAYOUT.addListener(applyHtmlSurface);
  }
})();
