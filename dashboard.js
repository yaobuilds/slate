const REFRESH_MS = 60 * 1000;

const guestFlag = document.getElementById("guest-flag");
const todayList = document.getElementById("today-list");
const deadlinesList = document.getElementById("deadlines-list");
const moneyNote = document.getElementById("money-note");
const deadlinesPanel = document.getElementById("panel-deadlines");
const moneyPanel = document.getElementById("panel-money");

let data = null;
let dataRaw = "";

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

function setGuest(on) {
  document.body.classList.toggle("guest", on);
  if (deadlinesPanel) deadlinesPanel.hidden = on;
  if (moneyPanel) moneyPanel.hidden = on;
  if (guestFlag) guestFlag.hidden = !on;
  if (on) clearPrivate();
  else if (data) renderPrivate(data);
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
    if (!response.ok) throw new Error(String(response.status));
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

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key !== "g" && event.key !== "G") return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  event.preventDefault();
  setGuest(!guestOn());
});
