const TZ = "America/New_York";
const DRIFT_MS = 3 * 60 * 1000;
const DRIFT = [
  [0, 0],
  [1, 1],
  [2, 0],
  [1, -1],
  [0, -2],
  [-1, -1],
  [-2, 0],
  [-1, 1],
  [0, 2],
];
const FOCUS_IDLE_MS = 15 * 1000;

const stage = document.getElementById("stage");
const hmEl = document.getElementById("clock-hm");
const secEl = document.getElementById("clock-sec");
const ampmEl = document.getElementById("clock-ampm");
const dateEl = document.getElementById("date");

const timeFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
  hour12: true,
});

const dateFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  weekday: "long",
  month: "long",
  day: "numeric",
});

function part(parts, type) {
  const found = parts.find((item) => item.type === type);
  return found ? found.value : "";
}

function renderClock() {
  const now = new Date();
  const parts = timeFormat.formatToParts(now);
  hmEl.textContent = `${part(parts, "hour")}:${part(parts, "minute")}`;
  secEl.textContent = `:${part(parts, "second")}`;
  ampmEl.textContent = part(parts, "dayPeriod");
  dateEl.textContent = dateFormat.format(now);
}

let driftIndex = 0;

function shiftTerm(px) {
  if (px === 0) return "-50%";
  const text = Number(Math.abs(px).toFixed(4)).toString();
  return px > 0 ? `calc(-50% + ${text}px)` : `calc(-50% - ${text}px)`;
}

function fitStage() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  const [x, y] = DRIFT[driftIndex];
  document.documentElement.style.setProperty("--drift-x", String(x));
  document.documentElement.style.setProperty("--drift-y", String(y));
  stage.style.transform =
    `translate(${shiftTerm(x * scale)}, ${shiftTerm(y * scale)}) scale(${scale})`;
}

function tileText(value) {
  return typeof value === "string" ? value : "";
}

function tileIcon(name) {
  return TILE_ICONS.has(name) ? name : "grid";
}

function tileUrl(url) {
  if (typeof url !== "string") return "";
  const value = url.trim();
  if (!value || value.length > 500) return "";
  if (/[\u0000-\u001f\\]/.test(value) || value.startsWith("//") || value.includes("..")) return "";
  if (/^[a-z0-9][a-z0-9._/-]*$/i.test(value)) return value;
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
  } catch (err) {
    return "";
  }
  return "";
}

function chosenText(override, fallback) {
  if (typeof override === "string" && override.trim()) return override;
  return tileText(fallback);
}

function resolveApps(entries, catalog) {
  const byId = new Map();
  if (Array.isArray(catalog)) {
    for (const item of catalog) {
      if (!item || typeof item !== "object" || typeof item.id !== "string" || !item.id) continue;
      if (!byId.has(item.id)) byId.set(item.id, item);
    }
  }
  const apps = [];
  if (!Array.isArray(entries)) return apps;
  for (const entry of entries) {
    if (apps.length >= MAX_APP_TILES) break;
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    let name = "";
    let icon = "grid";
    let url = "";
    if (typeof entry.id === "string" && entry.id) {
      const base = byId.get(entry.id);
      if (!base) continue;
      name = chosenText(entry.name, base.name);
      icon = typeof entry.icon === "string" && entry.icon ? entry.icon : tileText(base.icon);
      url = typeof entry.url === "string" ? entry.url : tileText(base.url);
    } else if (typeof entry.name === "string") {
      name = entry.name;
      icon = typeof entry.icon === "string" && entry.icon ? entry.icon : "grid";
      url = typeof entry.url === "string" ? entry.url : "";
    } else {
      continue;
    }
    name = name.replace(/\s+/g, " ").trim();
    if (!name) continue;
    apps.push({ name, icon: tileIcon(icon), url: tileUrl(url) });
  }
  return apps;
}

function homeTiles() {
  if (!document.body.classList.contains("page-home")) return [];
  const nav = document.getElementById("tiles");
  if (!nav) return [];
  return [...nav.querySelectorAll(".tile")];
}

function openTile(tile) {
  const url = tile && tile.dataset.url;
  if (url) location.href = url;
}

function renderTileList(apps) {
  const nav = document.getElementById("tiles");
  if (!nav) return [];
  const list = [{ name: "Dashboard", icon: "grid", url: "dashboard.html" }, ...apps];
  const built = [];
  nav.replaceChildren();
  for (const app of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tile focusable";
    if (app.url) button.dataset.url = app.url;
    if (!built.length) button.autofocus = true;
    const iconHolder = document.createElement("span");
    iconHolder.className = "tile-icon";
    const name = document.createElement("span");
    name.className = "nm";
    name.textContent = app.name;
    button.append(iconHolder, name);
    button.addEventListener("click", () => openTile(button));
    nav.append(button);
    built.push({ button, iconHolder, icon: app.icon });
  }
  if (!apps.length) {
    const empty = document.createElement("div");
    empty.className = "tile-empty";
    const title = document.createElement("b");
    title.textContent = "No other apps yet";
    const detail = document.createElement("span");
    detail.textContent = "Add them in apps.json";
    empty.append(title, detail);
    nav.append(empty);
  }
  const first = built[0] && built[0].button;
  if (first) first.focus({ preventScroll: true });
  return built;
}

async function paintTileIcons(built) {
  for (const tile of built) {
    const svg = await ensureIcon(tile.icon);
    if (!tile.iconHolder.isConnected) return;
    applyIcon(tile.iconHolder, tile.icon, svg);
  }
}

async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function loadTiles() {
  const nav = document.getElementById("tiles");
  if (!nav) return;
  let entries = [];
  let catalog = [];
  try {
    entries = await readJson("apps.json");
  } catch (err) {
    entries = [];
  }
  try {
    catalog = await readJson("apps-catalog.json");
  } catch (err) {
    catalog = [];
  }
  const built = renderTileList(resolveApps(entries, catalog));
  await paintTileIcons(built);
}

const BACK_KEYS = new Set(["Escape", "Backspace", "BrowserBack", "GoBack"]);
const BACK_CODES = new Set([461, 10009]);
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta"]);
let idleTimer = 0;

function onDashboard() {
  return document.body.classList.contains("page-dashboard");
}

function showFocus(on) {
  document.body.classList.toggle("show-focus", on);
}

function bumpIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => showFocus(false), FOCUS_IDLE_MS);
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if (MODIFIER_KEYS.has(event.key)) return;

  const key = event.key;
  const dash = onDashboard();

  if (key === "g" || key === "G") {
    if (dash) {
      showFocus(true);
      bumpIdle();
    }
    return;
  }

  if (BACK_KEYS.has(key) || BACK_CODES.has(event.keyCode)) {
    event.preventDefault();
    if (dash) location.href = "index.html";
    return;
  }

  const arrow = key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown";
  const select = key === "Enter";
  if (!arrow && !select) {
    showFocus(true);
    bumpIdle();
    return;
  }

  event.preventDefault();
  const wasHidden = !document.body.classList.contains("show-focus");
  showFocus(true);
  bumpIdle();
  if (wasHidden) return;

  if (dash) {
    if (select) location.href = "index.html";
    return;
  }

  const tiles = homeTiles();
  if (key === "ArrowUp" || key === "ArrowDown") return;
  if (select) {
    const active = document.activeElement;
    if (active && active.classList.contains("tile")) openTile(active);
    else if (active && typeof active.click === "function") active.click();
    return;
  }
  if (!tiles.length) return;
  let index = tiles.indexOf(document.activeElement);
  if (index < 0) index = 0;
  else if (key === "ArrowRight") index = Math.min(index + 1, tiles.length - 1);
  else index = Math.max(index - 1, 0);
  tiles[index].focus({ preventScroll: true });
});

document.addEventListener("mousemove", () => {
  document.body.classList.add("has-mouse");
}, { once: true });

if (hmEl && secEl && ampmEl && dateEl) {
  renderClock();
  setInterval(renderClock, 1000);
}

if (stage) {
  fitStage();
  setInterval(() => {
    driftIndex = (driftIndex + 1) % DRIFT.length;
    fitStage();
  }, DRIFT_MS);
  window.addEventListener("resize", fitStage);
}

if (onDashboard()) {
  const homeLink = document.querySelector("a.nav-link[href='index.html']");
  if (homeLink) homeLink.focus({ preventScroll: true });
}

const WEATHER_URL =
  "https://api.open-meteo.com/v1/forecast?latitude=40.7128&longitude=-74.0060" +
  "&current=temperature_2m,weather_code,is_day&hourly=temperature_2m,weather_code,is_day" +
  "&temperature_unit=fahrenheit&timezone=America%2FNew_York&forecast_hours=7";
const WEATHER_TICK_MS = 60 * 1000;
const WEATHER_EVERY_MS = 10 * 60 * 1000;
const WEATHER_STALE_MS = 20 * 60 * 1000;
const WEATHER_DROP_MS = 3 * 60 * 60 * 1000;
const WEATHER_CACHE_KEY = "tv-weather";
const ICON_FILES = new Set([
  "sun", "moon", "cloud", "cloudsun", "cloudmoon", "rain", "snow", "fog", "storm", "cloudoff",
  "tv", "music", "photo", "bulb", "sliders", "grid", "house", "film", "focus", "power", "mic", "speaker",
]);
const TILE_ICONS = new Set([
  "tv", "music", "photo", "bulb", "sliders", "grid", "house", "film", "focus", "power", "mic", "speaker",
]);
const MAX_APP_TILES = 5;

const iconSvg = new Map();
const wxBox = document.getElementById("wx");
const wxIcon = document.getElementById("wx-icon");
const wxTemp = document.getElementById("wx-temp");
const wxCond = document.getElementById("wx-cond");
const wxHours = document.getElementById("wx-hours");
const wxStale = document.getElementById("wx-stale");
const dwx = document.getElementById("dwx");

let wx = null;
let wxGoodAt = 0;
let wxTriedAt = 0;
let wxRenderGen = 0;
let wxLoadGen = 0;

function wallClock(date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(date);
  const value = (type) => Number(parts.find((item) => item.type === type).value);
  let hour = value("hour");
  if (hour === 24) hour = 0;
  return { year: value("year"), month: value("month"), day: value("day"), hour, minute: value("minute") };
}

function nyOffsetMinutes(date) {
  const wall = wallClock(date);
  const asUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  return Math.round((asUtc - date.getTime()) / 60000);
}

function parseNy(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso));
  if (!match) return new Date(NaN);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const naive = Date.UTC(year, month - 1, day, hour, minute);
  let utc = naive;
  for (let pass = 0; pass < 2; pass += 1) {
    utc = naive - nyOffsetMinutes(new Date(utc)) * 60000;
  }
  return new Date(utc);
}

function hmNy(date) {
  const clock = wallClock(date);
  const hour = clock.hour % 12 || 12;
  return `${hour}:${String(clock.minute).padStart(2, "0")}`;
}

function hourLabel(date) {
  const clock = wallClock(date);
  const hour = clock.hour % 12 || 12;
  return `${hour} ${clock.hour < 12 ? "AM" : "PM"}`;
}

function wmo(code, isDay) {
  if (typeof code !== "number" || !Number.isFinite(code)) return ["cloudoff", "Unknown"];
  const day = isDay === 1 || isDay === true;
  if (code === 0) return [day ? "sun" : "moon", "Clear"];
  if (code === 1) return [day ? "sun" : "moon", "Mostly clear"];
  if (code === 2) return [day ? "cloudsun" : "cloudmoon", "Partly cloudy"];
  if (code === 3) return ["cloud", "Cloudy"];
  if (code === 45 || code === 48) return ["fog", "Fog"];
  if (code >= 51 && code <= 57) return ["rain", "Drizzle"];
  if (code >= 61 && code <= 67) return ["rain", "Rain"];
  if (code >= 80 && code <= 82) return ["rain", "Showers"];
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return ["snow", "Snow"];
  if (code >= 95 && code <= 99) return ["storm", "Storms"];
  return ["cloudoff", "Unknown"];
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function weatherOk(data) {
  const current = data && data.current;
  const hourly = data && data.hourly;
  return !!(
    current &&
    finiteNumber(current.temperature_2m) &&
    finiteNumber(current.weather_code) &&
    (current.is_day === 0 || current.is_day === 1) &&
    hourly &&
    Array.isArray(hourly.time) &&
    Array.isArray(hourly.temperature_2m) &&
    Array.isArray(hourly.weather_code) &&
    Array.isArray(hourly.is_day)
  );
}

function degrees(value) {
  if (!finiteNumber(value)) return "";
  return `${Math.round(value)}°`;
}

function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

async function ensureIcon(name) {
  if (!ICON_FILES.has(name)) return "";
  if (iconSvg.has(name)) return iconSvg.get(name);
  try {
    const response = await fetch(`assets/icons/${name}.svg`);
    if (!response.ok) throw new Error(String(response.status));
    const text = await response.text();
    if (!text.includes("<svg")) throw new Error("bad icon");
    const svg = text.replace("<svg ", '<svg class="i" focusable="false" aria-hidden="true" ');
    iconSvg.set(name, svg);
    return svg;
  } catch (err) {
    iconSvg.set(name, "");
    return "";
  }
}

function applyIcon(el, name, svg) {
  if (!el) return;
  const key = svg ? name : "";
  if (el.dataset.icon === key) return;
  el.replaceChildren();
  if (!svg) {
    el.dataset.icon = "";
    return;
  }
  const holder = document.createElement("span");
  holder.innerHTML = svg;
  const icon = holder.querySelector("svg");
  if (!icon) {
    el.dataset.icon = "";
    return;
  }
  el.append(icon);
  el.dataset.icon = name;
}

function readWeatherCache() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(WEATHER_CACHE_KEY) || "null");
    if (!saved || !weatherOk(saved.wx) || !finiteNumber(saved.goodAt)) return;
    const age = Date.now() - saved.goodAt;
    if (age < -60 * 1000 || age >= WEATHER_DROP_MS) return;
    wx = saved.wx;
    wxGoodAt = saved.goodAt;
  } catch (err) {
    /* A blocked cache just means the next fetch has to succeed. */
  }
}

function writeWeatherCache() {
  try {
    sessionStorage.setItem(WEATHER_CACHE_KEY, JSON.stringify({ wx, goodAt: wxGoodAt }));
  } catch (err) {
    /* Keep the in-memory copy when storage is blocked. */
  }
}

function weatherAge(now) {
  if (!wx || !finiteNumber(wxGoodAt)) return Infinity;
  const age = now - wxGoodAt;
  if (!Number.isFinite(age) || age < -60 * 1000) return Infinity;
  return Math.max(0, age);
}

function upcomingHours(now) {
  const hourly = wx && wx.hourly;
  const out = [];
  if (!hourly) return out;
  for (let i = 0; i < hourly.time.length && out.length < 6; i += 1) {
    const temp = hourly.temperature_2m[i];
    if (!finiteNumber(temp)) continue;
    const when = parseNy(hourly.time[i]);
    if (Number.isNaN(when.getTime()) || when <= now) continue;
    out.push({
      when,
      temp,
      code: hourly.weather_code[i],
      day: hourly.is_day[i],
    });
  }
  return out;
}

function applyHours(hours, icons) {
  if (!wxHours) return;
  while (wxHours.children.length < hours.length) {
    const cell = document.createElement("div");
    cell.className = "wx-h";
    const label = document.createElement("span");
    label.className = "t";
    const icon = document.createElement("span");
    icon.className = "ic";
    const value = document.createElement("span");
    value.className = "v";
    cell.append(label, icon, value);
    wxHours.append(cell);
  }
  while (wxHours.children.length > hours.length) wxHours.lastChild.remove();
  for (let i = 0; i < hours.length; i += 1) {
    const cell = wxHours.children[i];
    const hour = hours[i];
    setText(cell.children[0], hourLabel(hour.when));
    applyIcon(cell.children[1], hour.iconName, icons[i]);
    setText(cell.children[2], degrees(hour.temp));
  }
}

function applyStale(el, message, svg) {
  if (!el || el.dataset.msg === message) return;
  el.dataset.msg = message;
  el.replaceChildren();
  if (!message) return;
  if (svg) {
    const holder = document.createElement("span");
    holder.innerHTML = svg;
    const icon = holder.querySelector("svg");
    if (icon) el.append(icon);
  }
  const text = document.createElement("span");
  text.textContent = message;
  el.append(text);
}

function applyDash(iconName, svg, label) {
  if (!dwx) return;
  if (!label) {
    if (dwx.dataset.h) {
      dwx.replaceChildren();
      dwx.dataset.h = "";
    }
    return;
  }
  const key = `${iconName}|${label}`;
  if (dwx.dataset.h === key) return;
  dwx.replaceChildren();
  if (svg) {
    const holder = document.createElement("span");
    holder.innerHTML = svg;
    const icon = holder.querySelector("svg");
    if (icon) dwx.append(icon);
  }
  const text = document.createElement("span");
  text.textContent = label;
  dwx.append(text);
  dwx.dataset.h = key;
}

async function renderWeather() {
  if (!wxBox && !dwx) return;
  const gen = ++wxRenderGen;
  const age = weatherAge(Date.now());
  const dropped = age >= WEATHER_DROP_MS;
  const stale = !dropped && age >= WEATHER_STALE_MS;
  const current = !dropped && wx ? wx.current : null;
  const temp = current ? degrees(current.temperature_2m) : "";
  const mapped = current && temp ? wmo(current.weather_code, current.is_day) : ["", ""];
  const currentIcon = mapped[0] ? await ensureIcon(mapped[0]) : "";
  if (gen !== wxRenderGen) return;

  const hours = wxBox && current && temp ? upcomingHours(new Date()) : [];
  const hourIcons = [];
  for (const hour of hours) {
    const [iconName] = wmo(hour.code, hour.day);
    hour.iconName = iconName;
    hourIcons.push(iconName ? await ensureIcon(iconName) : "");
    if (gen !== wxRenderGen) return;
  }

  const staleMessage = dropped
    ? "Weather unavailable"
    : stale
      ? `Couldn't refresh weather · Updated ${hmNy(new Date(wxGoodAt))}`
      : "";
  const staleIcon = wxBox && staleMessage ? await ensureIcon("cloudoff") : "";
  if (gen !== wxRenderGen) return;

  const dashLabel = temp ? `${temp} ${mapped[1]}`.trim() : "";
  const dashIcon = dwx && dashLabel && mapped[0] ? await ensureIcon(mapped[0]) : "";
  if (gen !== wxRenderGen) return;

  if (wxBox) {
    const unavailable = !temp;
    wxBox.classList.toggle("is-unavailable", unavailable);
    if (unavailable) {
      applyIcon(wxIcon, "", "");
      setText(wxTemp, "");
      setText(wxCond, "");
      if (wxHours) wxHours.replaceChildren();
      wxBox.classList.add("is-stale");
    } else {
      applyIcon(wxIcon, mapped[0], currentIcon);
      setText(wxTemp, temp);
      setText(wxCond, mapped[1]);
      applyHours(hours, hourIcons);
      wxBox.classList.toggle("is-stale", stale);
    }
    applyStale(wxStale, staleMessage, staleIcon);
    wxBox.style.visibility = "visible";
  }
  applyDash(mapped[0], dashIcon, dashLabel);
}

async function loadWeather() {
  if (!wxBox && !dwx) return;
  const gen = ++wxLoadGen;
  wxTriedAt = Date.now();
  try {
    const response = await fetch(WEATHER_URL, { cache: "no-store" });
    if (gen !== wxLoadGen) return;
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (gen !== wxLoadGen) return;
    if (!weatherOk(data)) throw new Error("bad weather");
    wx = data;
    wxGoodAt = Date.now();
    writeWeatherCache();
  } catch (err) {
    /* Keep the last good forecast. Never fill in a made-up temperature. */
  }
  if (gen !== wxLoadGen) return;
  await renderWeather();
}

if (wxBox || dwx) {
  readWeatherCache();
  if (wx) renderWeather();
}
if (wxBox) {
  loadWeather();
  setInterval(() => {
    if (Date.now() - wxTriedAt >= WEATHER_EVERY_MS) loadWeather();
    else renderWeather();
  }, WEATHER_TICK_MS);
} else if (dwx) {
  setInterval(renderWeather, WEATHER_TICK_MS);
}

loadTiles();
