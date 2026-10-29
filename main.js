const FALLBACK_LOCATION = {
  lat: 40.7128,
  lon: -74.0060,
  label: "New York, NY",
  timezone: "America/New_York",
  locked: false,
};
let activeLocation = { ...FALLBACK_LOCATION };
let activeTimeZone = FALLBACK_LOCATION.timezone;

const DRIFT_MS = 2 * 60 * 1000;
const DRIFT = [
  [0, 0],
  [1, 0],
  [2, 1],
  [2, 0],
  [1, -1],
  [0, -2],
  [-1, -2],
  [-2, -1],
  [-2, 0],
  [-1, 1],
  [0, 2],
  [1, 2],
  [2, 2],
  [1, 1],
  [-1, -1],
  [-2, -2],
];
const FOCUS_IDLE_MS = 15 * 1000;

const stage = document.getElementById("stage");
const hmEl = document.getElementById("clock-hm");
const ampmEl = document.getElementById("clock-ampm");
const dateEl = document.getElementById("date");
const dashDateEl = document.getElementById("dash-date");
const dashClockEl = document.getElementById("dash-clock");

let timeFormat = makeTimeFormat(activeTimeZone);
let dateFormat = makeDateFormat(activeTimeZone);

function makeTimeFormat(tz) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function makeDateFormat(tz) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function setActiveTimeZone(tz) {
  if (typeof tz !== "string" || !tz.includes("/")) return;
  if (tz === activeTimeZone) return;
  activeTimeZone = tz;
  timeFormat = makeTimeFormat(activeTimeZone);
  dateFormat = makeDateFormat(activeTimeZone);
  window.slateTimezone = activeTimeZone;
  try {
    document.dispatchEvent(new CustomEvent("slate:timezone", { detail: { timezone: activeTimeZone } }));
  } catch (err) {
    /* old browser */
  }
  tickTime();
}

window.slateTimezone = activeTimeZone;

function updateSlateInputFocus() {
  const active = document.activeElement;
  const focused = !!(
    active && active.matches && active.matches("input, textarea, select, [contenteditable='true']")
  );
  const bridge = window.SlateTV;
  if (bridge && typeof bridge.setInputFocused === "function") {
    bridge.setInputFocused(focused);
  }
}

document.addEventListener("focusin", updateSlateInputFocus);
document.addEventListener("focusout", () => setTimeout(updateSlateInputFocus, 0));

function part(parts, type) {
  const found = parts.find((item) => item.type === type);
  return found ? found.value : "";
}

function renderClock(now) {
  const parts = timeFormat.formatToParts(now);
  const hm = `${part(parts, "hour")}:${part(parts, "minute")}`;
  const ampm = part(parts, "dayPeriod");
  const dateText = dateFormat.format(now);
  if (hmEl) hmEl.textContent = hm;
  if (ampmEl) ampmEl.textContent = ampm;
  if (dateEl) dateEl.textContent = dateText;
  if (dashDateEl) dashDateEl.textContent = dateText;
  if (dashClockEl) dashClockEl.textContent = `${hm} ${ampm}`;
}

function applyNight(now) {
  document.documentElement.classList.toggle("night", wallClock(now).hour < 6);
}

function tickTime() {
  const now = new Date();
  applyNight(now);
  renderClock(now);
}

function scheduleMinuteClock() {
  tickTime();
  const now = new Date();
  const ms = (60 - now.getSeconds()) * 1000 - now.getMilliseconds();
  setTimeout(() => {
    scheduleMinuteClock();
  }, Math.max(100, ms));
}

let driftIndex = 0;

function shiftTerm(px) {
  if (px === 0) return "-50%";
  const text = Number(Math.abs(px).toFixed(4)).toString();
  return px > 0 ? `calc(-50% + ${text}px)` : `calc(-50% - ${text}px)`;
}

const TV_LAYOUT = window.matchMedia("(min-width: 960px) and (min-height: 540px) and (min-aspect-ratio: 16/9)");
const USE_TV_FRAME = true;

function fitStage() {
  if (!stage) return;
  const [x, y] = DRIFT[driftIndex];
  document.documentElement.style.setProperty("--drift-x", String(x));
  document.documentElement.style.setProperty("--drift-y", String(y));
  const tvSurface = document.documentElement.dataset.slateSurface === "tv";
  if (USE_TV_FRAME && TV_LAYOUT.matches && tvSurface) {
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    document.documentElement.dataset.layout = "tv";
    stage.style.transform =
      `translate(${shiftTerm(x * scale)}, ${shiftTerm(y * scale)}) scale(${scale})`;
    return;
  }
  const phone = window.matchMedia("(max-width: 759px), (max-height: 500px) and (orientation: landscape)").matches;
  document.documentElement.dataset.layout = phone ? "phone" : "laptop";
  stage.style.transform = `translate(${x}px, ${y}px)`;
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
  if (/^slate:\/\/[a-z0-9][a-z0-9-]*$/i.test(value)) return value;
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
  } catch (err) {
    return "";
  }
  return "";
}

function onAndroidTv() {
  if (window.SlateTV) return true;
  return /Android TV|Google TV/i.test(navigator.userAgent || "");
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
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    let id = "";
    let name = "";
    let icon = "grid";
    let url = "";
    if (typeof entry.id === "string" && entry.id) {
      const base = byId.get(entry.id);
      if (!base) continue;
      id = entry.id;
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
    const resolved = tileUrl(url);
    if (resolved.startsWith("slate://") && !onAndroidTv()) continue;
    apps.push({ id, name, icon: tileIcon(icon), url: resolved });
  }
  return apps;
}

function homeTiles() {
  if (!document.body.classList.contains("page-home")) return [];
  const nav = document.getElementById("tiles");
  if (!nav) return [];
  return [...nav.querySelectorAll(".tile")].filter(el => !el.hidden);
}

function homeFocusable(el) {
  if (!el || !el.isConnected || el.hidden) return false;
  if (el.id === "wx" && Number(el.tabIndex) >= 0) return true;
  const style = getComputedStyle(el);
  if (style.display === "none") return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function homeFocusables() {
  const list = homeTiles();
  document.querySelectorAll(".foot-end .foot-link").forEach((el) => {
    if (!list.includes(el)) list.push(el);
  });
  const credit = document.getElementById("site-credit");
  if (credit && !credit.hidden && Number(credit.tabIndex) >= 0 && !list.includes(credit)) list.push(credit);
  const weather = document.getElementById("wx");
  if (weather && Number(weather.tabIndex) >= 0 && !list.includes(weather)) list.push(weather);
  return list.filter(homeFocusable);
}

function moveHomeFocus(key) {
  moveDirectionalFocus(homeFocusables(), key);
}

function dashboardFocusables() {
  return [...document.querySelectorAll(
    ".home-pill[href], #guest-toggle, .calendar-panel-link[data-focus], .dash-foot .foot-link[href]",
  )].filter((el) => el && el.offsetParent !== null && !el.disabled);
}

function moveDashboardFocus(key) {
  moveDirectionalFocus(dashboardFocusables(), key);
}

function moveDirectionalFocus(items, key) {
  if (!items.length) return;
  let current = document.activeElement;
  if (!items.includes(current)) {
    items[0].focus({ preventScroll: true });
    return;
  }
  const cr = current.getBoundingClientRect();
  const cx = cr.left + cr.width / 2;
  const cy = cr.top + cr.height / 2;
  let best = null;
  let bestScore = Infinity;
  for (const el of items) {
    if (el === current) continue;
    const r = el.getBoundingClientRect();
    const dx = r.left + r.width / 2 - cx;
    const dy = r.top + r.height / 2 - cy;
    if (key === "ArrowLeft" && dx >= -8) continue;
    if (key === "ArrowRight" && dx <= 8) continue;
    if (key === "ArrowUp" && dy >= -8) continue;
    if (key === "ArrowDown" && dy <= 8) continue;
    const primary = key === "ArrowLeft" || key === "ArrowRight" ? Math.abs(dx) : Math.abs(dy);
    const secondary = key === "ArrowLeft" || key === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
    const score = primary * 1000 + secondary;
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (best) {
    best.focus({ preventScroll: true });
    best.scrollIntoView({ block: "nearest", inline: "nearest" });
    return;
  }
  const order = items.indexOf(current);
  if (order === -1) return;
  const step = key === "ArrowLeft" || key === "ArrowUp" ? -1 : 1;
  const next = items[order + step];
  if (next) {
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

let pendingTvLaunch = null;

function tvFallbackPanel() {
  return document.getElementById("tv-app-fallback");
}

function closeTvFallback() {
  const panel = tvFallbackPanel();
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  const tile = pendingTvLaunch && pendingTvLaunch.tile;
  pendingTvLaunch = null;
  if (tile && tile.isConnected) tile.focus({ preventScroll: true });
}

function showTvFallback() {
  const panel = tvFallbackPanel();
  if (!panel || !pendingTvLaunch) return;
  const message = document.getElementById("tv-app-fallback-message");
  if (message) message.textContent = `${pendingTvLaunch.name} isn't available on this TV.`;
  panel.hidden = false;
  const webButton = document.getElementById("tv-app-open-web");
  if (webButton) webButton.focus({ preventScroll: true });
}

window.addEventListener("slate:native-app-unavailable", showTvFallback);

const tvAppOpenWeb = document.getElementById("tv-app-open-web");
if (tvAppOpenWeb) {
  tvAppOpenWeb.addEventListener("click", () => {
    const pending = pendingTvLaunch;
    if (!pending) return;
    pendingTvLaunch = null;
    const panel = tvFallbackPanel();
    if (panel) panel.hidden = true;
    location.href = pending.url;
  });
}

const tvAppGoBack = document.getElementById("tv-app-go-back");
if (tvAppGoBack) tvAppGoBack.addEventListener("click", closeTvFallback);

function openTile(tile) {
  const url = tile && tile.dataset.url;
  if (!url) return;
  if (url === "dashboard.html") {
    location.href = url;
    return;
  }
  if (url.startsWith("slate://")) {
    if (url.startsWith("slate://google-tv")) {
      const bridge = window.SlateTV;
      if (bridge && typeof bridge.openGoogleTvHome === "function") {
        bridge.openGoogleTvHome();
        return;
      }
    }
    location.href = url;
    return;
  }
  const appId = tile.dataset.appId || "";
  if (window.SlateTV && TV_NATIVE_APP_IDS.has(appId)) {
      const name = tile.querySelector(".nm");
      pendingTvLaunch = {
        id: appId,
        name: name ? name.textContent : "App",
        url,
        tile,
      };
      location.href = `slate://app/${encodeURIComponent(appId)}`;
      return;
  }
  if (window.SlateTV || document.documentElement.dataset.layout === "tv") {
    // The TV WebView is a single surface; keep its history so remote Back returns Home.
    location.href = url;
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function renderTileList(apps) {
  const nav = document.getElementById("tiles");
  if (!nav) return [];
  const list = [{ id: "", name: "Dashboard", icon: "grid", url: "dashboard.html" }, ...apps];
  nav.classList.toggle("tiles-many", list.length > 5);
  nav.classList.toggle("tiles-dense", list.length > 12);
  const built = [];
  nav.replaceChildren();
  for (const app of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tile focusable";
    if (app.url) button.dataset.url = app.url;
    if (app.id) button.dataset.appId = app.id;
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
    detail.textContent = "Choose them in Settings";
    empty.append(title, detail);
    nav.append(empty);
  }
  const first = built[0] && built[0].button;
  if (first) first.focus({ preventScroll: true });
  document.dispatchEvent(new Event("slate:tiles"));
  performance.mark("slate-tiles-ready");
  return built;
}

async function paintTileIcons(built) {
  await Promise.all(built.map(async (tile) => {
    let icon = onAndroidTv() ? TV_BRAND_ICONS[tile.button.dataset.appId] || tile.icon : tile.icon;
    let svg = await ensureIcon(icon);
    if (icon !== tile.icon && svg === ICON_FALLBACK) {
      icon = tile.icon;
      svg = await ensureIcon(icon);
    }
    if (!tile.iconHolder.isConnected) return;
    applyIcon(tile.iconHolder, icon, svg);
  }));
}

async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function homeSettings() {
  if (!window.slateSettingsPromise) window.slateSettingsPromise = readJson("settings.json");
  return window.slateSettingsPromise;
}

async function loadTiles() {
  const nav = document.getElementById("tiles");
  if (!nav) return;
  const results = await Promise.allSettled([readJson("apps.json"), readJson("apps-catalog.json"), homeSettings()]);
  const entries = results[0].status === "fulfilled" ? results[0].value : [];
  const catalog = results[1].status === "fulfilled" ? results[1].value : [];
  const settings = results[2].status === "fulfilled" ? results[2].value : {};
  document.body.dataset.tileSize = settings.tileSize === "large" ? "large" : "auto";
  window.slateHomeSettings = settings;
  document.dispatchEvent(new CustomEvent("slate:appearance", { detail: settings }));
  const built = renderTileList(resolveApps(entries, catalog));
  await paintTileIcons(built);
}

const BACK_KEYS = new Set(["Escape", "Backspace", "BrowserBack", "GoBack", "Back"]);
const BACK_CODES = new Set([4, 461, 10009]);
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta"]);
let idleTimer = 0;

function onDashboard() {
  return document.body.classList.contains("page-dashboard");
}

function isBackKey(event) {
  if (BACK_KEYS.has(event.key) || BACK_CODES.has(event.keyCode)) return true;
  return false;
}

function goHome() {
  location.href = "index.html";
}

function dashboardBackAction(fromPopState) {
  const pinForm = document.getElementById("pin-form");
  const pinInput = document.getElementById("pin-input");
  const pinError = document.getElementById("pin-error");
  if (pinForm && !pinForm.hidden) {
    pinForm.hidden = true;
    if (pinError) pinError.textContent = "";
    if (pinInput) pinInput.blur();
    if (fromPopState) {
      try {
        history.pushState({ slate: "dashboard" }, "", location.href);
      } catch (err) {
        /* History may be unavailable in some embeds. */
      }
    }
    return;
  }
  goHome();
}

function installDashboardBack() {
  if (!onDashboard()) return;
  try {
    history.pushState({ slate: "dashboard" }, "", location.href);
  } catch (err) {
    /* History may be unavailable in some embeds. */
  }
  window.addEventListener("popstate", () => {
    if (!onDashboard()) return;
    dashboardBackAction(true);
  });
  const bridge = window.SlateTV;
  if (bridge && typeof bridge === "object") {
    bridge.goHome = goHome;
    bridge.onBackPressed = dashboardBackAction;
  }
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
  if (MODIFIER_KEYS.has(event.key)) return;

  const key = event.key;
  const dash = onDashboard();

  if (isBackKey(event)) {
    event.preventDefault();
    if (!dash && tvFallbackPanel() && !tvFallbackPanel().hidden) closeTvFallback();
    else if (dash) dashboardBackAction();
    return;
  }

  const fallbackPanel = tvFallbackPanel();
  if (!dash && fallbackPanel && !fallbackPanel.hidden) {
    const webButton = document.getElementById("tv-app-open-web");
    const backButton = document.getElementById("tv-app-go-back");
    if (key === "ArrowLeft" || key === "ArrowRight") {
      event.preventDefault();
      if (document.activeElement === webButton && backButton) backButton.focus({ preventScroll: true });
      else if (webButton) webButton.focus({ preventScroll: true });
    } else if (key === "Enter") {
      event.preventDefault();
      if (document.activeElement && typeof document.activeElement.click === "function") {
        document.activeElement.click();
      }
    }
    return;
  }

  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;

  if (key === "g" || key === "G") {
    if (dash) {
      showFocus(true);
      bumpIdle();
    }
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
  showFocus(true);
  bumpIdle();

  if (dash) {
    if (select) {
      const active = document.activeElement;
      if (active && typeof active.click === "function") active.click();
      else goHome();
      return;
    }
    if (arrow) moveDashboardFocus(key);
    return;
  }

  if (select) {
    const active = document.activeElement;
    if (active && active.id === "wx") {
      location.href = "weather.html";
      return;
    }
    if (active && active.classList.contains("tile")) openTile(active);
    else if (active && typeof active.click === "function") active.click();
    return;
  }
  moveHomeFocus(key);
});

document.addEventListener("mousemove", () => {
  if (document.body.classList.contains("hide-pointer")) return;
  document.body.classList.add("has-mouse");
});

scheduleMinuteClock();

if (stage) {
  fitStage();
  setInterval(() => {
    driftIndex = (driftIndex + 1) % DRIFT.length;
    fitStage();
  }, DRIFT_MS);
  window.addEventListener("resize", fitStage);
  if (TV_LAYOUT.addEventListener) TV_LAYOUT.addEventListener("change", fitStage);
}

function weatherUrl() {
  const lat = activeLocation.lat;
  const lon = activeLocation.lon;
  return (
    "https://api.open-meteo.com/v1/forecast?latitude=" + encodeURIComponent(String(lat)) +
    "&longitude=" + encodeURIComponent(String(lon)) +
    "&current=temperature_2m,weather_code,is_day&hourly=temperature_2m,weather_code,is_day" +
    "&temperature_unit=fahrenheit&timezone=auto&forecast_hours=7"
  );
}
const WEATHER_TICK_MS = 60 * 1000;
const WEATHER_EVERY_MS = 10 * 60 * 1000;
const WEATHER_STALE_MS = 20 * 60 * 1000;
const WEATHER_DROP_MS = 3 * 60 * 60 * 1000;
const WEATHER_CACHE_KEY = "tv-weather";
const ICON_FILES = new Set([
  "sun", "moon", "cloud", "cloudsun", "cloudmoon", "rain", "snow", "fog", "storm", "cloudoff",
  "tv", "music", "photo", "bulb", "sliders", "grid", "house", "film", "focus", "power", "mic", "speaker", "eyeoff",
  "brand-netflix", "brand-youtube", "brand-youtubemusic", "brand-googletv",
]);
const TILE_ICONS = new Set([
  "tv", "music", "photo", "bulb", "sliders", "grid", "house", "film", "focus", "power", "mic", "speaker",
]);
const TV_NATIVE_APP_IDS = new Set([
  "netflix", "hulu", "hbo", "youtube", "youtube-music", "disney-plus",
  "prime-video", "apple-tv", "spotify", "youtube-tv", "sling-tv",
]);
const TV_BRAND_ICONS = {
  netflix: "brand-netflix", youtube: "brand-youtube",
  "youtube-music": "brand-youtubemusic", "google-tv": "brand-googletv",
};
const iconSvg = new Map();
const ICON_FALLBACK = '<svg class="i" focusable="false" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 16.2a4.5 4.5 0 0 0-.9-8.9A6.2 6.2 0 0 0 7.3 6a4.8 4.8 0 0 0-1 9.9H20Z"/><path d="m4 21 16-18"/></svg>';
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
    timeZone: activeTimeZone,
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
    Array.isArray(hourly.is_day) &&
    hourly.time.length === hourly.temperature_2m.length &&
    hourly.time.length === hourly.weather_code.length &&
    hourly.time.length === hourly.is_day.length
  );
}

function degrees(value) {
  if (!finiteNumber(value)) return "";
  return `${Math.round(value)}°`;
}

function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

function localSvg(text) {
  /* Icons are chosen from ICON_FILES and loaded from assets/icons only. */
  if (typeof text !== "string" || !text.includes("<svg") || text.length > 20000) return "";
  const lower = text.toLowerCase();
  if (lower.includes("<script") || lower.includes("foreignobject") || lower.includes("javascript:") || /on[a-z]+\s*=/.test(lower)) {
    return "";
  }
  return text.replace("<svg ", '<svg class="i" focusable="false" aria-hidden="true" ');
}

async function fetchIcon(name) {
  const response = await fetch(`assets/icons/${name}.svg`);
  if (!response.ok) throw new Error(String(response.status));
  const svg = localSvg(await response.text());
  if (!svg) throw new Error("bad icon");
  return svg;
}

function ensureIcon(name) {
  if (!ICON_FILES.has(name)) return Promise.resolve("");
  if (iconSvg.has(name)) return iconSvg.get(name);
  let pending;
  pending = fetchIcon(name).catch(() => {
    if (iconSvg.get(name) === pending) iconSvg.delete(name);
    return ICON_FALLBACK;
  });
  iconSvg.set(name, pending);
  return pending;
}

function applyIcon(el, name, svg) {
  if (!el) return;
  if (el._slateIconSvg === svg) return;
  el._slateIconSvg = svg;
  const key = svg ? name : "";
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
  icon.classList.toggle("brand-mark", name.startsWith("brand-"));
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

function formatPlaceLabel(label) {
  const text = typeof label === "string" ? label.trim() : "";
  return text || FALLBACK_LOCATION.label;
}

function updateWeatherPlace() {
  const el = document.querySelector(".wx-place");
  if (el) el.textContent = formatPlaceLabel(activeLocation.label);
}

function applyLocation(loc) {
  if (!loc || typeof loc !== "object") return;
  if (typeof loc.lat === "number" && typeof loc.lon === "number") {
    activeLocation.lat = loc.lat;
    activeLocation.lon = loc.lon;
  }
  if (typeof loc.label === "string" && loc.label.trim()) activeLocation.label = loc.label.trim();
  if (typeof loc.timezone === "string") setActiveTimeZone(loc.timezone);
  activeLocation.locked = loc.locked === true;
  updateWeatherPlace();
}

async function reversePlaceLabel(lat, lon) {
  try {
    const url =
      "/place.json?lat=" + encodeURIComponent(String(lat)) +
      "&lon=" + encodeURIComponent(String(lon));
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (typeof data.label === "string" && data.label.trim()) return data.label.trim();
  } catch (err) {
    /* Fall back to coordinates below. */
  }
  return `${Number(lat).toFixed(2)}, ${Number(lon).toFixed(2)}`;
}

function detectDeviceLocation() {
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

async function resolveLocation() {
  try {
    const settings = await homeSettings();
    const loc = settings.location;
    if (loc && typeof loc.lat === "number" && typeof loc.lon === "number") {
      let label = typeof loc.label === "string" ? loc.label.trim() : "";
      applyLocation({ ...loc, label: label || activeLocation.label });
      if (loc.locked === true || onAndroidTv()) {
        if (!label || label.toLowerCase() === "near you") {
          label = await reversePlaceLabel(loc.lat, loc.lon);
          applyLocation({ ...loc, label });
        }
        return;
      }
    }
  } catch (err) {
    /* settings missing: still try geolocation */
  }
  const detected = await detectDeviceLocation();
  if (detected) {
    const label = await reversePlaceLabel(detected.lat, detected.lon);
    applyLocation({ ...detected, label, locked: false });
    return;
  }
  if (activeLocation.lat === FALLBACK_LOCATION.lat && activeLocation.lon === FALLBACK_LOCATION.lon) {
    applyLocation(FALLBACK_LOCATION);
  }
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
    const response = await fetch(weatherUrl(), { cache: "no-store" });
    if (gen !== wxLoadGen) return;
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (gen !== wxLoadGen) return;
    if (!weatherOk(data)) throw new Error("bad weather");
    wx = data;
    if (typeof data.timezone === "string") setActiveTimeZone(data.timezone);
    wxGoodAt = Date.now();
    writeWeatherCache();
  } catch (err) {
    /* Keep the last good forecast. Never fill in a made-up temperature. */
  }
  if (gen !== wxLoadGen) return;
  await renderWeather();
}

function applySettingsLocation(settings) {
  const loc = settings && settings.location;
  if (loc && typeof loc.lat === "number" && typeof loc.lon === "number") {
    const label = typeof loc.label === "string" && loc.label.trim() ? loc.label.trim() : activeLocation.label;
    applyLocation({ ...loc, label });
    updateWeatherPlace();
  }
}

async function bootWeatherAndTiles() {
  // Apps must be usable while location/weather services are still loading.
  const settingsPromise = homeSettings().catch(() => ({}));
  loadTiles();
  if (wxBox || dwx) {
    readWeatherCache();
    if (wx) renderWeather();
    settingsPromise.then(applySettingsLocation).finally(() => loadWeather());
    setInterval(() => {
      if (Date.now() - wxTriedAt >= WEATHER_EVERY_MS) loadWeather();
      else renderWeather();
    }, WEATHER_TICK_MS);
  }
  resolveLocation().then(() => {
    updateWeatherPlace();
    loadWeather();
  });
}

function wireHomeWeather() {
  const wx = document.getElementById("wx");
  if (!wx || !document.body.classList.contains("page-home")) return;
  wx.tabIndex = 0;
  wx.setAttribute("role", "button");
  wx.setAttribute("aria-label", "Weather. Open forecast");
  if (wx.dataset.weatherLink === "1") return;
  wx.dataset.weatherLink = "1";
  wx.addEventListener("click", () => {
    location.href = "weather.html";
  });
}

bootWeatherAndTiles();
wireHomeWeather();
document.addEventListener("slate:appearance", wireHomeWeather);

async function applyPointerSetting() {
  try {
    const settings = await homeSettings();
    const hide = settings.hidePointer === true;
    document.body.classList.toggle("hide-pointer", hide);
    if (hide) document.body.classList.remove("has-mouse");
  } catch (err) {
    /* A missing settings file keeps the pointer hidden until the mouse moves. */
  }
}

applyPointerSetting();

function applyCredit(show) {
  document.querySelectorAll("#site-credit").forEach((el) => {
    el.classList.toggle("hidden", show === false);
    if (show !== false) {
      el.tabIndex = 0;
    } else {
      el.tabIndex = -1;
    }
  });
}

async function applyCreditSetting() {
  try {
    const settings = await homeSettings();
    applyCredit(settings.showCredit !== false);
  } catch (err) {
    applyCredit(true);
  }
}

applyCreditSetting();

if (onDashboard()) {
  installDashboardBack();
  const homeLink = document.querySelector("a.home-pill[href='index.html']");
  if (homeLink) homeLink.focus({ preventScroll: true });
  ensureIcon("house").then((svg) => {
    const holder = document.getElementById("home-pill-icon");
    if (holder) applyIcon(holder, "house", svg);
  });
}
