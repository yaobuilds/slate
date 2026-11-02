const PAGE_SIZE = 6;
const GUEST_IDLE_MS = 30 * 60 * 1000;
const REFRESH_MS = 2 * 60 * 1000;
const DAY_MS = 86400000;

const content = document.getElementById("calendar-content");
const titleEl = document.getElementById("calendar-title");
const syncEl = document.getElementById("calendar-sync");
const pageEl = document.getElementById("calendar-page");
const guestButton = document.getElementById("calendar-guest");
const detail = document.getElementById("event-detail");
const pinForm = document.getElementById("calendar-pin");

let view = "today";
if (location.hash === "#week") view = "week";
else if (location.hash === "#month") view = "month";
let cursor = new Date();
cursor.setHours(0, 0, 0, 0);
let page = 0;
let payload = { events: [] };
let returnFocus = null;
let guestTimer = 0;
let loadGen = 0;

function guestOn() {
  return document.body.classList.contains("guest");
}

function armGuest() {
  clearTimeout(guestTimer);
  guestTimer = setTimeout(() => setGuest(true), GUEST_IDLE_MS);
}

function setGuest(on) {
  document.body.classList.toggle("guest", on);
  if (guestButton) guestButton.textContent = on ? "Show all" : "Guest mode";
  load();
}

function startOfWeek(date) {
  const d = new Date(date);
  d.setDate(d.getDate() - d.getDay());
  d.setHours(0, 0, 0, 0);
  return d;
}

function rangeForView() {
  if (view === "today") {
    const end = new Date(cursor.getTime() + DAY_MS);
    return [new Date(cursor), end];
  }
  if (view === "week") {
    const start = startOfWeek(cursor);
    return [start, new Date(start.getTime() + 7 * DAY_MS)];
  }
  const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const grid = startOfWeek(monthStart);
  return [grid, new Date(grid.getTime() + 42 * DAY_MS)];
}

function eventStart(event) {
  return event.allDay ? new Date(`${event.start}T00:00:00`) : new Date(event.start);
}

function eventEnd(event) {
  if (event.allDay && event.end) {
    const end = new Date(`${event.end}T00:00:00`);
    end.setMilliseconds(end.getMilliseconds() - 1);
    return end;
  }
  return new Date(event.end || event.start);
}

function eventsBetween(start, end) {
  return payload.events.filter((event) => eventStart(event) < end && eventEnd(event) >= start);
}

function eventTime(event) {
  if (event.allDay) return "All day";
  const start = eventStart(event);
  const end = eventEnd(event);
  return `${start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} – ${end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function displayTitle(event) {
  const title = typeof event.title === "string" ? event.title.trim() : "";
  if (guestOn()) return title || "Busy";
  return title || "Untitled event";
}

function makeEventButton(event, className = "agenda-item") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.dataset.calFocus = "";
  const when = document.createElement("span");
  when.className = "agenda-time";
  when.textContent = eventTime(event);
  const name = document.createElement("span");
  name.className = "agenda-title";
  const label = displayTitle(event);
  name.textContent = label;
  if (label.length > 55) button.classList.add("tall");
  button.append(when, name);
  button.addEventListener("click", () => openDetail(event, button));
  return button;
}

function renderToday() {
  const [start] = rangeForView();
  const end = new Date(start.getTime() + DAY_MS);
  const events = eventsBetween(start, end);
  const pages = Math.max(1, Math.ceil(events.length / PAGE_SIZE));
  page = Math.min(page, pages - 1);
  const slice = events.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const list = document.createElement("div");
  list.className = "agenda";
  slice.forEach((event) => list.append(makeEventButton(event)));
  if (!events.length) {
    list.className = "calendar-empty";
    list.textContent = "Nothing scheduled";
  }
  content.replaceChildren(list);
  titleEl.textContent = start.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  if (pages > 1) {
    pageEl.textContent = `Page ${page + 1} of ${pages}`;
  } else if (events.length > PAGE_SIZE) {
    pageEl.textContent = `${events.length - PAGE_SIZE} more today`;
  } else {
    pageEl.textContent = "Today";
  }
}

function renderWeek() {
  const [start] = rangeForView();
  const grid = document.createElement("div");
  grid.className = "week-grid";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = 0; i < 7; i += 1) {
    const day = new Date(start.getTime() + i * DAY_MS);
    const dayEnd = new Date(day.getTime() + DAY_MS);
    const col = document.createElement("section");
    col.className = `week-day${day.getTime() === today.getTime() ? " today" : ""}`;
    const head = document.createElement("h2");
    head.textContent = day.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    col.append(head);
    const dayEvents = eventsBetween(day, dayEnd);
    dayEvents.slice(0, 5).forEach((event) => {
      const button = makeEventButton(event, "week-event");
      const label = `${eventTime(event)} · ${displayTitle(event)}`;
      button.replaceChildren(document.createTextNode(label));
      col.append(button);
    });
    if (dayEvents.length > 5) {
      const more = document.createElement("p");
      more.className = "week-more";
      more.textContent = `+ ${dayEvents.length - 5} more`;
      col.append(more);
    }
    grid.append(col);
  }
  content.replaceChildren(grid);
  titleEl.textContent = `Week of ${start.toLocaleDateString([], { month: "long", day: "numeric" })}`;
  pageEl.textContent = "Seven days";
}

function renderMonth() {
  const [start] = rangeForView();
  const grid = document.createElement("div");
  grid.className = "month-grid";
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start.getTime() + i * DAY_MS);
    const dayEnd = new Date(day.getTime() + DAY_MS);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "month-day";
    button.dataset.calFocus = "";
    if (day.getMonth() !== cursor.getMonth()) button.classList.add("outside");
    if (eventsBetween(day, dayEnd).length) button.classList.add("has-events");
    button.textContent = String(day.getDate());
    button.addEventListener("click", () => {
      cursor = day;
      page = 0;
      setView("today");
    });
    grid.append(button);
  }
  content.replaceChildren(grid);
  titleEl.textContent = cursor.toLocaleDateString([], { month: "long", year: "numeric" });
  pageEl.textContent = "Select a day";
}

function renderSyncLine() {
  if (!payload.configured) {
    syncEl.textContent = "Connect Google Calendar on this Mac";
  } else if (payload.stale) {
    syncEl.textContent = payload.syncedAt
      ? `Offline · last sync ${new Date(payload.syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
      : "Offline · showing last sync";
  } else if (payload.syncedAt) {
    syncEl.textContent = `Synced ${new Date(payload.syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  } else {
    syncEl.textContent = "";
  }
}

function render() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  });
  if (view === "today") renderToday();
  else if (view === "week") renderWeek();
  else renderMonth();
  renderSyncLine();
}

async function load() {
  const gen = ++loadGen;
  const [start, end] = rangeForView();
  try {
    const response = await fetch(
      `calendar.json?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`,
      {
        cache: "no-store",
        headers: guestOn() ? {} : { "X-Slate-Full": "1" },
      },
    );
    if (gen !== loadGen) return;
    if (response.status === 401) {
      pinForm.hidden = false;
      document.getElementById("calendar-pin-input").focus();
      return;
    }
    if (!response.ok) throw new Error("calendar");
    payload = await response.json();
    render();
  } catch (error) {
    syncEl.textContent = "Could not refresh calendar";
    render();
  }
}

function setView(next) {
  view = next;
  page = 0;
  location.hash = next === "today" ? "" : next;
  load();
}

function openDetail(event, button) {
  if (guestOn()) return;
  returnFocus = button;
  document.getElementById("event-when").textContent = `${eventStart(event).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })} · ${eventTime(event)}`;
  document.getElementById("event-title").textContent = displayTitle(event);
  const place = document.getElementById("event-location");
  place.textContent = event.location ? `Location · ${event.location}` : "";
  place.hidden = !event.location;
  const notes = document.getElementById("event-notes");
  notes.textContent = event.notes || "";
  notes.hidden = !event.notes;
  detail.hidden = false;
  document.getElementById("event-close").focus();
}

function closeDetail() {
  detail.hidden = true;
  focusAndReveal(returnFocus);
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

if (guestButton) {
  guestButton.addEventListener("click", () => {
    armGuest();
    setGuest(!guestOn());
  });
}

document.getElementById("calendar-prev").addEventListener("click", () => {
  if (view === "today" && page > 0) {
    page -= 1;
    renderToday();
    return;
  }
  if (view === "today") cursor.setDate(cursor.getDate() - 1);
  else if (view === "week") cursor.setDate(cursor.getDate() - 7);
  else cursor.setMonth(cursor.getMonth() - 1);
  page = 0;
  load();
});

document.getElementById("calendar-next").addEventListener("click", () => {
  if (view === "today") {
    const [start] = rangeForView();
    const end = new Date(start.getTime() + DAY_MS);
    const events = eventsBetween(start, end);
    const pages = Math.max(1, Math.ceil(events.length / PAGE_SIZE));
    if (page < pages - 1) {
      page += 1;
      renderToday();
      return;
    }
  }
  if (view === "today") cursor.setDate(cursor.getDate() + 1);
  else if (view === "week") cursor.setDate(cursor.getDate() + 7);
  else cursor.setMonth(cursor.getMonth() + 1);
  page = 0;
  load();
});

document.getElementById("event-close").addEventListener("click", closeDetail);

pinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("calendar-pin-input");
  const error = document.getElementById("calendar-pin-error");
  const pin = input.value.trim();
  if (!/^[0-9]{4,8}$/.test(pin)) {
    error.textContent = "Enter the 4 to 8 digit PIN from this Mac.";
    return;
  }
  try {
    const response = await fetch("unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    if (!response.ok) {
      error.textContent = "That PIN didn't work.";
      return;
    }
    input.value = "";
    error.textContent = "";
    pinForm.hidden = true;
    setGuest(false);
    armGuest();
    load();
  } catch (err) {
    error.textContent = "Couldn't reach this Mac.";
  }
});

function focusAndReveal(el) {
  if (!el) return;
  el.focus({ preventScroll: true });
  if (typeof window.SlateSurface?.reveal === "function") {
    window.SlateSurface.reveal(el);
  }
}

function focusables() {
  const root = detail.hidden ? document : detail;
  return [...root.querySelectorAll("[data-cal-focus]")].filter((el) => el.offsetParent !== null);
}

function moveFocus(key) {
  const items = focusables();
  if (!items.includes(document.activeElement)) {
    focusAndReveal(items[0]);
    return;
  }
  if (window.SlateSurface && typeof SlateSurface.moveFocus === "function") {
    SlateSurface.moveFocus(items, key);
  }
}

document.addEventListener("keydown", (event) => {
  armGuest();
  const back =
    ["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key) ||
    [4, 461, 10009].includes(event.keyCode);
  if (back && (!detail.hidden || !pinForm.hidden)) {
    event.preventDefault();
    if (!detail.hidden) closeDetail();
    else pinForm.hidden = true;
    return;
  }
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    moveFocus(event.key);
  } else if (event.key === "Enter" && document.activeElement?.click) {
    event.preventDefault();
    document.activeElement.click();
  }
  if ((event.key === "g" || event.key === "G") && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    event.preventDefault();
    setGuest(!guestOn());
  }
});

setGuest(true);
armGuest();
load();
setInterval(load, REFRESH_MS);
