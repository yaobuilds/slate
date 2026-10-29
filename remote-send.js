(() => {
  const params = new URLSearchParams(location.search);
  if (params.get("remote") !== "1") return;

  function isTvClient() {
    return document.documentElement.dataset.slateSurface === "tv"
      || !!window.SlateTV
      || /Android TV|Google TV/i.test(navigator.userAgent || "");
  }

  if (isTvClient()) {
    params.delete("remote");
    const q = params.toString();
    location.replace(`${location.pathname}${q ? `?${q}` : ""}${location.hash}`);
    return;
  }

  const REMOTE_KEYS = new Set([
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Enter", "Escape", "Backspace", "g", "G",
  ]);

  async function sendCommand(body) {
    try {
      const response = await fetch("remote/v1/command.json", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      return response.ok;
    } catch (err) {
      return false;
    }
  }

  function mountBanner() {
    if (document.getElementById("slate-remote-banner")) return;
    const bar = document.createElement("div");
    bar.id = "slate-remote-banner";
    bar.className = "slate-remote-banner";
    bar.innerHTML = '<span>Remote mode. Keys and taps go to the TV.</span><a href="remote.html">Remote pad</a><a href="settings.html">Settings</a>';
    document.body.prepend(bar);
  }

  document.documentElement.classList.add("slate-remote-control");
  mountBanner();

  document.addEventListener("keydown", (event) => {
    if (!REMOTE_KEYS.has(event.key)) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    sendCommand({ type: "key", key: event.key });
  }, true);

  document.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("#slate-remote-banner")) return;
    const target = event.target instanceof Element
      ? event.target.closest("a, button, input, [role='button'], .home-tile, .app-tile")
      : null;
    if (!target || target.closest("#slate-remote-banner")) return;
    event.preventDefault();
    event.stopPropagation();
    sendCommand({ type: "key", key: "Enter" });
  }, true);
})();
