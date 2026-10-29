(function () {
  function detectSurface() {
    if (window.SlateTV || /Android TV|Google TV/i.test(navigator.userAgent || "")) return "tv";
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) return "pointer";
    if (window.matchMedia("(any-pointer: coarse)").matches) return "touch";
    return "remote";
  }

  function applySurface() {
    document.documentElement.dataset.slateSurface = detectSurface();
  }

  applySurface();
  const hover = window.matchMedia("(hover: hover)");
  const coarse = window.matchMedia("(any-pointer: coarse)");
  if (hover.addEventListener) {
    hover.addEventListener("change", applySurface);
    coarse.addEventListener("change", applySurface);
  } else if (hover.addListener) {
    hover.addListener(applySurface);
    coarse.addListener(applySurface);
  }
})();
