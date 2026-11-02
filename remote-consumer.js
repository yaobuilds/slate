(function () {
  const HEARTBEAT_MS = 15000;
  const POLL_MS = 500;
  const CURSOR_KEY = "slate-remote-seq";

  function isTvClient() {
    const surface = document.documentElement.dataset.slateSurface;
    if (surface === "pointer" || surface === "touch") return false;
    return surface === "tv"
      || !!window.SlateTV
      || /Android TV|Google TV/i.test(navigator.userAgent || "");
  }

  if (!isTvClient()) return;

  let since = 0;
  let primed = false;
  let pollTimer = 0;

  try {
    const saved = Number(sessionStorage.getItem(CURSOR_KEY));
    if (Number.isFinite(saved) && saved > 0) {
      since = saved;
      primed = true;
    }
  } catch (err) {
    /* Private mode may block storage. The first poll still drops the backlog. */
  }

  function pageName() {
    const path = location.pathname.split("/").pop() || "index.html";
    return path.replace(/\.html$/, "") || "index";
  }

  function storeCursor(seq) {
    since = seq;
    try {
      sessionStorage.setItem(CURSOR_KEY, String(since));
    } catch (err) {
      /* Ignore quota or private-mode failures. */
    }
  }

  function remember(seq) {
    if (typeof seq !== "number" || !Number.isFinite(seq) || seq <= since) return;
    storeCursor(seq);
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
      const latest = typeof body.latest === "number" ? body.latest : since;
      if (latest < since) {
        primed = true;
        storeCursor(latest);
        return;
      }
      const events = Array.isArray(body.events) ? body.events : [];
      if (!primed) {
        primed = true;
        let cursor = since;
        for (const ev of events) {
          if (ev && typeof ev.seq === "number" && ev.seq > cursor) cursor = ev.seq;
        }
        if (latest > cursor) cursor = latest;
        remember(cursor);
        return;
      }
      for (const ev of events) {
        if (ev && typeof ev.seq === "number") {
          if (ev.seq <= since) continue;
          remember(ev.seq);
        }
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
        body: JSON.stringify({ page: pageName(), tv: true }),
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
  void pollTimer;
})();
