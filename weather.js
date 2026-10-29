const ICON_FILES = new Set([
  "sun", "moon", "cloud", "cloudsun", "cloudmoon", "rain", "snow", "fog", "storm", "cloudoff",
]);
const ICON_FALLBACK =
  '<svg class="i" focusable="false" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 16.2a4.5 4.5 0 0 0-.9-8.9A6.2 6.2 0 0 0 7.3 6a4.8 4.8 0 0 0-1 9.9H20Z"/></svg>';
const iconCache = new Map();

const dayStrip = document.getElementById("day-strip");
const hourlyList = document.getElementById("hourly-list");
const rainChart = document.getElementById("rain-chart");
const rainPanel = document.getElementById("rain-panel");
const rainSummary = document.getElementById("rain-summary");
const weatherTitle = document.getElementById("weather-title");
const weatherPlace = document.getElementById("weather-place");
const weatherUpdated = document.getElementById("weather-updated");
const radarImage = document.getElementById("radar-image");
const radarBasemap = document.getElementById("radar-basemap");
const radarCaption = document.getElementById("radar-caption");
const radarTime = document.getElementById("radar-time");
const TV_LAYOUT = window.matchMedia("(min-width: 960px) and (min-height: 540px) and (min-aspect-ratio: 16/9)");
const radarPlay = document.getElementById("radar-play");
const radarZoom = document.getElementById("radar-zoom");

let savedPlace = { lat: 40.7128, lon: -74.0060, label: "New York, NY", timezone: "America/New_York" };
let forecast = null;
let selectedDay = 0;
let radarFrame = 0;
let radarPlaying = false;
let radarTimer = 0;
let radarZoomLevel = "near";

function wmo(code, isDay) {
  const day = isDay === 1 || isDay === true;
  if (code === 0) return [day ? "sun" : "moon", "Clear"];
  if (code === 1) return [day ? "sun" : "moon", "Mostly clear"];
  if (code === 2) return [day ? "cloudsun" : "cloudmoon", "Partly cloudy"];
  if (code === 3) return ["cloud", "Cloudy"];
  if (code === 45 || code === 48) return ["fog", "Fog"];
  if (code >= 51 && code <= 67 || (code >= 80 && code <= 82)) return ["rain", "Rain"];
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return ["snow", "Snow"];
  if (code >= 95) return ["storm", "Storms"];
  return ["cloudoff", "Unknown"];
}

async function loadIcon(name) {
  if (!ICON_FILES.has(name)) return ICON_FALLBACK;
  if (iconCache.has(name)) return iconCache.get(name);
  try {
    const response = await fetch(`assets/icons/${name}.svg`);
    if (!response.ok) throw new Error("icon");
    const text = await response.text();
    const svg = text.replace("<svg ", '<svg class="i" focusable="false" aria-hidden="true" ');
    iconCache.set(name, svg);
    return svg;
  } catch (error) {
    return ICON_FALLBACK;
  }
}

function weatherUrl() {
  return (
    "https://api.open-meteo.com/v1/forecast?latitude=" +
    encodeURIComponent(String(savedPlace.lat)) +
    "&longitude=" +
    encodeURIComponent(String(savedPlace.lon)) +
    "&current=temperature_2m,weather_code,is_day" +
    "&hourly=temperature_2m,weather_code,is_day,precipitation_probability,precipitation" +
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max" +
    "&minutely_15=precipitation,precipitation_probability" +
    "&temperature_unit=fahrenheit&precipitation_unit=inch&timezone=auto&forecast_days=7&forecast_hours=168"
  );
}

function dayLabel(index) {
  const date = forecast.daily.time[index];
  const d = new Date(`${date}T12:00:00`);
  if (index === 0) return "Today";
  return d.toLocaleDateString([], { weekday: "short" });
}

function hoursForDay(index) {
  const day = forecast.daily.time[index];
  const out = [];
  for (let i = 0; i < forecast.hourly.time.length; i += 1) {
    if (!forecast.hourly.time[i].startsWith(day)) continue;
    out.push({
      time: forecast.hourly.time[i],
      temp: forecast.hourly.temperature_2m[i],
      code: forecast.hourly.weather_code[i],
      isDay: forecast.hourly.is_day[i],
      rainChance: forecast.hourly.precipitation_probability[i],
      rainAmount: forecast.hourly.precipitation[i],
    });
  }
  return out;
}

function renderDays() {
  dayStrip.replaceChildren();
  for (let i = 0; i < forecast.daily.time.length; i += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day-card";
    button.dataset.wxFocus = "";
    button.setAttribute("aria-pressed", String(i === selectedDay));
    const [iconName] = wmo(forecast.daily.weather_code[i], 1);
    const label = document.createElement("span");
    label.textContent = dayLabel(i);
    const icon = document.createElement("span");
    icon.className = "day-icon";
    icon.textContent = "…";
    loadIcon(iconName).then((svg) => {
      icon.innerHTML = svg;
    });
    const small = document.createElement("small");
    small.textContent = `${Math.round(forecast.daily.temperature_2m_max[i])}° / ${Math.round(forecast.daily.temperature_2m_min[i])}°`;
    button.append(label, icon, small);
    button.addEventListener("click", () => {
      selectedDay = i;
      renderDays();
      renderHours();
      renderRain();
    });
    dayStrip.append(button);
  }
}

async function renderHours() {
  const hours = hoursForDay(selectedDay);
  const pageSize = 8;
  hourlyList.replaceChildren();
  for (const hour of hours.slice(0, pageSize)) {
    const card = document.createElement("div");
    card.className = "hour-card";
    const time = new Date(hour.time);
    const [iconName, label] = wmo(hour.code, hour.isDay);
    const strong = document.createElement("strong");
    strong.textContent = time.toLocaleTimeString([], { hour: "numeric" });
    const cond = document.createElement("span");
    cond.textContent = `${Math.round(hour.temp)}° · ${label}`;
    const rain = document.createElement("small");
    const chance = Number.isFinite(hour.rainChance) ? `${Math.round(hour.rainChance)}% rain` : "";
    const amount = Number.isFinite(hour.rainAmount) && hour.rainAmount > 0 ? `${hour.rainAmount.toFixed(2)} in` : "";
    rain.textContent = [chance, amount].filter(Boolean).join(" · ");
    card.append(strong, cond, rain);
    const iconHolder = document.createElement("span");
    iconHolder.innerHTML = await loadIcon(iconName);
    card.prepend(iconHolder);
    hourlyList.append(card);
  }
  if (hours.length > pageSize) {
    rainSummary.textContent = `Showing ${pageSize} of ${hours.length} hours`;
  } else {
    const day = forecast.daily.time[selectedDay];
    rainSummary.textContent = `${Math.round(forecast.daily.precipitation_probability_max[selectedDay] || 0)}% max rain · ${Number(forecast.daily.precipitation_sum[selectedDay] || 0).toFixed(2)} in total`;
  }
  weatherTitle.textContent = selectedDay === 0 ? "Today" : new Date(`${forecast.daily.time[selectedDay]}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

function renderRain() {
  rainChart.replaceChildren();
  if (selectedDay !== 0 || !forecast.minutely_15) {
    rainPanel.hidden = true;
    return;
  }
  rainPanel.hidden = false;
  const times = forecast.minutely_15.time || [];
  const amounts = forecast.minutely_15.precipitation || [];
  const chances = forecast.minutely_15.precipitation_probability || [];
  const now = Date.now();
  let shown = 0;
  for (let i = 0; i < times.length && shown < 16; i += 1) {
    const stamp = new Date(times[i]).getTime();
    if (stamp < now - 15 * 60 * 1000) continue;
    const bar = document.createElement("i");
    bar.className = "rain-bar";
    const amount = Number(amounts[i]) || 0;
    const chance = (Number(chances[i]) || 0) / 100;
    bar.style.setProperty("--rain", String(Math.min(1, amount * 40)));
    bar.style.setProperty("--chance", String(chance));
    bar.title = new Date(times[i]).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    rainChart.append(bar);
    shown += 1;
  }
}

function radarStamp(frame) {
  const base = Math.floor(Date.now() / 600000) * 600;
  return base - frame * 600;
}

function radarSpanMiles() {
  return radarZoomLevel === "near" ? 90 : 220;
}

function updateRadarImage() {
  const stamp = radarStamp(radarFrame);
  const label = savedPlace.label || "Saved location";
  if (radarCaption) {
    radarCaption.textContent = `${label} · about ${radarSpanMiles()} miles across`;
  }
  if (radarBasemap) {
    radarBasemap.src = `radar.png?layer=basemap&zoom=${radarZoomLevel}&t=${Math.floor(Date.now() / 86400000)}`;
  }
  radarImage.src = `radar.png?zoom=${radarZoomLevel}&frame=${radarFrame}&t=${stamp}`;
  radarTime.textContent = `Recent radar · ${new Date(stamp * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function applyWeatherLayout() {
  const tvSurface = document.documentElement.dataset.slateSurface === "tv";
  document.body.classList.toggle("weather-tv", TV_LAYOUT.matches && tvSurface);
}

function detectDeviceLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: Math.round(pos.coords.latitude * 100) / 100,
        lon: Math.round(pos.coords.longitude * 100) / 100,
      }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 4000, maximumAge: 10 * 60 * 1000 },
    );
  });
}

async function reversePlaceLabel(lat, lon) {
  try {
    const response = await fetch(
      `/place.json?lat=${encodeURIComponent(String(lat))}&lon=${encodeURIComponent(String(lon))}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (typeof data.label === "string" && data.label.trim()) return data.label.trim();
  } catch (error) {
    /* fall through */
  }
  return `${Number(lat).toFixed(2)}, ${Number(lon).toFixed(2)}`;
}

function applyWeatherPlaceFromSettings(settings) {
  const loc = settings?.location;
  if (loc && typeof loc.lat === "number" && typeof loc.lon === "number") {
    const label = typeof loc.label === "string" && loc.label.trim() ? loc.label.trim() : savedPlace.label;
    savedPlace = { ...savedPlace, ...loc, label };
  }
}

function forecastOk(data) {
  return !!(data && Array.isArray(data.daily?.time) && data.daily.time.length > 0);
}

async function resolveWeatherPlace(settings) {
  const loc = settings?.location;
  const onTv = /Android TV|Google TV/i.test(navigator.userAgent || "");
  applyWeatherPlaceFromSettings(settings);
  if (loc && typeof loc.lat === "number" && (loc.locked === true || onTv)) {
    let label = typeof loc.label === "string" ? loc.label.trim() : "";
    if (!label) label = await reversePlaceLabel(loc.lat, loc.lon);
    savedPlace = { ...savedPlace, label };
    return;
  }
  const detected = await detectDeviceLocation();
  if (detected) {
    const label = await reversePlaceLabel(detected.lat, detected.lon);
    savedPlace = { ...detected, label, timezone: savedPlace.timezone };
  }
}

function setRadarPlaying(on) {
  radarPlaying = on;
  clearInterval(radarTimer);
  radarPlay.textContent = on ? "Pause" : "Play";
  if (on) {
    radarTimer = setInterval(() => {
      radarFrame = (radarFrame + 1) % 6;
      updateRadarImage();
    }, 900);
  }
}

function focusables() {
  return [...document.querySelectorAll("[data-wx-focus]")].filter((el) => el.offsetParent !== null);
}

function moveFocus(key) {
  const items = focusables();
  const current = document.activeElement;
  if (!items.includes(current)) {
    items[0]?.focus();
    return;
  }
  const rect = current.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  let best = null;
  let score = Infinity;
  for (const el of items) {
    if (el === current) continue;
    const target = el.getBoundingClientRect();
    const dx = target.left + target.width / 2 - x;
    const dy = target.top + target.height / 2 - y;
    if (key === "ArrowLeft" && dx >= 0) continue;
    if (key === "ArrowRight" && dx <= 0) continue;
    if (key === "ArrowUp" && dy >= 0) continue;
    if (key === "ArrowDown" && dy <= 0) continue;
    const primary = key === "ArrowLeft" || key === "ArrowRight" ? Math.abs(dx) : Math.abs(dy);
    const secondary = key === "ArrowLeft" || key === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
    const nextScore = primary * 1000 + secondary;
    if (nextScore < score) {
      score = nextScore;
      best = el;
    }
  }
  best?.focus({ preventScroll: true });
}

async function init() {
  applyWeatherLayout();
  if (TV_LAYOUT.addEventListener) {
    TV_LAYOUT.addEventListener("change", applyWeatherLayout);
  } else {
    addEventListener("resize", applyWeatherLayout);
  }
  let settings = null;
  try {
    settings = await fetch("settings.json", { cache: "no-store" }).then((r) => r.json());
  } catch (error) {
    /* Keep fallback location. */
  }
  applyWeatherPlaceFromSettings(settings);
  weatherPlace.textContent = savedPlace.label || "Weather";
  const placeTask = resolveWeatherPlace(settings).then(() => {
    weatherPlace.textContent = savedPlace.label || "Weather";
  });
  try {
    const response = await fetch(weatherUrl(), { cache: "no-store" });
    if (!response.ok) throw new Error("weather");
    const data = await response.json();
    if (!forecastOk(data)) throw new Error("weather");
    forecast = data;
    weatherUpdated.textContent = "Updated just now";
    renderDays();
    await renderHours();
    renderRain();
    updateRadarImage();
  } catch (error) {
    weatherUpdated.textContent = "Weather unavailable";
  }
  placeTask.then(async () => {
    try {
      const response = await fetch(weatherUrl(), { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      if (!forecastOk(data)) return;
      forecast = data;
      weatherUpdated.textContent = "Updated just now";
      renderDays();
      await renderHours();
      renderRain();
      updateRadarImage();
    } catch (error) {
      /* keep first load result */
    }
  });
}

radarPlay?.addEventListener("click", () => setRadarPlaying(!radarPlaying));
radarZoom?.addEventListener("click", () => {
  radarZoomLevel = radarZoomLevel === "near" ? "wide" : "near";
  radarZoom.textContent = radarZoomLevel === "near" ? "Wide" : "Near";
  updateRadarImage();
});

document.addEventListener("keydown", (event) => {
  const back =
    ["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key) ||
    [4, 461, 10009].includes(event.keyCode);
  if (back) {
    event.preventDefault();
    location.href = "index.html";
    return;
  }
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    moveFocus(event.key);
  } else if (event.key === "Enter" && document.activeElement?.click) {
    event.preventDefault();
    document.activeElement.click();
  }
});

init();
