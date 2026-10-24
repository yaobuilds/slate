const REFRESH_MS = 60 * 1000;
const GUEST_KEY = "tv-guest";

const guestFlag = document.getElementById("guest-flag");
const todayList = document.getElementById("today-list");
const deadlinesList = document.getElementById("deadlines-list");
const moneyNote = document.getElementById("money-note");
const todayPanel = document.getElementById("panel-today");

let hasData = false;

function readGuest() {
  try {
    return sessionStorage.getItem(GUEST_KEY) === "1";
  } catch (err) {
    return false;
  }
}

function writeGuest(on) {
  try {
    sessionStorage.setItem(GUEST_KEY, on ? "1" : "0");
  } catch (err) {
    /* Keep the mode for this page view when storage is blocked. */
  }
}

function setGuest(on) {
  document.body.classList.toggle("is-guest", on);
  guestFlag.hidden = !on;
  writeGuest(on);
  const active = document.activeElement;
  if (on && active && active.classList.contains("panel") && !active.offsetParent) {
    todayPanel.focus();
  }
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

function render(data) {
  const today = asList(data.today);
  const deadlines = asList(data.deadlines);
  const money = data.money && typeof data.money === "object" ? data.money : {};
  fillList(todayList, today, "Nothing on today", "time", "title");
  fillList(deadlinesList, deadlines, "No deadlines", "due", "title");
  const note = text(money.note);
  moneyNote.textContent = note || "Nothing noted";
  moneyNote.classList.toggle("empty", !note);
}

function showError() {
  todayList.replaceChildren(emptyItem("Could not load the dashboard"));
  deadlinesList.replaceChildren();
  moneyNote.textContent = "";
}

async function loadData() {
  try {
    const response = await fetch("data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    render(data);
    hasData = true;
  } catch (err) {
    if (!hasData) showError();
  }
}

setGuest(readGuest());
loadData();
setInterval(loadData, REFRESH_MS);

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key !== "g" && event.key !== "G") return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  event.preventDefault();
  setGuest(!document.body.classList.contains("is-guest"));
});
