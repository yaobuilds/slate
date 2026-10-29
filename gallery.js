(() => {
  const ID_RE = /^[0-9a-f]{32}$/;
  const REFRESH_MS = 60 * 1000;
  const frame = document.getElementById("gallery-frame");
  const photoEl = document.getElementById("gallery-photo");
  const emptyEl = document.getElementById("gallery-empty");
  const prevEdge = document.getElementById("gallery-prev");
  const nextEdge = document.getElementById("gallery-next");
  const prevBar = document.getElementById("gallery-prev-bar");
  const nextBar = document.getElementById("gallery-next-bar");
  const uploadWrap = document.getElementById("gallery-upload");
  const addBtn = document.getElementById("gallery-add");
  const fileInput = document.getElementById("gallery-file");
  const uploadMsg = document.getElementById("gallery-upload-msg");
  const tvControls = [prevBar, nextBar, document.getElementById("gallery-home"), addBtn].filter(Boolean);

  let photos = [];
  let index = 0;
  let listSig = "";
  let currentId = "";

  function isTv() {
    return document.body.dataset.slateSurface === "tv";
  }

  function pointerOrTouch() {
    return window.matchMedia("(pointer: coarse)").matches || window.matchMedia("(hover: none)").matches;
  }

  function showUploadUi() {
    if (isTv() || !uploadWrap) return;
    uploadWrap.hidden = false;
  }

  function listSignature(list) {
    return list.map((p) => p.id).join(",");
  }

  function validPhotos(data) {
    if (!data || !Array.isArray(data.photos)) return [];
    return data.photos.filter(
      (p) => p && ID_RE.test(p.id) && Number(p.w) > 0 && Number(p.h) > 0,
    );
  }

  async function fetchList(full) {
    const headers = { "Cache-Control": "no-store" };
    if (full) headers["X-Slate-Full"] = "1";
    const resp = await fetch("/gallery.json", { cache: "no-store", headers });
    if (resp.status === 401) return null;
    if (!resp.ok) return null;
    return resp.json();
  }

  function photoSrc(item) {
    if (item.src && typeof item.src === "string") return item.src;
    return `/gallery/${item.id}.jpg`;
  }

  function updateNav() {
    const has = photos.length > 0;
    const atStart = index <= 0;
    const atEnd = index >= photos.length - 1;
    for (const btn of [prevEdge, prevBar]) {
      if (btn) {
        btn.disabled = !has || atStart;
      }
    }
    for (const btn of [nextEdge, nextBar]) {
      if (btn) {
        btn.disabled = !has || atEnd;
      }
    }
  }

  function showEmpty() {
    currentId = "";
    photoEl.hidden = true;
    photoEl.removeAttribute("src");
    photoEl.removeAttribute("width");
    photoEl.removeAttribute("height");
    emptyEl.hidden = false;
    updateNav();
  }

  function showPhoto(i) {
    if (!photos.length) {
      showEmpty();
      return;
    }
    index = Math.max(0, Math.min(i, photos.length - 1));
    const item = photos[index];
    emptyEl.hidden = true;
    photoEl.hidden = false;
    photoEl.width = Number(item.w);
    photoEl.height = Number(item.h);
    if (item.id !== currentId) {
      currentId = item.id;
      photoEl.src = photoSrc(item);
    }
    updateNav();
  }

  function applyList(list, keepId) {
    const sig = listSignature(list);
    const same = sig === listSig;
    listSig = sig;
    photos = list;
    if (!photos.length) {
      showEmpty();
      return;
    }
    if (keepId && photos.some((p) => p.id === keepId)) {
      showPhoto(photos.findIndex((p) => p.id === keepId));
      return;
    }
    if (!same && keepId && !photos.some((p) => p.id === keepId)) {
      const next = Math.min(index, photos.length - 1);
      showPhoto(next);
      return;
    }
    if (!same) {
      showPhoto(Math.min(index, photos.length - 1));
    }
  }

  async function refreshList(full, keepId) {
    try {
      const data = await fetchList(full);
      if (data === null) {
        showEmpty();
        return;
      }
      applyList(validPhotos(data), keepId);
    } catch (_err) {
      showEmpty();
    }
  }

  function goHome() {
    window.location.href = "index.html";
  }

  function backKeys(event) {
    const k = event.key;
    if (
      k === "Escape" ||
      k === "Backspace" ||
      k === "BrowserBack" ||
      k === "GoBack" ||
      k === "Back" ||
      event.keyCode === 4 ||
      event.keyCode === 461 ||
      event.keyCode === 10009
    ) {
      event.preventDefault();
      goHome();
    }
  }

  function move(delta) {
    if (!photos.length) return;
    showPhoto(index + delta);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      move(-1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      move(1);
      return;
    }
    if (event.key === "Enter" && event.target === addBtn) {
      event.preventDefault();
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && event.target === addBtn) {
      event.preventDefault();
      return;
    }
    if (isTv() && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      const items = tvControls.filter((el) => el && !el.disabled && el.offsetParent !== null);
      const current = document.activeElement;
      let pos = items.indexOf(current);
      if (pos < 0) {
        items[0]?.focus({ preventScroll: true });
        event.preventDefault();
        return;
      }
      const next = event.key === "ArrowDown" ? Math.min(pos + 1, items.length - 1) : Math.max(pos - 1, 0);
      items[next]?.focus({ preventScroll: true });
      event.preventDefault();
      return;
    }
    backKeys(event);
  }

  async function uploadFile(file) {
    if (!file) return;
    uploadMsg.hidden = true;
    const body = new FormData();
    body.append("file", file);
    let resp;
    try {
      resp = await fetch("/gallery", { method: "POST", body });
    } catch (_err) {
      uploadMsg.textContent = "Couldn't add that.";
      uploadMsg.hidden = false;
      return;
    }
    if (resp.status === 201) {
      uploadMsg.hidden = true;
      let payload;
      try {
        payload = await resp.json();
      } catch (_err) {
        payload = null;
      }
      await refreshList(true, payload && payload.id);
      return;
    }
    uploadMsg.textContent = "Couldn't add that.";
    uploadMsg.hidden = false;
  }

  function bindUi() {
    for (const btn of [prevEdge, prevBar]) {
      btn?.addEventListener("click", () => move(-1));
    }
    for (const btn of [nextEdge, nextBar]) {
      btn?.addEventListener("click", () => move(1));
    }
    addBtn?.addEventListener("click", () => fileInput?.click());
    addBtn?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
      }
    });
    fileInput?.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      uploadFile(file);
    });
    document.addEventListener("keydown", onKeyDown);
  }

  function fitFrame() {
    if (window.SlateSurface && frame) {
      SlateSurface.fitGalleryFrame(frame);
    }
  }

  function init() {
    document.body.dataset.slateSurface = SlateSurface.applySurface() ? "tv" : "flex";
    showUploadUi();
    bindUi();
    fitFrame();
    window.addEventListener("resize", fitFrame);
    if (SlateSurface.onDrift) {
      SlateSurface.onDrift(() => fitFrame());
    }
    refreshList(true);
    setInterval(() => refreshList(true, currentId), REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
