const REFRESH_MS = 60 * 1000;
const MAP_ZOOM_DEFAULT = 11;
const MAP_ZOOM_MIN = 9;
const MAP_ZOOM_MAX = 16;
const TILE_SIZE = 256;
const PAN_LIMIT_KM = 120;
const DRAG_START_PX = 4;
const WHEEL_ZOOM_PX = 80;
const PINCH_RATIO = 1.2;
const HOME_EPSILON = 1e-5;
// Same-origin tiles. The CARTO key stays in carto.local on the server.
const MAP_TILE = "/map";

const placeEl = document.getElementById("traffic-place");
const headingEl = document.getElementById("traffic-heading");
const updatedEl = document.getElementById("traffic-updated");
const quietEl = document.getElementById("traffic-quiet");
const bodyEl = document.getElementById("traffic-body");
const mapEl = document.getElementById("traffic-map");
const tilesEl = document.getElementById("traffic-tiles");
const centerEl = document.getElementById("traffic-center");
const markersEl = document.getElementById("traffic-markers");
const speedsEl = document.getElementById("traffic-speeds");
const listEl = document.getElementById("traffic-incident-list");
const noteEl = document.getElementById("traffic-incidents-note");
const speedsNoteEl = document.getElementById("traffic-speeds-note");
const mapNoteEl = document.getElementById("traffic-map-note");
const shellEl = document.getElementById("traffic-shell");

let mapCenter = null;
let view = null;
let mapTilesReady = false;
let lastIncidents = [];
let lastSegments = [];
let refreshTimer = 0;
let driftTimer = 0;
let driftIndex = 0;
const DRIFT = [[0, 0], [1, 0], [2, 1], [1, -1], [0, -2], [-1, -1], [-2, 0], [-1, 1]];

function lonToTileX(lon, zoom) {
  return ((lon + 180) / 360) * 2 ** zoom;
}

function latToTileY(lat, zoom) {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** zoom;
}

function project(lat, lon, zoom) {
  return {
    x: lonToTileX(lon, zoom) * TILE_SIZE,
    y: latToTileY(lat, zoom) * TILE_SIZE,
  };
}

function tileXToLon(x, zoom) {
  return (x / 2 ** zoom) * 360 - 180;
}

function tileYToLat(y, zoom) {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** zoom;
  return (180 / Math.PI) * Math.atan(Math.sinh(n));
}

function viewIsHome() {
  if (!view || !mapCenter) return true;
  if (view.zoom !== MAP_ZOOM_DEFAULT) return false;
  return Math.abs(view.lat - mapCenter.lat) <= HOME_EPSILON && Math.abs(view.lon - mapCenter.lon) <= HOME_EPSILON;
}

function clampCamera(lat, lon) {
  if (!mapCenter || !window.SlatePlace || typeof window.SlatePlace.haversineKm !== "function") {
    return { lat, lon };
  }
  const dist = window.SlatePlace.haversineKm(mapCenter.lat, mapCenter.lon, lat, lon);
  if (!Number.isFinite(dist) || dist <= PAN_LIMIT_KM) return { lat, lon };
  const scale = PAN_LIMIT_KM / dist;
  return {
    lat: mapCenter.lat + (lat - mapCenter.lat) * scale,
    lon: mapCenter.lon + (lon - mapCenter.lon) * scale,
  };
}

function commitCamera(lat, lon, zoom) {
  if (!view) return;
  const clamped = clampCamera(lat, lon);
  const nextZoom = Math.max(MAP_ZOOM_MIN, Math.min(MAP_ZOOM_MAX, Math.round(zoom)));
  if (
    Math.abs(view.lat - clamped.lat) < 1e-9 &&
    Math.abs(view.lon - clamped.lon) < 1e-9 &&
    view.zoom === nextZoom
  ) {
    return;
  }
  view.lat = clamped.lat;
  view.lon = clamped.lon;
  view.zoom = nextZoom;
  view.userMoved = true;
  paintMap();
}

function panByPixels(dx, dy) {
  if (!view) return;
  const center = project(view.lat, view.lon, view.zoom);
  commitCamera(
    tileYToLat((center.y - dy) / TILE_SIZE, view.zoom),
    tileXToLon((center.x - dx) / TILE_SIZE, view.zoom),
    view.zoom,
  );
}

function zoomToward(nextZoom, anchorX, anchorY) {
  if (!view || !mapEl) return;
  const zoom = view.zoom;
  const target = Math.max(MAP_ZOOM_MIN, Math.min(MAP_ZOOM_MAX, Math.round(nextZoom)));
  if (target === zoom) return;
  const width = mapEl.clientWidth;
  const height = mapEl.clientHeight;
  if (!width || !height) {
    commitCamera(view.lat, view.lon, target);
    return;
  }
  const center = project(view.lat, view.lon, zoom);
  const worldX = center.x + (anchorX - width / 2);
  const worldY = center.y + (anchorY - height / 2);
  const lat = tileYToLat(worldY / TILE_SIZE, zoom);
  const lon = tileXToLon(worldX / TILE_SIZE, zoom);
  const nextWorld = project(lat, lon, target);
  const nextCenterX = nextWorld.x - (anchorX - width / 2);
  const nextCenterY = nextWorld.y - (anchorY - height / 2);
  commitCamera(
    tileYToLat(nextCenterY / TILE_SIZE, target),
    tileXToLon(nextCenterX / TILE_SIZE, target),
    target,
  );
}

function zoomAtCenter(delta) {
  if (!view || !mapEl) return;
  zoomToward(view.zoom + delta, mapEl.clientWidth / 2, mapEl.clientHeight / 2);
}

function resetView() {
  if (!mapCenter) return;
  view = {
    lat: mapCenter.lat,
    lon: mapCenter.lon,
    zoom: MAP_ZOOM_DEFAULT,
    userMoved: false,
  };
  paintMap();
}

function renderCredits(sources, tomtomCredit) {
  const el = document.getElementById("traffic-attribution");
  if (!el) return;
  let extra = document.getElementById("traffic-credit-extra");
  if (!extra) {
    extra = document.createElement("span");
    extra.id = "traffic-credit-extra";
    el.appendChild(extra);
  }
  extra.replaceChildren();
  const list = Array.isArray(sources) ? sources : [];
  if (list.indexOf("md-chart") !== -1) {
    extra.append(document.createTextNode(" · "));
    const link = document.createElement("a");
    link.href = "https://chart.maryland.gov/";
    link.rel = "noopener noreferrer";
    link.textContent = "Maryland CHART (MDOT SHA)";
    extra.append(link);
  }
  if (list.indexOf("tomtom") !== -1) {
    extra.append(document.createTextNode(" · "));
    const link = document.createElement("a");
    link.href = "https://www.tomtom.com/en_gb/thirdpartyproductterms/";
    link.rel = "noopener noreferrer";
    link.textContent = tomtomCredit || "© TomTom";
    extra.append(link);
  }
}

function formatIncidentTime(raw) {
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function renderIncidents(incidents, available) {
  listEl.innerHTML = "";
  if (!available) {
    noteEl.hidden = false;
    noteEl.textContent = "Live incidents are not available here.";
    return;
  }
  noteEl.hidden = true;
  noteEl.textContent = "";
  const rows = Array.isArray(incidents) ? incidents.slice(0, 5) : [];
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.textContent = "No recent incidents reported nearby.";
    listEl.appendChild(empty);
    return;
  }
  for (const item of rows) {
    const li = document.createElement("li");
    const road = document.createElement("span");
    road.className = "tr-road";
    road.textContent = item.road || "Incident";
    const desc = document.createElement("span");
    desc.className = "tr-desc";
    desc.textContent = item.description || "";
    const time = document.createElement("span");
    time.className = "tr-time";
    time.textContent = formatIncidentTime(item.time);
    li.append(road, desc, time);
    listEl.appendChild(li);
  }
}

function renderMapNote(ready, message) {
  if (!mapNoteEl) return;
  if (ready) {
    mapNoteEl.hidden = true;
    mapNoteEl.textContent = "";
    return;
  }
  mapNoteEl.hidden = false;
  mapNoteEl.textContent = message || "Street tiles need a map key on this computer.";
}

function renderSpeedsNote(speedsAvailable) {
  if (!speedsNoteEl) return;
  if (speedsAvailable) {
    speedsNoteEl.hidden = true;
    speedsNoteEl.textContent = "";
    return;
  }
  speedsNoteEl.hidden = false;
  speedsNoteEl.textContent = "Live speeds are not available here.";
}

function paintMap() {
  if (!view) return;
  layoutMap(view.lat, view.lon, view.zoom, lastIncidents, lastSegments, mapTilesReady);
}

function layoutMap(lat, lon, zoom, incidents, segments, tilesReady) {
  if (!mapEl || !tilesEl || !centerEl) return;
  const width = mapEl.clientWidth;
  const height = mapEl.clientHeight;
  // The first frame can run before the map has a box. Wait for the next one.
  if (!width || !height) {
    if (!layoutMap.waiting) {
      layoutMap.waiting = true;
      requestAnimationFrame(() => {
        layoutMap.waiting = false;
        paintMap();
      });
    }
    return;
  }

  const centerPx = project(lat, lon, zoom);
  const saved = mapCenter || { lat, lon };
  const dot = project(saved.lat, saved.lon, zoom);
  centerEl.style.left = `${width / 2 + (dot.x - centerPx.x)}px`;
  centerEl.style.top = `${height / 2 + (dot.y - centerPx.y)}px`;

  const startTileX = Math.floor(centerPx.x / TILE_SIZE) - Math.ceil(width / TILE_SIZE / 2) - 1;
  const endTileX = Math.floor(centerPx.x / TILE_SIZE) + Math.ceil(width / TILE_SIZE / 2) + 1;
  const startTileY = Math.floor(centerPx.y / TILE_SIZE) - Math.ceil(height / TILE_SIZE / 2) - 1;
  const endTileY = Math.floor(centerPx.y / TILE_SIZE) + Math.ceil(height / TILE_SIZE / 2) + 1;

  const wanted = new Map();
  if (tilesReady) {
    for (let x = startTileX; x <= endTileX; x += 1) {
      for (let y = startTileY; y <= endTileY; y += 1) {
        const src = `${MAP_TILE}/${zoom}/${x}/${y}.png`;
        wanted.set(src, {
          left: `${width / 2 + (x * TILE_SIZE - centerPx.x)}px`,
          top: `${height / 2 + (y * TILE_SIZE - centerPx.y)}px`,
        });
      }
    }
  }
  for (const img of [...tilesEl.querySelectorAll("img")]) {
    const place = wanted.get(img.getAttribute("src") || "");
    if (!place) {
      img.remove();
      continue;
    }
    img.style.left = place.left;
    img.style.top = place.top;
    wanted.delete(img.getAttribute("src") || "");
  }
  for (const [src, place] of wanted) {
    const img = document.createElement("img");
    img.alt = "";
    img.decoding = "async";
    img.src = src;
    img.style.left = place.left;
    img.style.top = place.top;
    img.addEventListener("load", () => {
      img.dataset.ok = "1";
      renderMapNote(true);
    });
    img.addEventListener("error", () => {
      if (!tilesEl.querySelector("img[data-ok]")) {
        renderMapNote(false, "Street tiles did not load.");
      }
    });
    tilesEl.appendChild(img);
  }

  if (speedsEl) {
    speedsEl.innerHTML = "";
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "traffic-speed-svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    const speedRows = Array.isArray(segments) ? segments : [];
    for (const item of speedRows) {
      const level = item.level;
      if (level !== "green" && level !== "yellow" && level !== "red") continue;
      const points = Array.isArray(item.points) ? item.points : [];
      if (points.length < 2) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      line.setAttribute("class", `speed-line level-${level}`);
      line.setAttribute(
        "points",
        points
          .map((pair) => {
            const lat = Number(pair[0]);
            const lon = Number(pair[1]);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "";
            const xy = project(lat, lon, zoom);
            return `${width / 2 + (xy.x - centerPx.x)},${height / 2 + (xy.y - centerPx.y)}`;
          })
          .filter(Boolean)
          .join(" "),
      );
      svg.appendChild(line);
    }
    speedsEl.appendChild(svg);
  }

  markersEl.innerHTML = "";
  if (!Array.isArray(incidents)) return;
  for (const item of incidents) {
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) continue;
    const point = project(item.lat, item.lon, zoom);
    const marker = document.createElement("span");
    marker.className = "traffic-marker";
    marker.style.left = `${width / 2 + (point.x - centerPx.x)}px`;
    marker.style.top = `${height / 2 + (point.y - centerPx.y)}px`;
    markersEl.appendChild(marker);
  }
}

function applyDrift() {
  if (!shellEl || document.documentElement.dataset.slateSurface !== "tv") return;
  const [dx, dy] = DRIFT[driftIndex % DRIFT.length];
  driftIndex += 1;
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  shellEl.style.transform =
    `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${scale})`;
}

function showNoPlace() {
  quietEl.hidden = false;
  quietEl.textContent = "No place saved.";
  bodyEl.hidden = true;
  updatedEl.textContent = "";
  headingEl.textContent = "Traffic";
  placeEl.textContent = "Location";
  renderCredits(null, "");
}

function detectHere() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          lat: Math.round(pos.coords.latitude * 100) / 100,
          lon: Math.round(pos.coords.longitude * 100) / 100,
        });
      },
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 4000, maximumAge: 10 * 60 * 1000 },
    );
  });
}

let placePromise = null;

function ensureDetectedPlace() {
  // Do not block the first paint on GPS. A permission prompt can sit there for a long time.
  if (!placePromise) placePromise = detectAndStore();
  return placePromise;
}

async function detectAndStore() {
  const surface = document.documentElement.dataset.slateSurface;
  if (surface === "tv" || window.SlateTV || !window.SlatePlace) return false;
  const before = window.SlatePlace.readDevicePlace();
  try {
    const settings = await fetch("settings.json", { cache: "no-store" });
    if (settings.ok) {
      const body = await settings.json();
      if (body.location && body.location.locked === true) return false;
    }
  } catch (err) {
    /* An unread settings file still allows a device fix. */
  }
  const detected = await detectHere();
  if (!detected) return false;
  let label = `${detected.lat.toFixed(2)}, ${detected.lon.toFixed(2)}`;
  try {
    const named = await fetch(
      "place.json?lat=" + encodeURIComponent(String(detected.lat)) +
        "&lon=" + encodeURIComponent(String(detected.lon)),
      { cache: "no-store" },
    );
    if (named.ok) {
      const body = await named.json();
      if (typeof body.label === "string" && body.label.trim()) label = body.label.trim();
    }
  } catch (err) {
    /* Coordinates are enough to center the map. */
  }
  window.SlatePlace.writeDevicePlace({ ...detected, label });
  if (!before) return true;
  return Math.abs(before.lat - detected.lat) > 0.009 || Math.abs(before.lon - detected.lon) > 0.009;
}

async function refreshTraffic() {
  try {
    const trafficUrl =
      window.SlatePlace && typeof window.SlatePlace.trafficJsonUrl === "function"
        ? window.SlatePlace.trafficJsonUrl()
        : "traffic.json";
    const response = await fetch(trafficUrl, { cache: "no-store" });
    if (!response.ok) throw new Error("traffic");
    const data = await response.json();
    if (!data.hasPlace) {
      showNoPlace();
      return;
    }
    quietEl.hidden = true;
    bodyEl.hidden = false;
    const place = data.place || {};
    const device =
      window.SlatePlace && typeof window.SlatePlace.readDevicePlace === "function"
        ? window.SlatePlace.readDevicePlace()
        : null;
    placeEl.textContent =
      (device && device.label) || place.label || "Saved place";
    headingEl.textContent = "Live map";
    updatedEl.textContent = data.updated ? `Updated ${formatIncidentTime(data.updated)}` : "";
    mapCenter = { lat: place.lat, lon: place.lon };
    lastIncidents = Array.isArray(data.incidents) ? data.incidents : [];
    lastSegments = Array.isArray(data.segments) ? data.segments : [];
    renderIncidents(lastIncidents, data.incidentsAvailable !== false);
    renderSpeedsNote(data.speedsAvailable === true);
    mapTilesReady = data.mapReady === true;
    renderMapNote(mapTilesReady);
    renderCredits(data.sources, data.tomtomCredit);
    if (!view || view.userMoved !== true) {
      view = {
        lat: mapCenter.lat,
        lon: mapCenter.lon,
        zoom: MAP_ZOOM_DEFAULT,
        userMoved: false,
      };
    }
    requestAnimationFrame(paintMap);
  } catch (error) {
    if (!mapCenter) {
      showNoPlace();
      return;
    }
    noteEl.hidden = false;
    noteEl.textContent = "Could not refresh incidents.";
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(refreshTraffic, REFRESH_MS);
}

function mapFocused() {
  return document.activeElement === mapEl;
}

function panByArrow(key) {
  if (!mapEl) return;
  const width = mapEl.clientWidth;
  const height = mapEl.clientHeight;
  if (!width || !height) return;
  if (key === "ArrowLeft") panByPixels(width * 0.25, 0);
  else if (key === "ArrowRight") panByPixels(-width * 0.25, 0);
  else if (key === "ArrowUp") panByPixels(0, height * 0.25);
  else if (key === "ArrowDown") panByPixels(0, -height * 0.25);
}

function installBackKeys() {
  const home = document.querySelector("a.traffic-back");
  if (home) home.focus({ preventScroll: true });
  window.SlatePage = {
    consumeHome(event) {
      if (!mapFocused() || viewIsHome()) return false;
      event.preventDefault();
      resetView();
      return true;
    },
  };
  document.addEventListener("keydown", (event) => {
    const back =
      ["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key) ||
      [4, 461, 10009].includes(event.keyCode);
    if (back) {
      event.preventDefault();
      if (mapFocused() && !viewIsHome()) {
        resetView();
        return;
      }
      location.href = "index.html";
      return;
    }
    if (mapFocused() && (event.key === "+" || event.key === "=")) {
      event.preventDefault();
      zoomAtCenter(1);
      return;
    }
    if (mapFocused() && (event.key === "-" || event.key === "−")) {
      event.preventDefault();
      zoomAtCenter(-1);
      return;
    }
    if (mapFocused() && event.key === "Enter") {
      event.preventDefault();
      zoomAtCenter(1);
      return;
    }
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    if (mapFocused() && !viewIsHome()) {
      event.preventDefault();
      panByArrow(event.key);
      return;
    }
    const items = [...document.querySelectorAll("[data-tr-focus]")];
    if (!items.length || !window.SlateSurface || typeof SlateSurface.moveFocus !== "function") return;
    event.preventDefault();
    if (!items.includes(document.activeElement)) items[0].focus({ preventScroll: true });
    else SlateSurface.moveFocus(items, event.key);
  });
}

function localPoint(clientX, clientY) {
  const rect = mapEl.getBoundingClientRect();
  const width = mapEl.clientWidth || rect.width || 1;
  const height = mapEl.clientHeight || rect.height || 1;
  const sx = rect.width ? width / rect.width : 1;
  const sy = rect.height ? height / rect.height : 1;
  return {
    x: (clientX - rect.left) * sx,
    y: (clientY - rect.top) * sy,
  };
}

function installMapGestures() {
  if (!mapEl) return;
  const pointers = new Map();
  let drag = null;
  let pinchBase = 0;
  let wheelBucket = 0;
  const zoomIn = document.getElementById("traffic-zoom-in");
  const zoomOut = document.getElementById("traffic-zoom-out");
  if (zoomIn) zoomIn.addEventListener("click", () => zoomAtCenter(1));
  if (zoomOut) zoomOut.addEventListener("click", () => zoomAtCenter(-1));

  function pinchDistance() {
    const pts = [...pointers.values()];
    if (pts.length < 2) return 0;
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  }

  function pinchMid() {
    const pts = [...pointers.values()];
    return { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
  }

  mapEl.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const point = localPoint(event.clientX, event.clientY);
    pointers.set(event.pointerId, point);
    mapEl.focus({ preventScroll: true });
    if (pointers.size === 1) {
      drag = {
        id: event.pointerId,
        lastX: event.clientX,
        lastY: event.clientY,
        originX: event.clientX,
        originY: event.clientY,
        panning: false,
      };
      pinchBase = 0;
      try {
        mapEl.setPointerCapture(event.pointerId);
      } catch (err) {
        /* Capture can fail if the pointer already ended. */
      }
      return;
    }
    drag = null;
    if (pointers.size === 2) pinchBase = pinchDistance();
  });

  mapEl.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, localPoint(event.clientX, event.clientY));
    if (pointers.size >= 2 && pinchBase > 0) {
      const dist = pinchDistance();
      const mid = pinchMid();
      if (dist / pinchBase >= PINCH_RATIO) {
        zoomToward(view ? view.zoom + 1 : MAP_ZOOM_DEFAULT, mid.x, mid.y);
        pinchBase = dist;
      } else if (dist / pinchBase <= 1 / PINCH_RATIO) {
        zoomToward(view ? view.zoom - 1 : MAP_ZOOM_DEFAULT, mid.x, mid.y);
        pinchBase = dist;
      }
      return;
    }
    if (!drag || drag.id !== event.pointerId) return;
    const moved = Math.hypot(event.clientX - drag.originX, event.clientY - drag.originY);
    if (!drag.panning && moved < DRAG_START_PX) return;
    drag.panning = true;
    const rect = mapEl.getBoundingClientRect();
    const sx = rect.width ? mapEl.clientWidth / rect.width : 1;
    const sy = rect.height ? mapEl.clientHeight / rect.height : 1;
    const dx = (event.clientX - drag.lastX) * sx;
    const dy = (event.clientY - drag.lastY) * sy;
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
    panByPixels(dx, dy);
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (drag && drag.id === event.pointerId) drag = null;
    if (pointers.size < 2) pinchBase = 0;
  }

  mapEl.addEventListener("pointerup", endPointer);
  mapEl.addEventListener("pointercancel", endPointer);

  mapEl.addEventListener("wheel", (event) => {
    event.preventDefault();
    const point = localPoint(event.clientX, event.clientY);
    wheelBucket += event.deltaY;
    while (wheelBucket >= WHEEL_ZOOM_PX) {
      wheelBucket -= WHEEL_ZOOM_PX;
      zoomToward(view ? view.zoom - 1 : MAP_ZOOM_DEFAULT, point.x, point.y);
    }
    while (wheelBucket <= -WHEEL_ZOOM_PX) {
      wheelBucket += WHEEL_ZOOM_PX;
      zoomToward(view ? view.zoom + 1 : MAP_ZOOM_DEFAULT, point.x, point.y);
    }
  }, { passive: false });
}

window.addEventListener("resize", paintMap);
if (window.ResizeObserver && mapEl) {
  new ResizeObserver(paintMap).observe(mapEl);
}

installBackKeys();
installMapGestures();
refreshTraffic();
ensureDetectedPlace().then((moved) => {
  if (moved) refreshTraffic();
});
scheduleRefresh();
if (document.documentElement.dataset.slateSurface === "tv") {
  driftTimer = window.setInterval(applyDrift, 3 * 60 * 1000);
}
