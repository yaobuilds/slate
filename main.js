const TZ = "America/New_York";
const BURN_MS = 3 * 60 * 1000;
const BURN_OFFSETS = [
  [1, 0],
  [2, 1],
  [1, 2],
  [0, 1],
  [2, 0],
  [1, 1],
  [0, 2],
  [2, 2],
];

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

function fitStage() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  const step = Math.floor(Date.now() / BURN_MS) % BURN_OFFSETS.length;
  const [x, y] = BURN_OFFSETS[step];
  stage.style.transform =
    `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(${scale})`;
}

renderClock();
fitStage();
setInterval(renderClock, 1000);
setInterval(fitStage, BURN_MS);
window.addEventListener("resize", fitStage);
