const listEl = document.getElementById("apps-list");
const orderListEl = document.getElementById("apps-order-list");
const orderEmptyEl = document.getElementById("apps-order-empty");
const countEl = document.getElementById("apps-count");
const msgEl = document.getElementById("apps-msg");
const saveBtn = document.getElementById("apps-save");
const tileSizeEl = document.getElementById("tile-size");

let catalog = [];
let selected = [];
let tileSize = "auto";

function isTvSurface() {
  return !!window.SlateTV || /Android TV|Google TV/i.test(navigator.userAgent || "");
}

function catalogName(id) {
  const item = catalog.find((entry) => entry.id === id);
  return item && item.name ? item.name : id;
}

function updateCount() {
  if (countEl) countEl.textContent = `${selected.length} of ${catalog.length}`;
}

function moveSelected(id, delta) {
  const index = selected.indexOf(id);
  if (index < 0) return;
  const next = index + delta;
  if (next < 0 || next >= selected.length) return;
  const copy = selected.slice();
  const swap = copy[next];
  copy[next] = copy[index];
  copy[index] = swap;
  selected = copy;
  renderOrderList();
  if (msgEl) msgEl.textContent = "";
}

function renderOrderList() {
  if (!orderListEl) return;
  orderListEl.replaceChildren();
  if (orderEmptyEl) orderEmptyEl.hidden = selected.length > 0;
  selected.forEach((id, index) => {
    const li = document.createElement("li");
    li.className = "settings-order-row";
    const name = document.createElement("span");
    name.className = "nm";
    name.textContent = catalogName(id);
    const btns = document.createElement("div");
    btns.className = "order-btns";
    const up = document.createElement("button");
    up.type = "button";
    up.textContent = "Up";
    up.disabled = index === 0;
    up.addEventListener("click", () => moveSelected(id, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.textContent = "Down";
    down.disabled = index === selected.length - 1;
    down.addEventListener("click", () => moveSelected(id, 1));
    btns.append(up, down);
    li.append(name, btns);
    orderListEl.append(li);
  });
  updateCount();
}

function syncRows() {
  if (!listEl) return;
  listEl.querySelectorAll(".settings-row").forEach((row) => {
    const id = row.dataset.id;
    const on = selected.includes(id);
    row.classList.toggle("is-on", on);
    const input = row.querySelector("input");
    if (input) input.checked = on;
  });
  renderOrderList();
}

function renderList() {
  if (!listEl) return;
  listEl.replaceChildren();
  for (const item of catalog) {
    const row = document.createElement("label");
    row.className = "settings-row";
    row.dataset.id = item.id;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "app";
    input.value = item.id;
    const tvOnly = item.id === "google-tv" && !isTvSurface();
    input.disabled = tvOnly;
    const name = document.createElement("span");
    name.className = "nm";
    name.textContent = tvOnly ? `${item.name} (TV only)` : item.name;
    if (tvOnly) row.classList.add("is-disabled");
    row.append(input, name);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!selected.includes(item.id)) selected.push(item.id);
      } else {
        selected = selected.filter((id) => id !== item.id);
      }
      if (msgEl) msgEl.textContent = "";
      syncRows();
    });
    listEl.append(row);
  }
  syncRows();
}

async function persistApps() {
  if (tileSizeEl) tileSize = tileSizeEl.value === "large" ? "large" : "auto";
  const result = await saveSettings({ homeApps: selected, tileSize });
  if (result.error === "pin") {
    wireSettingsPinForm(persistApps);
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
  if (Array.isArray(result.homeApps)) {
    const known = new Set(catalog.map((item) => item.id));
    selected = result.homeApps.filter((id) => known.has(id));
    syncRows();
  }
  if (typeof result.tileSize === "string") {
    tileSize = result.tileSize;
    if (tileSizeEl) tileSizeEl.value = tileSize;
  }
  if (msgEl) {
    msgEl.textContent = selected.length
      ? "Saved. Open Home to see the new tiles."
      : "Saved. Home will show Dashboard only until you pick apps.";
  }
}

async function init() {
  try {
    const [cat, settings] = await Promise.all([readJson("apps-catalog.json"), loadSettings()]);
    catalog = Array.isArray(cat) ? cat.filter((item) => item && item.id) : [];
    const known = new Set(catalog.map((item) => item.id));
    const raw = Array.isArray(settings.homeApps) ? settings.homeApps : [];
    selected = raw.filter((id, index) => known.has(id) && raw.indexOf(id) === index);
    tileSize = settings.tileSize === "large" ? "large" : "auto";
    if (tileSizeEl) tileSizeEl.value = tileSize;
    renderList();
  } catch (err) {
    if (msgEl) msgEl.textContent = "Could not load the app list.";
  }
}

if (saveBtn) saveBtn.addEventListener("click", persistApps);
init();
