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

  window.SlateSurface = {
    TV_LAYOUT,
    applySurface: applyGallerySurface,
    fitGalleryFrame,
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
