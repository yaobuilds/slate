const CALENDAR_REFRESH_MS = 2 * 60 * 1000;
const GUEST_IDLE_MS = 30 * 60 * 1000;
const TODAY_CAP = 4;

const guestPill = document.getElementById("guest-pill");
const guestToggle = document.getElementById("guest-toggle");
const guestHint = document.getElementById("guest-hint");
const pinForm = document.getElementById("pin-form");
const pinInput = document.getElementById("pin-input");
const pinError = document.getElementById("pin-error");
const todayList = document.getElementById("today-list");
const upcomingList = document.getElementById("upcoming-list");
const staleEl = document.getElementById("data-stale");

let guestTimer = 0;
let generation = 0;

function guestOn() {
  return document.body.classList.contains("guest");
}

function armGuest() {
  clearTimeout(guestTimer);
  guestTimer = setTimeout(() => setGuest(true), GUEST_IDLE_MS);
}

function setGuest(on) {
  document.body.classList.toggle("guest", on);
  if (guestPill) guestPill.hidden = !on;
  if (guestToggle) {
    guestToggle.textContent = on ? "Show all" : "Guest mode";
    guestToggle.setAttribute("aria-pressed", String(!on));
  }
  if (guestHint) guestHint.textContent = on ? "Show all" : "Guest mode";
  loadCalendar();
}

function dayBounds() {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 14);
  return { start, end, now };
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

function timeLabel(event) {
  return event.allDay
    ? "All day"
    : eventStart(event).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function dateLabel(event) {
  return eventStart(event).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function displayTitle(event) {
  const title = typeof event.title === "string" ? event.title.trim() : "";
  if (guestOn()) return title || "Busy";
  return title || "Untitled event";
}

function row(meta, title, current = false, tall = false) {
  const li = document.createElement("li");
  li.className = `row${current ? " is-now" : ""}${tall ? " row-tall" : ""}`;
  const when = document.createElement("span");
  when.className = "row-meta";
  when.textContent = meta;
  const name = document.createElement("span");
  name.className = "row-title";
  name.textContent = title;
  li.append(when, name);
  return li;
}

function empty(label) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = label;
  return li;
}

function moreRow(count, label) {
  const li = document.createElement("li");
  li.className = "row-more";
  li.textContent = `+ ${count} more ${label}`;
  return li;
}

function render(payload) {
  const { start, now } = dayBounds();
  const tomorrow = new Date(start);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const events = Array.isArray(payload.events) ? payload.events : [];
  const today = events.filter(
    (event) => eventStart(event) < tomorrow && eventEnd(event) >= start,
  );
  const future = events.filter((event) => eventStart(event) >= tomorrow).slice(0, 4);

  const todayRows = today.slice(0, TODAY_CAP).map((event) => {
    const begins = eventStart(event);
    const ends = eventEnd(event);
    const title = displayTitle(event);
    const tall = title.length > 48;
    return row(
      begins <= now && ends > now ? "Now" : timeLabel(event),
      title,
      begins <= now && ends > now,
      tall,
    );
  });
  if (today.length > TODAY_CAP) todayRows.push(moreRow(today.length - TODAY_CAP, "today"));
  todayList.replaceChildren(...(todayRows.length ? todayRows : [empty("Nothing else today")]));

  if (upcomingList) {
    upcomingList.replaceChildren(
      ...(future.length
        ? future.map((event) =>
            row(`${dateLabel(event)} · ${timeLabel(event)}`, displayTitle(event), false, displayTitle(event).length > 48),
          )
        : [empty("Nothing coming up")]),
    );
  }

  if (staleEl) {
    if (!payload.configured) {
      staleEl.textContent = "Calendar connection needed";
    } else if (payload.stale) {
      staleEl.textContent = payload.syncedAt
        ? `Calendar unavailable · Last synced ${new Date(payload.syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : "Calendar unavailable";
    } else {
      staleEl.textContent = payload.syncedAt
        ? `Synced ${new Date(payload.syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : "";
    }
    staleEl.hidden = !staleEl.textContent;
  }
}

async function loadCalendar() {
  const gen = ++generation;
  const { start, end } = dayBounds();
  try {
    const response = await fetch(
      `calendar.json?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`,
      {
        cache: "no-store",
        headers: guestOn() ? {} : { "X-Slate-Full": "1" },
      },
    );
    if (gen !== generation) return;
    if (response.status === 401) {
      showPin();
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    hidePin();
    render(await response.json());
  } catch (error) {
    if (staleEl) {
      staleEl.textContent = "Could not refresh calendar";
      staleEl.hidden = false;
    }
  }
}

function showPin(message = "") {
  pinForm.hidden = false;
  pinError.textContent = message;
  pinInput.focus();
}

function hidePin() {
  pinForm.hidden = true;
  pinError.textContent = "";
  pinInput.blur();
}

if (guestToggle) {
  guestToggle.addEventListener("click", () => {
    armGuest();
    setGuest(!guestOn());
  });
}

pinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const pin = pinInput.value.trim();
  if (!/^[0-9]{4,8}$/.test(pin)) {
    pinError.textContent = "Enter the 4 to 8 digit PIN from this Mac.";
    return;
  }
  try {
    const response = await fetch("unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
      cache: "no-store",
    });
    if (!response.ok) {
      pinError.textContent =
        response.status === 429 ? "Wait a moment and try again." : "That PIN didn't work.";
      return;
    }
    pinInput.value = "";
    hidePin();
    setGuest(false);
    armGuest();
    loadCalendar();
  } catch (error) {
    pinError.textContent = "Couldn't reach this Mac.";
  }
});

document.addEventListener("keydown", (event) => {
  armGuest();
  if ((event.key === "g" || event.key === "G") && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    event.preventDefault();
    setGuest(!guestOn());
  }
});

if (typeof ensureIcon === "function") {
  ensureIcon("eyeoff").then((svg) => applyIcon(document.getElementById("guest-pill-icon"), "eyeoff", svg));
}

setGuest(true);
armGuest();
setInterval(loadCalendar, CALENDAR_REFRESH_MS);
