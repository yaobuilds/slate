const REFRESH_MS = 60 * 1000;
const GUEST_IDLE_MS = 30 * 60 * 1000;
const TODAY_MAX_FULL = 4;
const TODAY_MAX_GUEST = 6;

const guestPill = document.getElementById("guest-pill");
const guestToggle = document.getElementById("guest-toggle");
const guestHint = document.getElementById("guest-hint");
const pinForm = document.getElementById("pin-form");
const pinInput = document.getElementById("pin-input");
const pinError = document.getElementById("pin-error");
const todayList = document.getElementById("today-list");
const deadlinesList = document.getElementById("deadlines-list");
const moneyNote = document.getElementById("money-note");
const deadlinesPanel = document.getElementById("panel-deadlines");
const moneyPanel = document.getElementById("panel-money");
const dataStaleEl = document.getElementById("data-stale");

let data = null;
let dataRaw = "";
let lastGoodUpdated = "";
let failStreak = 0;
let guestIdleTimer = 0;
let loadGen = 0;

function armGuestIdle() {
  clearTimeout(guestIdleTimer);
  guestIdleTimer = setTimeout(returnToGuest, GUEST_IDLE_MS);
}

function returnToGuest() {
  if (guestOn()) return;
  setGuest(true);
  if (window.ambient && typeof window.ambient.arrive === "function") window.ambient.arrive();
}

function guestOn() {
  return document.body.classList.contains("guest");
}

function clearPrivate() {
  if (deadlinesList) deadlinesList.replaceChildren();
  if (moneyNote) {
    moneyNote.textContent = "";
    moneyNote.classList.remove("empty");
  }
}

function syncGuestToggle() {
  if (!guestToggle) return;
  const on = guestOn();
  guestToggle.textContent = on ? "Show all" : "Guest mode";
  guestToggle.setAttribute("aria-pressed", on ? "false" : "true");
  if (guestHint) guestHint.textContent = on ? "Show all" : "Guest mode";
}

function scrubToday() {
  if (!todayList) return;
  todayList.querySelectorAll(".row-title").forEach((el) => {
    if (el.textContent) el.textContent = "Busy";
  });
}

function setGuest(on) {
  document.body.classList.toggle("guest", on);
  if (deadlinesPanel) deadlinesPanel.hidden = on;
  if (moneyPanel) moneyPanel.hidden = on;
  if (guestPill) guestPill.hidden = !on;
  syncGuestToggle();
  if (on) {
    clearPrivate();
    scrubToday();
    data = null;
    dataRaw = "";
  }
  loadData();
}

function showPin(message) {
  if (!pinForm) return;
  const wasHidden = pinForm.hidden;
  pinForm.hidden = false;
  if (pinError && message) pinError.textContent = message;
  if (wasHidden && pinInput) pinInput.focus();
}

function hidePin() {
  if (!pinForm) return;
  pinForm.hidden = true;
  if (pinError) pinError.textContent = "";
  if (pinInput) pinInput.blur();
}

function asList(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => item && typeof item === "object");
}

function text(value) {
  return typeof value === "string" ? value : "";
}

function emptyItem(message) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = message;
  return li;
}

function row(meta, title) {
  const li = document.createElement("li");
  li.className = "row";
  const metaEl = document.createElement("span");
  metaEl.className = "row-meta";
  metaEl.textContent = meta;
  const titleEl = document.createElement("span");
  titleEl.className = "row-title";
  titleEl.textContent = title;
  li.append(metaEl, titleEl);
  return li;
}

function moreRow(count) {
  const li = document.createElement("li");
  li.className = "row-more";
  li.textContent = `+ ${count} more`;
  return li;
}

function clampTitle(text, guest) {
  const value = text.replace(/\s+/g, " ").trim();
  if (!value) return "";
  const max = guest ? 80 : 120;
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}…`;
}

function shownTitle(item) {
  const title = text(item.title);
  if (!guestOn()) return clampTitle(title, false);
  if (!text(item.time) && !title) return "";
  return "Busy";
}

function parseIsoDate(due) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!year || month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

function slateTz() {
  return typeof window.slateTimezone === "string" && window.slateTimezone
    ? window.slateTimezone
    : "America/New_York";
}

function nyTodayParts() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: slateTz(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const value = (type) => Number(parts.find((item) => item.type === type).value);
  return { year: value("year"), month: value("month"), day: value("day") };
}

function daysUntilDue(parsed) {
  const today = nyTodayParts();
  const a = Date.UTC(today.year, today.month - 1, today.day);
  const b = Date.UTC(parsed.year, parsed.month - 1, parsed.day);
  return Math.round((b - a) / 86400000);
}

function weekdayShort(parsed) {
  const date = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day, 12));
  return new Intl.DateTimeFormat("en-US", { timeZone: slateTz(), weekday: "short" }).format(date);
}

function monthDay(parsed) {
  const date = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day, 12));
  return new Intl.DateTimeFormat("en-US", { timeZone: slateTz(), month: "short", day: "numeric" }).format(date);
}

function countdownLabel(days) {
  if (days < 0) return "Past due";
  if (days === 0) return "Due today";
  if (days === 1) return "Tomorrow";
  return `${days} days`;
}

function formatDue(due) {
  const raw = text(due).trim();
  if (!raw) return "";
  const parsed = parseIsoDate(raw);
  if (!parsed) return raw;
  const days = daysUntilDue(parsed);
  return `${weekdayShort(parsed)}, ${monthDay(parsed)} · ${countdownLabel(days)}`;
}

function renderToday(payload) {
  if (!todayList) return;
  const guest = guestOn();
  const maxRows = guest ? TODAY_MAX_GUEST : TODAY_MAX_FULL;
  const items = asList(payload.today).map((item) => ({
    time: text(item.time),
    title: shownTitle(item),
  }));
  const visible = items.filter((item) => item.time || item.title);
  const rows = [];
  for (let i = 0; i < Math.min(visible.length, maxRows); i += 1) {
    const item = visible[i];
    rows.push(row(item.time, clampTitle(item.title, guest)));
  }
  const extra = visible.length - maxRows;
  if (extra > 0) rows.push(moreRow(extra));
  todayList.replaceChildren(...(rows.length ? rows : [emptyItem("Nothing today")]));
}

function renderPrivate(payload) {
  const deadlines = asList(payload.deadlines)
    .slice()
    .sort((a, b) => {
      const pa = parseIsoDate(text(a.due));
      const pb = parseIsoDate(text(b.due));
      if (pa && pb) {
        return Date.UTC(pa.year, pa.month - 1, pa.day) - Date.UTC(pb.year, pb.month - 1, pb.day);
      }
      return text(a.due).localeCompare(text(b.due));
    })
    .slice(0, 4)
    .map((item) => ({
      due: formatDue(item.due),
      title: clampTitle(text(item.title), false),
    }));
  const money = payload.money && typeof payload.money === "object" ? payload.money : {};
  fillList(deadlinesList, deadlines, "No deadlines coming up", "due", "title");
  const note = text(money.note);
  moneyNote.textContent = note || "No money update yet";
  moneyNote.classList.toggle("empty", !note);
}

function fillList(list, items, emptyMessage, metaKey, titleKey) {
  if (!list) return;
  const rows = [];
  for (const item of items) {
    const meta = text(item[metaKey]);
    const title = text(item[titleKey]);
    if (!meta && !title) continue;
    rows.push(row(meta, title));
  }
  list.replaceChildren(...(rows.length ? rows : [emptyItem(emptyMessage)]));
}

function hmFromUpdated(iso) {
  if (typeof iso !== "string" || !iso) return "";
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return "";
  let hour = Number(match[1]);
  const minute = match[2];
  hour = hour % 12 || 12;
  return `${hour}:${minute}`;
}

function updateStaleLine() {
  if (!dataStaleEl) return;
  if (failStreak >= 2 && lastGoodUpdated) {
    const stamp = hmFromUpdated(lastGoodUpdated);
    dataStaleEl.textContent = stamp
      ? `Couldn't refresh · Updated ${stamp}`
      : "Couldn't refresh";
    dataStaleEl.hidden = false;
    return;
  }
  dataStaleEl.textContent = "";
  dataStaleEl.hidden = true;
}

async function loadData() {
  const gen = ++loadGen;
  const full = !guestOn();
  try {
    const response = await fetch("data.json", {
      cache: "no-store",
      headers: full ? { "X-Slate-Full": "1" } : {},
    });
    if (gen !== loadGen || full !== !guestOn()) return;
    if (response.status === 401) {
      data = null;
      dataRaw = "";
      clearPrivate();
      if (todayList) todayList.replaceChildren();
      showPin("");
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    hidePin();
    const raw = await response.text();
    if (gen !== loadGen || full !== !guestOn()) return;
    if (raw === dataRaw) {
      failStreak = 0;
      updateStaleLine();
      return;
    }
    const next = JSON.parse(raw);
    if (full && guestOn()) return;
    dataRaw = raw;
    data = full ? next : null;
    failStreak = 0;
    if (typeof next.updated === "string" && next.updated) lastGoodUpdated = next.updated;
    renderToday(next);
    if (!guestOn()) renderPrivate(next);
    updateStaleLine();
  } catch (err) {
    failStreak += 1;
    updateStaleLine();
  }
}

loadData();
setInterval(loadData, REFRESH_MS);

document.addEventListener("keydown", armGuestIdle, true);
armGuestIdle();

if (guestToggle) {
  guestToggle.addEventListener("click", () => {
    armGuestIdle();
    setGuest(!guestOn());
  });
}

if (pinForm && pinInput) {
  pinForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const pin = pinInput.value.trim();
    if (!/^[0-9]{4,8}$/.test(pin)) {
      if (pinError) pinError.textContent = "Enter the 4 to 8 digit PIN from this Mac.";
      return;
    }
    if (pinError) pinError.textContent = "";
    let response;
    try {
      response = await fetch("unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: pin }),
        cache: "no-store",
      });
    } catch (err) {
      if (pinError) pinError.textContent = "Couldn't reach this Mac.";
      return;
    }
    if (response.status === 429) {
      if (pinError) pinError.textContent = "Wait a moment and try again.";
      return;
    }
    if (!response.ok) {
      if (pinError) pinError.textContent = "That PIN didn't work.";
      return;
    }
    pinInput.value = "";
    hidePin();
    loadData();
  });
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key !== "g" && event.key !== "G") return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  event.preventDefault();
  armGuestIdle();
  setGuest(!guestOn());
});

function paintGuestPillIcon() {
  const holder = document.getElementById("guest-pill-icon");
  if (!holder || typeof ensureIcon !== "function") return;
  ensureIcon("eyeoff").then((svg) => {
    if (holder.isConnected && typeof applyIcon === "function") applyIcon(holder, "eyeoff", svg);
  });
}

paintGuestPillIcon();
syncGuestToggle();
if (guestPill) guestPill.hidden = !guestOn();
