(function () {
  function markedHost() {
    return /(?:^|; )slate-host=1(?:;|$)/.test(document.cookie);
  }

  function moveToLoopback() {
    const host = location.hostname;
    if (window.isSecureContext) return false;
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") return false;
    if (!markedHost()) return false;
    const port = location.port || "80";
    location.replace(`http://127.0.0.1:${port}${location.pathname}${location.search}${location.hash}`);
    return true;
  }

  moveToLoopback();
  window.SlateLocate = { moveToLoopback };
})();
