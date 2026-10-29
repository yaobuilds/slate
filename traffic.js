const REFRESH_MS = 60 * 1000;
const MAP_ZOOM = 11;
const TILE_SIZE = 256;
const OSM_TILE = "https://tile.openstreetmap.org";

const placeEl = document.getElementById("traffic-place");
const headingEl = document.getElementById("traffic-heading");
const updatedEl = document.getElementById("traffic-updated");
const quietEl = document.getElementById("traffic-quiet");
const bodyEl = document.getElementById("traffic-body");
const mapEl = document.getElementById("traffic-map");
const tilesEl = document.getElementById("traffic-tiles");
const centerEl = document.getElementById("traffic-center");
const markersEl = document.getElementById("traffic-markers");
const listEl = document.getElementById("traffic-incident-list");
const noteEl = document.getElementById("traffic-incidents-note");
const shellEl = document.getElementById("traffic-shell");

let mapCenter = null;
let lastIncidents = [];
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
    empty.textContent = "No active incidents reported nearby.";
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

function layoutMap(lat, lon, incidents) {
  if (!mapEl || !tilesEl || !centerEl) return;
  const width = mapEl.clientWidth;
  const height = mapEl.clientHeight;
  if (!width || !height) return;

  const centerPx = project(lat, lon, MAP_ZOOM);
  centerEl.style.left = `${width / 2}px`;
  centerEl.style.top = `${height / 2}px`;

  const startTileX = Math.floor(centerPx.x / TILE_SIZE) - Math.ceil(width / TILE_SIZE / 2) - 1;
  const endTileX = Math.floor(centerPx.x / TILE_SIZE) + Math.ceil(width / TILE_SIZE / 2) + 1;
  const startTileY = Math.floor(centerPx.y / TILE_SIZE) - Math.ceil(height / TILE_SIZE / 2) - 1;
  const endTileY = Math.floor(centerPx.y / TILE_SIZE) + Math.ceil(height / TILE_SIZE / 2) + 1;

  tilesEl.innerHTML = "";
  for (let x = startTileX; x <= endTileX; x += 1) {
    for (let y = startTileY; y <= endTileY; y += 1) {
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.src = `${OSM_TILE}/${MAP_ZOOM}/${x}/${y}.png`;
      img.style.left = `${width / 2 + (x * TILE_SIZE - centerPx.x)}px`;
      img.style.top = `${height / 2 + (y * TILE_SIZE - centerPx.y)}px`;
      tilesEl.appendChild(img);
    }
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
  shellEl.style.transform =
    `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(min(100vw / 1920, 100vh / 1080))`;
}

function showNoPlace() {
  quietEl.hidden = false;
  quietEl.textContent = "No place saved.";
  bodyEl.hidden = true;
  updatedEl.textContent = "";
  headingEl.textContent = "Traffic";
  placeEl.textContent = "Location";
}

async function refreshTraffic() {
  try {
    const response = await fetch("traffic.json", { cache: "no-store" });
    if (!response.ok) throw new Error("traffic");
    const data = await response.json();
    if (!data.hasPlace) {
      showNoPlace();
      return;
    }
    quietEl.hidden = true;
    bodyEl.hidden = false;
    const place = data.place || {};
    placeEl.textContent = place.label || "Saved place";
    headingEl.textContent = "Live map";
    updatedEl.textContent = data.updated ? `Updated ${formatIncidentTime(data.updated)}` : "";
    mapCenter = { lat: place.lat, lon: place.lon };
    lastIncidents = Array.isArray(data.incidents) ? data.incidents : [];
    renderIncidents(lastIncidents, data.incidentsAvailable !== false);
    requestAnimationFrame(() => layoutMap(place.lat, place.lon, lastIncidents));
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
  document.addEventListener("keydown", (event) => {
    const back =
      ["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key) ||
      [4, 461, 10009].includes(event.keyCode);
    if (back) {
      event.preventDefault();
      location.href = "index.html";
    }
  });
}

window.addEventListener("resize", () => {
  if (mapCenter) layoutMap(mapCenter.lat, mapCenter.lon, lastIncidents);
});

installBackKeys();
refreshTraffic();
scheduleRefresh();
if (document.documentElement.dataset.slateSurface === "tv") {
  driftTimer = window.setInterval(applyDrift, 3 * 60 * 1000);
}
