const REFRESH_MS = 60 * 1000;
const GUEST_IDLE_MS = 30 * 60 * 1000;

const guestFlag = document.getElementById("guest-flag");
const guestToggle = document.getElementById("guest-toggle");
const pinForm = document.getElementById("pin-form");
const pinInput = document.getElementById("pin-input");
const pinError = document.getElementById("pin-error");
const todayList = document.getElementById("today-list");
const deadlinesList = document.getElementById("deadlines-list");
const moneyNote = document.getElementById("money-note");
const deadlinesPanel = document.getElementById("panel-deadlines");
const moneyPanel = document.getElementById("panel-money");

let data = null;
let dataRaw = "";
let guestIdleTimer = 0;

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
}

function setGuest(on) {
  document.body.classList.toggle("guest", on);
  if (deadlinesPanel) deadlinesPanel.hidden = on;
  if (moneyPanel) moneyPanel.hidden = on;
  if (guestFlag) guestFlag.hidden = !on;
  syncGuestToggle();
  if (on) clearPrivate();
  else if (data) renderPrivate(data);
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

function fillList(list, items, emptyMessage, metaKey, titleKey) {
  const rows = [];
  for (const item of items) {
    const meta = text(item[metaKey]);
    const title = text(item[titleKey]);
    if (!meta && !title) continue;
    rows.push(row(meta, title));
  }
  list.replaceChildren(...(rows.length ? rows : [emptyItem(emptyMessage)]));
}

function renderToday(payload) {
  fillList(todayList, asList(payload.today), "Nothing today", "time", "title");
}

function renderPrivate(payload) {
  const deadlines = asList(payload.deadlines);
  const money = payload.money && typeof payload.money === "object" ? payload.money : {};
  fillList(deadlinesList, deadlines, "No deadlines coming up", "due", "title");
  const note = text(money.note);
  moneyNote.textContent = note || "No money update yet";
  moneyNote.classList.toggle("empty", !note);
}

async function loadData() {
  try {
    const response = await fetch("data.json", { cache: "no-store" });
    if (response.status === 401) {
      showPin("");
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    hidePin();
    const raw = await response.text();
    if (raw === dataRaw) return;
    const next = JSON.parse(raw);
    dataRaw = raw;
    data = next;
    renderToday(data);
    if (!guestOn()) renderPrivate(data);
  } catch (err) {
    /* Keep the last good boxes. A miss must not blank the screen. */
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
  setGuest(!guestOn());
});
