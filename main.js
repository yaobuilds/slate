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

function focusables() {
  return [...document.querySelectorAll("[data-focus]")].filter((el) => {
    if (el.hidden) return false;
    const style = getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden";
  });
}

function center(el) {
  const box = el.getBoundingClientRect();
  return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
}

function moveFocus(direction) {
  const items = focusables();
  if (!items.length) return;
  const current = items.includes(document.activeElement) ? document.activeElement : null;
  if (!current) {
    items[0].focus();
    return;
  }
  const from = center(current);
  let best = null;
  let bestScore = Infinity;
  for (const el of items) {
    if (el === current) continue;
    const to = center(el);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    if (direction === "left" && dx >= -4) continue;
    if (direction === "right" && dx <= 4) continue;
    if (direction === "up" && dy >= -4) continue;
    if (direction === "down" && dy <= 4) continue;
    const primary = direction === "left" || direction === "right" ? Math.abs(dx) : Math.abs(dy);
    const secondary = direction === "left" || direction === "right" ? Math.abs(dy) : Math.abs(dx);
    const score = primary + secondary * 2;
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (best) best.focus();
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const direction = {
    ArrowLeft: "left",
    ArrowRight: "right",
    ArrowUp: "up",
    ArrowDown: "down",
  }[event.key];
  if (!direction) return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  event.preventDefault();
  moveFocus(direction);
});

if (hmEl && secEl && ampmEl && dateEl) {
  renderClock();
  setInterval(renderClock, 1000);
}

if (stage) {
  fitStage();
  setInterval(fitStage, BURN_MS);
  window.addEventListener("resize", fitStage);
}
