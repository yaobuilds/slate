const shell = document.getElementById("saver-shell");
const clockEl = document.getElementById("saver-clock");
const dateEl = document.getElementById("saver-date");
const weatherEl = document.getElementById("saver-weather");
const eventEl = document.getElementById("saver-event");

const DRIFT = [[0, 0], [1, 0], [2, 1], [1, -1], [0, -2], [-2, -1], [-2, 0], [-1, 1], [0, 2], [2, 2]];
let driftIndex = 0;
let tz = "America/New_York";

function tickClock() {
  const now = new Date();
  clockEl.textContent = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(now);
  dateEl.textContent = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(now);
}

function shiftSaver() {
  if (!shell) return;
  const [x, y] = DRIFT[driftIndex % DRIFT.length];
  shell.style.transform = `translate(${x}px, ${y}px)`;
  driftIndex += 1;
}

async function loadSettings() {
  try {
    const settings = await fetch("settings.json", { cache: "no-store" }).then((r) => r.json());
    if (settings.location?.timezone) tz = settings.location.timezone;
    document.body.dataset.tvAppearance = settings.tvAppearance || "sculptural";
    document.body.dataset.tvMotion = "still";
    if (window.SlateLooks && settings.tvAppearance) {
      const look = settings.tvAppearance;
      if (look === "sculptural") await window.SlateLooks.loadAmbient();
      const colors = look === "sculptural" ? window.SlateLooks.ambientColorsFor(settings.ambientPreset) : undefined;
      const key = look === "aqua" ? settings.tvAquaPalette : look === "flurry" ? settings.tvFlurryPalette : "";
      window.SlateLooks.decorate(
        document.getElementById("tv-backdrop"),
        look,
        "still",
        "soft",
        colors,
        key,
      );
    }
  } catch (error) {
    /* defaults */
  }
}

async function loadWeather() {
  try {
    const settings = await fetch("settings.json", { cache: "no-store" }).then((r) => r.json());
    const loc = settings.location || { lat: 40.7128, lon: -74.0060, label: "Weather" };
    const url =
      "https://api.open-meteo.com/v1/forecast?latitude=" +
      encodeURIComponent(String(loc.lat)) +
      "&longitude=" +
      encodeURIComponent(String(loc.lon)) +
      "&current=temperature_2m,weather_code&temperature_unit=fahrenheit&timezone=auto";
    const data = await fetch(url, { cache: "no-store" }).then((r) => r.json());
    const temp = Math.round(data.current.temperature_2m);
    weatherEl.textContent = `${loc.label || "Weather"} · ${temp}°`;
  } catch (error) {
    weatherEl.textContent = "Weather unavailable";
  }
}

async function loadNextEvent() {
  try {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 2);
    const response = await fetch(
      `calendar.json?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(String(response.status));
    const payload = await response.json();
    const now = Date.now();
    const next = (payload.events || []).find((event) => {
      const stamp = event.allDay ? new Date(`${event.start}T12:00:00`).getTime() : new Date(event.start).getTime();
      return stamp >= now - 60000;
    });
    if (!next) {
      eventEl.textContent = "Nothing coming up";
      return;
    }
    const when = next.allDay
      ? "All day"
      : new Date(next.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    eventEl.textContent = `${when} · Busy`;
  } catch (error) {
    eventEl.textContent = "Calendar unavailable";
  }
}

tickClock();
setInterval(tickClock, 60000);
shiftSaver();
setInterval(shiftSaver, 3 * 60 * 1000);
loadSettings();
loadWeather();
loadNextEvent();
setInterval(loadWeather, 10 * 60 * 1000);
setInterval(loadNextEvent, 2 * 60 * 1000);
