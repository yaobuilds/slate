const REFRESH_MS = 60 * 1000;
const MAP_ZOOM = 11;
const TILE_SIZE = 256;
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
  if (!mapCenter) return;
  layoutMap(mapCenter.lat, mapCenter.lon, lastIncidents, lastSegments, mapTilesReady);
}

function layoutMap(lat, lon, incidents, segments, tilesReady) {
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

  const centerPx = project(lat, lon, MAP_ZOOM);
  centerEl.style.left = `${width / 2}px`;
  centerEl.style.top = `${height / 2}px`;

  const startTileX = Math.floor(centerPx.x / TILE_SIZE) - Math.ceil(width / TILE_SIZE / 2) - 1;
  const endTileX = Math.floor(centerPx.x / TILE_SIZE) + Math.ceil(width / TILE_SIZE / 2) + 1;
  const startTileY = Math.floor(centerPx.y / TILE_SIZE) - Math.ceil(height / TILE_SIZE / 2) - 1;
  const endTileY = Math.floor(centerPx.y / TILE_SIZE) + Math.ceil(height / TILE_SIZE / 2) + 1;

  const wanted = new Map();
  if (tilesReady) {
    for (let x = startTileX; x <= endTileX; x += 1) {
      for (let y = startTileY; y <= endTileY; y += 1) {
        const src = `${MAP_TILE}/${MAP_ZOOM}/${x}/${y}.png`;
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
            const xy = project(lat, lon, MAP_ZOOM);
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
    const point = project(item.lat, item.lon, MAP_ZOOM);
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
    requestAnimationFrame(paintMap);
  } catch (error) {
    if (!mapCenter) {
      showNoPlace();
      return;
    }
    noteEl.hidden = false;
    noteEl.textContent = "Could not refresh incidents. The map is still centered on your saved place.";
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(refreshTraffic, REFRESH_MS);
}

function installBackKeys() {
  const home = document.querySelector("a.traffic-back");
  if (home) home.focus({ preventScroll: true });
  document.addEventListener("keydown", (event) => {
    const back =
      ["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key) ||
      [4, 461, 10009].includes(event.keyCode);
    if (back) {
      event.preventDefault();
      location.href = "index.html";
      return;
    }
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const items = [...document.querySelectorAll("[data-tr-focus]")];
    if (!items.length || !window.SlateSurface || typeof SlateSurface.moveFocus !== "function") return;
    event.preventDefault();
    if (!items.includes(document.activeElement)) items[0].focus({ preventScroll: true });
    else SlateSurface.moveFocus(items, event.key);
  });
}

window.addEventListener("resize", paintMap);
if (window.ResizeObserver && mapEl) {
  new ResizeObserver(paintMap).observe(mapEl);
}

installBackKeys();
refreshTraffic();
ensureDetectedPlace().then((moved) => {
  if (moved) refreshTraffic();
});
scheduleRefresh();
if (document.documentElement.dataset.slateSurface === "tv") {
  driftTimer = window.setInterval(applyDrift, 3 * 60 * 1000);
}
