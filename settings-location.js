const readout = document.getElementById("loc-readout");
const lockedEl = document.getElementById("loc-locked");
const detectBtn = document.getElementById("loc-detect");
const saveBtn = document.getElementById("loc-save");
const msgEl = document.getElementById("loc-msg");

let draft = {
  lat: 40.7128,
  lon: -74.0060,
  label: "New York, NY",
  timezone: "America/New_York",
  locked: false,
};

function showDraft() {
  if (!readout) return;
  const mode = draft.locked ? "Locked" : "Auto-detect when unlocked";
  readout.textContent = `${draft.label} (${draft.lat}, ${draft.lon}) · ${mode}`;
  if (lockedEl) lockedEl.checked = draft.locked;
}

async function reversePlaceLabel(lat, lon) {
  try {
    const url =
      "/place.json?lat=" + encodeURIComponent(String(lat)) +
      "&lon=" + encodeURIComponent(String(lon));
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (typeof data.label === "string" && data.label.trim()) return data.label.trim();
  } catch (err) {
    /* Fall back to coordinates below. */
  }
  return `${Number(lat).toFixed(2)}, ${Number(lon).toFixed(2)}`;
}

function detectDeviceLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: Math.round(pos.coords.latitude * 100) / 100,
        lon: Math.round(pos.coords.longitude * 100) / 100,
      }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 12000, maximumAge: 0 },
    );
  });
}

async function detectNow() {
  if (msgEl) msgEl.textContent = "Finding location…";
  const hit = await detectDeviceLocation();
  if (!hit) {
    if (msgEl) msgEl.textContent = "Could not detect location. Check browser permission.";
    return;
  }
  draft.lat = hit.lat;
  draft.lon = hit.lon;
  draft.label = await reversePlaceLabel(hit.lat, hit.lon);
  if (msgEl) msgEl.textContent = "";
  showDraft();
}

async function persistLocation() {
  draft.locked = !!(lockedEl && lockedEl.checked);
  const result = await saveSettings({ location: draft });
  if (result.error === "pin") {
    wireSettingsPinForm(persistLocation);
    return;
  }
  if (result.error === "slow") {
    if (msgEl) msgEl.textContent = "Wait a moment and try again.";
    return;
  }
  if (result.error) {
    if (msgEl) msgEl.textContent = "Could not save.";
    return;
  }
  if (msgEl) msgEl.textContent = "Saved. Reload Home for weather at this place.";
}

async function init() {
  try {
    const settings = await loadSettings();
    if (settings.location && typeof settings.location === "object") {
      draft = { ...draft, ...settings.location };
    }
    showDraft();
  } catch (err) {
    if (readout) readout.textContent = "Could not load settings.";
  }
}

if (detectBtn) detectBtn.addEventListener("click", detectNow);
if (saveBtn) saveBtn.addEventListener("click", persistLocation);
if (lockedEl) {
  lockedEl.addEventListener("change", () => {
    draft.locked = lockedEl.checked;
    showDraft();
  });
}
init();
