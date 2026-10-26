const MAX = 5;
const listEl = document.getElementById("apps-list");
const countEl = document.getElementById("apps-count");
const msgEl = document.getElementById("apps-msg");
const saveBtn = document.getElementById("apps-save");

let catalog = [];
let selected = [];

function updateCount() {
  if (countEl) countEl.textContent = `${selected.length} of ${MAX}`;
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
  updateCount();
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
    const name = document.createElement("span");
    name.className = "nm";
    name.textContent = item.name;
    row.append(input, name);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (selected.length >= MAX && !selected.includes(item.id)) {
          input.checked = false;
          if (msgEl) msgEl.textContent = `Choose at most ${MAX} apps besides Dashboard.`;
          return;
        }
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
  const result = await saveSettings({ homeApps: selected });
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
  if (msgEl) msgEl.textContent = "Saved. Open Home to see the new tiles.";
}

async function init() {
  try {
    const [cat, settings] = await Promise.all([readJson("apps-catalog.json"), loadSettings()]);
    catalog = Array.isArray(cat) ? cat.filter((item) => item && item.id) : [];
    selected = Array.isArray(settings.homeApps) ? settings.homeApps.slice(0, MAX) : [];
    renderList();
  } catch (err) {
    if (msgEl) msgEl.textContent = "Could not load the app list.";
  }
}

if (saveBtn) saveBtn.addEventListener("click", persistApps);
init();
