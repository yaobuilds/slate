const statusEl = document.getElementById("calendar-status");
const hostPanel = document.getElementById("calendar-host-panel");
const setupPanel = document.getElementById("calendar-setup-panel");
const remoteNote = document.getElementById("calendar-remote-note");
const clientIdInput = document.getElementById("calendar-client-id");
const clientSecretInput = document.getElementById("calendar-client-secret");
const pickSelect = document.getElementById("calendar-pick");
const saveClientBtn = document.getElementById("calendar-save-client");
const connectBtn = document.getElementById("calendar-connect");
const savePickBtn = document.getElementById("calendar-save-pick");
const disconnectBtn = document.getElementById("calendar-disconnect");

function isHost() {
  const host = location.hostname;
  return host === "127.0.0.1" || host === "localhost";
}

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

async function readCalendarStatus() {
  const response = await fetch("calendar/status.json", { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function readCalendarList() {
  const response = await fetch("calendar/list.json", { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function renderStatus(data) {
  if (!data.configured) {
    if (data.hasClient && data.hasToken) {
      setStatus("Signed in to Google. Choose a calendar below.");
    } else if (data.hasClient) {
      setStatus("Client saved. Connect with Google, then choose a calendar.");
    } else {
      setStatus("Not connected. Save your OAuth client, then connect with Google.");
    }
    return;
  }
  const name = data.calendarName || data.calendarId;
  const sync = data.syncedAt
    ? `Last sync ${new Date(data.syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
    : "Waiting for first sync";
  setStatus(`${name} · ${sync}${data.stale ? " · offline, showing last sync" : ""}`);
}

async function fillCalendarPick(selectedId) {
  pickSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a calendar";
  pickSelect.append(placeholder);
  try {
    const payload = await readCalendarList();
    for (const row of payload.calendars || []) {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = row.summary;
      pickSelect.append(option);
    }
    pickSelect.disabled = !(payload.calendars || []).length;
    savePickBtn.disabled = pickSelect.disabled;
    if (selectedId) pickSelect.value = selectedId;
  } catch (error) {
    pickSelect.disabled = true;
    savePickBtn.disabled = true;
  }
}

async function refresh() {
  try {
    const data = await readCalendarStatus();
    renderStatus(data);
    if (isHost()) await fillCalendarPick(data.calendarId || "");
    connectBtn.disabled = !isHost();
    saveClientBtn.disabled = !isHost();
    disconnectBtn.disabled = !isHost();
  } catch (error) {
    setStatus("Could not load calendar status.");
  }
}

async function saveClient() {
  if (!isHost()) return;
  const clientId = clientIdInput.value.trim();
  const clientSecret = clientSecretInput.value.trim();
  if (!clientId || !clientSecret) {
    setStatus("Enter both client ID and client secret.");
    return;
  }
  saveClientBtn.disabled = true;
  try {
    const response = await fetch("calendar/credentials.json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clientId, clientSecret }),
    });
    if (!response.ok) {
      setStatus("Could not save the client. Check Keychain access on this Mac.");
      return;
    }
    clientSecretInput.value = "";
    setStatus("Client saved. Connect with Google next.");
  } catch (error) {
    setStatus("Could not reach Slate.");
  } finally {
    saveClientBtn.disabled = false;
    refresh();
  }
}

function connectGoogle() {
  if (!isHost()) return;
  location.href = "oauth/start";
}

async function savePick() {
  const calendarId = pickSelect.value.trim();
  if (!calendarId || !isHost()) return;
  savePickBtn.disabled = true;
  try {
    const response = await fetch("calendar/select.json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ calendarId }),
    });
    if (!response.ok) {
      setStatus("Could not save the calendar choice.");
      return;
    }
    const data = await response.json();
    renderStatus(data);
  } catch (error) {
    setStatus("Could not reach Slate.");
  } finally {
    savePickBtn.disabled = false;
  }
}

async function disconnect() {
  if (!isHost()) return;
  disconnectBtn.disabled = true;
  try {
    await fetch("calendar/disconnect.json", { method: "POST", cache: "no-store" });
    setStatus("Disconnected.");
    await fillCalendarPick("");
  } catch (error) {
    setStatus("Could not disconnect.");
  } finally {
    disconnectBtn.disabled = false;
    refresh();
  }
}

if (!isHost()) {
  hostPanel.hidden = false;
  setupPanel.hidden = true;
} else {
  hostPanel.hidden = true;
  setupPanel.hidden = false;
  if (remoteNote) remoteNote.hidden = true;
}

const params = new URLSearchParams(location.search);
if (params.get("connected") === "1") setStatus("Google connected. Choose a calendar below.");
if (params.get("error")) setStatus("Connect did not finish. Try again.");

saveClientBtn?.addEventListener("click", saveClient);
connectBtn?.addEventListener("click", connectGoogle);
savePickBtn?.addEventListener("click", savePick);
disconnectBtn?.addEventListener("click", disconnect);

refresh();
