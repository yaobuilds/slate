const gridEl = document.getElementById("theme-grid");
const msgEl = document.getElementById("theme-msg");
const saveBtn = document.getElementById("theme-save");

let presetKeys = [];
let presetMeta = {};
let paletteColors = {};
let current = "aurora";
let picked = "aurora";

function swatchRow(colors) {
  const row = document.createElement("div");
  row.className = "theme-swatches";
  for (const color of colors || []) {
    const dot = document.createElement("span");
    dot.style.background = color;
    row.append(dot);
  }
  return row;
}

function renderGrid() {
  if (!gridEl) return;
  gridEl.replaceChildren();
  for (const key of presetKeys) {
    const meta = presetMeta[key] || {};
    const card = document.createElement("label");
    card.className = "theme-card";
    card.dataset.key = key;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "theme";
    input.value = key;
    input.checked = key === picked;
    const name = document.createElement("span");
    name.className = "theme-name";
    name.textContent = meta.name || key;
    card.append(input, name);
    const pal = meta.palette || (key.endsWith("-still") ? key.replace("-still", "") : key);
    if (key !== "off" && paletteColors[pal]) {
      card.append(swatchRow(paletteColors[pal].colors));
    }
    card.classList.toggle("is-on", key === picked);
    card.addEventListener("click", () => {
      picked = key;
      gridEl.querySelectorAll(".theme-card").forEach((el) => {
        el.classList.toggle("is-on", el.dataset.key === picked);
      });
    });
    gridEl.append(card);
  }
}

async function persistTheme() {
  const result = await saveSettings({ ambientPreset: picked });
  if (result.error === "pin") {
    wireSettingsPinForm(persistTheme);
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
  location.href = "index.html";
}

async function init() {
  try {
    const [ambient, settings] = await Promise.all([readJson("ambient.json"), loadSettings()]);
    const presets = ambient.presets && typeof ambient.presets === "object" ? ambient.presets : {};
    presetKeys = Object.keys(presets);
    presetMeta = presets;
    paletteColors = ambient.palettes && typeof ambient.palettes === "object" ? ambient.palettes : {};
    current = typeof settings.ambientPreset === "string" ? settings.ambientPreset : ambient.preset;
    picked = current;
    renderGrid();
  } catch (err) {
    if (msgEl) msgEl.textContent = "Could not load themes.";
  }
}

if (saveBtn) saveBtn.addEventListener("click", persistTheme);
init();
