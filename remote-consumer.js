(function () {
  const HEARTBEAT_MS = 15000;
  const POLL_MS = 500;
  let since = 0;
  let pollTimer = 0;

  function pageName() {
    const path = location.pathname.split("/").pop() || "index.html";
    return path.replace(/\.html$/, "") || "index";
  }

  function dispatchKey(key) {
    try {
      document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    } catch (err) {
      /* Older WebViews may lack KeyboardEvent constructor. */
    }
  }

  function runBridge(action) {
    const bridge = window.SlateTV;
    if (!bridge || typeof bridge !== "object") {
      if (action === "navigateHome") location.href = "index.html";
      return;
    }
    if (action === "openScreensaverSettings" && typeof bridge.openScreensaverSettings === "function") {
      bridge.openScreensaverSettings();
      return;
    }
    if (action === "openGoogleTvHome" && typeof bridge.openGoogleTvHome === "function") {
      bridge.openGoogleTvHome();
      return;
    }
    if (action === "navigateHome" && typeof bridge.goHome === "function") {
      bridge.goHome();
      return;
    }
    if (action === "navigateHome") location.href = "index.html";
  }

  function handleEvent(ev) {
    if (!ev || typeof ev !== "object") return;
    if (ev.type === "key" && typeof ev.key === "string") {
      dispatchKey(ev.key);
      return;
    }
    if (ev.type === "bridge" && typeof ev.action === "string") {
      runBridge(ev.action);
    }
  }

  async function pollEvents() {
    try {
      const response = await fetch(`/remote/v1/events.json?since=${since}`, { cache: "no-store" });
      if (!response.ok) return;
      const body = await response.json();
      const events = Array.isArray(body.events) ? body.events : [];
      for (const ev of events) {
        if (typeof ev.seq === "number" && ev.seq > since) since = ev.seq;
        handleEvent(ev);
      }
    } catch (err) {
      /* Server may be local-only; ignore until LAN is up. */
    }
  }

  async function heartbeat() {
    try {
      await fetch("/remote/v1/heartbeat.json", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: pageName() }),
        cache: "no-store",
      });
    } catch (err) {
      /* Ignore transient network errors. */
    }
  }

  function tick() {
    pollEvents();
    pollTimer = window.setTimeout(tick, POLL_MS);
  }

  heartbeat();
  setInterval(heartbeat, HEARTBEAT_MS);
  tick();
})();
