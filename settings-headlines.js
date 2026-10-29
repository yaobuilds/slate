const builtinList = document.getElementById("headlines-builtin");
const customList = document.getElementById("headlines-custom");
const customCountEl = document.getElementById("headlines-custom-count");
const nameInput = document.getElementById("headlines-name");
const urlInput = document.getElementById("headlines-url");
const addBtn = document.getElementById("headlines-add");
const addBlock = document.getElementById("headlines-add-block");
const saveBtn = document.getElementById("headlines-save");
const msgEl = document.getElementById("headlines-msg");

const CUSTOM_MAX = 8;

let draft = {
  builtin: [],
  custom: [],
};

function updateCustomCount() {
  if (!customCountEl) return;
  const n = draft.custom.length;
  customCountEl.textContent = `${n} custom feed${n === 1 ? "" : "s"}`;
  if (addBtn) addBtn.disabled = n >= CUSTOM_MAX;
  if (addBlock) addBlock.classList.toggle("is-disabled", n >= CUSTOM_MAX);
}

function renderBuiltin() {
  if (!builtinList) return;
  builtinList.replaceChildren();
  for (const row of draft.builtin) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = "settings-row";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!row.enabled;
    input.addEventListener("change", () => {
      row.enabled = input.checked;
      label.classList.toggle("is-on", input.checked);
      if (msgEl) msgEl.textContent = "";
    });
    const text = document.createElement("span");
    text.className = "nm";
    text.textContent = row.name;
    const url = document.createElement("span");
    url.className = "settings-lan-copy";
    url.style.marginLeft = "0.5rem";
    url.textContent = row.url;
    label.classList.toggle("is-on", input.checked);
    label.append(input, text, url);
    li.append(label);
    builtinList.append(li);
  }
}

function removeCustom(index) {
  draft.custom.splice(index, 1);
  renderCustom();
  if (msgEl) msgEl.textContent = "";
}

function renderCustom() {
  if (!customList) return;
  customList.replaceChildren();
  draft.custom.forEach((row, index) => {
    const li = document.createElement("li");
    li.className = "settings-order-row";
    const label = document.createElement("label");
    label.className = "settings-row";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = row.enabled !== false;
    input.addEventListener("change", () => {
      row.enabled = input.checked;
      label.classList.toggle("is-on", input.checked);
      if (msgEl) msgEl.textContent = "";
    });
    const text = document.createElement("span");
    text.className = "nm";
    text.textContent = row.name;
    label.classList.toggle("is-on", input.checked);
    label.append(input, text);
    const meta = document.createElement("span");
    meta.className = "settings-lan-copy";
    meta.textContent = row.url;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => removeCustom(index));
    li.append(label, meta, remove);
    customList.append(li);
  });
  updateCustomCount();
}

function addCustomFeed() {
  if (draft.custom.length >= CUSTOM_MAX) {
    if (msgEl) msgEl.textContent = "Custom feed limit reached.";
    return;
  }
  const name = nameInput && nameInput.value ? nameInput.value.trim() : "";
  const url = urlInput && urlInput.value ? urlInput.value.trim() : "";
  if (!name) {
    if (msgEl) msgEl.textContent = "Enter a name for the feed.";
    return;
  }
  if (!url.startsWith("https://")) {
    if (msgEl) msgEl.textContent = "RSS URL must start with https://";
    return;
  }
  draft.custom.push({ name, url, enabled: true });
  if (nameInput) nameInput.value = "";
  if (urlInput) urlInput.value = "";
  if (msgEl) msgEl.textContent = "";
  renderCustom();
}

function headlinesPayload() {
  const feeds = {};
  for (const row of draft.builtin) {
    if (row.id) feeds[row.id] = !!row.enabled;
  }
  return {
    headlines: {
      feeds,
      custom: draft.custom.map((row) => ({
        name: row.name,
        url: row.url,
        enabled: row.enabled !== false,
      })),
    },
  };
}

async function persistHeadlines() {
  const result = await saveSettings(headlinesPayload());
  if (result.error === "pin") {
    wireSettingsPinForm(persistHeadlines);
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
  if (result.headlines) {
    draft.builtin = Array.isArray(result.headlines.builtin) ? result.headlines.builtin : draft.builtin;
    draft.custom = Array.isArray(result.headlines.custom) ? result.headlines.custom : draft.custom;
    renderBuiltin();
    renderCustom();
  }
  if (msgEl) msgEl.textContent = "Saved. Dashboard headlines refresh within a few minutes.";
}

async function init() {
  try {
    const settings = await loadSettings();
    if (settings.headlines && typeof settings.headlines === "object") {
      const h = settings.headlines;
      draft.builtin = Array.isArray(h.builtin) ? h.builtin.map((row) => ({ ...row })) : [];
      draft.custom = Array.isArray(h.custom) ? h.custom.map((row) => ({ ...row })) : [];
    }
    renderBuiltin();
    renderCustom();
  } catch (err) {
    if (msgEl) msgEl.textContent = "Could not load settings.";
  }
}

if (addBtn) addBtn.addEventListener("click", addCustomFeed);
if (saveBtn) saveBtn.addEventListener("click", persistHeadlines);
init();
