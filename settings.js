async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function loadSettings() {
  const response = await fetch("settings.json", { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function saveSettings(body) {
  try {
    const response = await fetch("settings.json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (response.status === 401) return { error: "pin" };
    if (response.status === 429) return { error: "slow" };
    if (!response.ok) return { error: "bad" };
    return await response.json();
  } catch (err) { return { error: "offline" }; }
}

function pinForm() {
  return document.getElementById("settings-pin-form");
}

let pinReturnFocus = null;

function showSettingsPin(message) {
  const form = pinForm();
  if (!form) return;
  if (form.hidden) pinReturnFocus = document.activeElement;
  form.hidden = false;
  const err = document.getElementById("settings-pin-error");
  if (err && message) err.textContent = message;
  const input = document.getElementById("settings-pin-input");
  if (input) input.focus();
}

function settingsBack(event) {
  if (!document.documentElement.classList.contains("page-settings")) return;
  const backKeys = new Set(["Escape", "Backspace", "BrowserBack", "GoBack", "Back"]);
  const backCodes = new Set([4, 461, 10009]);
  if (!backKeys.has(event.key) && !backCodes.has(event.keyCode)) return;
  const active = document.activeElement;
  const editable = active && (
    active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable
  );
  if (event.key === "Backspace" && editable && !backCodes.has(event.keyCode)) return;

  event.preventDefault();
  event.stopPropagation();
  const form = pinForm();
  if (form && !form.hidden) {
    form.hidden = true;
    const input = document.getElementById("settings-pin-input");
    const error = document.getElementById("settings-pin-error");
    if (input) {
      input.value = "";
      input.blur();
    }
    if (error) error.textContent = "";
    if (pinReturnFocus && typeof pinReturnFocus.focus === "function") {
      pinReturnFocus.focus({ preventScroll: true });
    }
    return;
  }
  const link = document.querySelector("a.settings-back[href]");
  if (link) location.href = link.href;
}

document.addEventListener("keydown", settingsBack, true);

function settingsFocusables() {
  return [...document.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
  )].filter((el) => {
    if (el.offsetParent === null) return false;
    const form = pinForm();
    if (form && !form.hidden) return form.contains(el);
    return !form || !form.contains(el);
  });
}

function moveSettingsFocus(direction) {
  const items = settingsFocusables();
  if (!items.length) return;
  const current = document.activeElement;
  const rect = current && current.getBoundingClientRect ? current.getBoundingClientRect() : null;
  if (!rect || !items.includes(current)) {
    items[0].focus({ preventScroll: true });
    return;
  }
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  let next = null;
  let score = Infinity;
  for (const item of items) {
    if (item === current) continue;
    const target = item.getBoundingClientRect();
    const dx = target.left + target.width / 2 - x;
    const dy = target.top + target.height / 2 - y;
    if (direction === "ArrowLeft" && dx >= -8) continue;
    if (direction === "ArrowRight" && dx <= 8) continue;
    if (direction === "ArrowUp" && dy >= -8) continue;
    if (direction === "ArrowDown" && dy <= 8) continue;
    const primary = direction === "ArrowLeft" || direction === "ArrowRight" ? Math.abs(dx) : Math.abs(dy);
    const secondary = direction === "ArrowLeft" || direction === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
    const candidateScore = primary * 1000 + secondary;
    if (candidateScore < score) {
      next = item;
      score = candidateScore;
    }
  }
  if (next) {
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

document.addEventListener("keydown", (event) => {
  if (!document.documentElement.classList.contains("page-settings")) return;
  if (event.key === "Enter" && event.target && event.target.id === "settings-pin-input") return;
  const active = document.activeElement;
  const editable = active && (
    active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.tagName === "SELECT" || active.isContentEditable
  );
  if (editable) return;
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    document.body.classList.add("show-focus");
    moveSettingsFocus(event.key);
    return;
  }
  if (event.key === "Enter" && active && typeof active.click === "function") {
    event.preventDefault();
    active.click();
  }
});

function updateSettingsInputFocus() {
  const active = document.activeElement;
  const focused = !!(
    active && active.matches && active.matches("input, textarea, select, [contenteditable='true']")
  );
  const bridge = window.SlateTV;
  if (bridge && typeof bridge.setInputFocused === "function") {
    bridge.setInputFocused(focused);
  }
}

document.addEventListener("focusin", updateSettingsInputFocus);
document.addEventListener("focusout", () => setTimeout(updateSettingsInputFocus, 0));
const settingsBackLink = document.querySelector("a.settings-back[href]");
if (settingsBackLink) settingsBackLink.focus({ preventScroll: true });

async function unlockSettingsPin(pin) {
  try {
    const response = await fetch("unlock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin }),
    cache: "no-store",
  });
    if (response.status === 429) return "slow";
    if (!response.ok) return "pin";
    return "ok";
  } catch (err) { return "offline"; }
}

async function saveWithPin(body) {
  let result = await saveSettings(body);
  if (result.error !== "pin") return result;
  showSettingsPin("Enter the PIN from this Mac to save on Wi-Fi.");
  return result;
}

let pinSaveHandler = null;

function wireSettingsPinForm(onSuccess) {
  const form = pinForm();
  if (!form) return;
  pinSaveHandler = onSuccess;
  showSettingsPin("Enter the PIN from this Mac to save on Wi-Fi.");
  if (form.dataset.wired === "1") return;
  form.dataset.wired = "1";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("settings-pin-input");
    const err = document.getElementById("settings-pin-error");
    const pin = input && input.value.trim();
    if (!/^[0-9]{4,8}$/.test(pin || "")) {
      if (err) err.textContent = "Enter the 4 to 8 digit PIN from this Mac.";
      return;
    }
    if (err) err.textContent = "";
    const status = await unlockSettingsPin(pin);
    if (status === "offline") {
      if (err) err.textContent = "Could not reach Slate. Keep this page open and try again.";
      return;
    }
    if (status === "slow") {
      if (err) err.textContent = "Wait a moment and try again.";
      return;
    }
    if (status !== "ok") {
      if (err) err.textContent = "That PIN didn't work.";
      return;
    }
    if (input) input.value = "";
    form.hidden = true;
    if (typeof pinSaveHandler === "function") pinSaveHandler();
  });
}

let signOutBusy = false;

async function signOutOnLan() {
  if (signOutBusy) return;
  const msgEl = document.getElementById("sign-out-msg");
  const btn = document.getElementById("settings-sign-out");
  signOutBusy = true;
  if (btn) btn.disabled = true;
  try {
    const response = await fetch("/lock", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.ok) {
      if (msgEl) {
        msgEl.textContent =
          "Signed out. Show all on Dashboard will ask for the PIN again on Wi-Fi.";
      }
      return;
    }
    if (msgEl) {
      msgEl.textContent = response.status === 404
        ? "Sign out only works when the server runs with --lan (iPad or phone on Wi-Fi)."
        : "Could not sign out.";
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = "Could not reach the server.";
  } finally {
    signOutBusy = false;
    if (btn) btn.disabled = false;
  }
}

function wireSettingsSignOut() {
  const btn = document.getElementById("settings-sign-out");
  if (!btn) return;
  btn.addEventListener("click", signOutOnLan);
}

function applyHidePointer(hide) {
  document.body.classList.toggle("hide-pointer", hide);
  if (hide) document.body.classList.remove("has-mouse");
  else if (document.documentElement.classList.contains("page-settings")) {
    document.body.classList.add("has-mouse");
  }
}

async function persistHidePointer(hide) {
  const msgEl = document.getElementById("pointer-msg");
  const result = await saveSettings({ hidePointer: hide });
  if (result.error === "pin") {
    wireSettingsPinForm(() => persistHidePointer(hide));
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
  applyHidePointer(result.hidePointer === true);
  const input = document.getElementById("pointer-toggle");
  if (input) input.checked = result.hidePointer === true;
  if (msgEl) msgEl.textContent = result.hidePointer ? "Pointer hidden." : "Pointer shows when the mouse moves.";
}

function wirePointerToggle() {
  const input = document.getElementById("pointer-toggle");
  if (!input) return;
  input.addEventListener("change", () => {
    persistHidePointer(input.checked);
  });
}

async function bootPointerSetting() {
  try {
    const settings = await loadSettings();
    const hide = settings.hidePointer === true;
    applyHidePointer(hide);
    const input = document.getElementById("pointer-toggle");
    if (input) input.checked = hide;
  } catch (err) {
    /* Leave the pointer on the default show-after-move path. */
  }
}

function isTvSurface() {
  return !!window.SlateTV || /Android TV|Google TV|SlateTV/i.test(navigator.userAgent || "");
}

async function remoteSettingsJson(url, options) {
  const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options });
  let body = null;
  try { body = await response.json(); } catch (err) { body = null; }
  return { response, body };
}

function wireTvRemotePanel() {
  const panel = document.getElementById("tv-remote-panel");
  if (!panel || isTvSurface()) return;
  panel.hidden = false;

  document.getElementById("remote-settings-gen")?.addEventListener("click", async () => {
    const msg = document.getElementById("remote-settings-phone-code");
    const { response, body } = await remoteSettingsJson("/remote/v1/pairing.json", { method: "POST" });
    if (!response.ok) {
      if (msg) msg.textContent = response.status === 403 ? "Start the server with --lan on Wi-Fi." : "Could not generate a code.";
      return;
    }
    if (msg) msg.textContent = body.code ? `Phone code: ${body.code} (five minutes)` : "";
  });

  document.getElementById("remote-settings-show-code")?.addEventListener("click", async () => {
    const msg = document.getElementById("remote-settings-tv-msg");
    const { response, body } = await remoteSettingsJson("/remote/v1/tv-pair.json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (response.status === 409 && body && body.error === "no-host") {
      if (msg) msg.textContent = "Open Slate on the TV first.";
      return;
    }
    if (!response.ok) {
      if (msg) msg.textContent = "Could not start TV pairing.";
      return;
    }
    if (msg) msg.textContent = "Enter the code shown on the TV.";
  });

  document.getElementById("remote-settings-send-code")?.addEventListener("click", async () => {
    const input = document.getElementById("remote-settings-tv-code");
    const msg = document.getElementById("remote-settings-tv-msg");
    const code = input && input.value.trim();
    if (!/^[0-9a-fA-F]{6}$/.test(code || "")) {
      if (msg) msg.textContent = "Enter the six-character TV code.";
      return;
    }
    const { response } = await remoteSettingsJson("/remote/v1/tv-code.json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (response.status === 401) {
      if (msg) msg.textContent = "That code did not match.";
      return;
    }
    if (!response.ok) {
      if (msg) msg.textContent = "Could not send the code.";
      return;
    }
    if (msg) msg.textContent = "TV paired.";
  });

  const toggle = document.getElementById("remote-enabled-toggle");
  toggle?.addEventListener("change", async () => {
    const msg = document.getElementById("remote-enabled-msg");
    const result = await saveWithPin({ remoteEnabled: toggle.checked });
    if (result.error === "pin") return;
    if (result.error) {
      if (msg) msg.textContent = "Could not save.";
      return;
    }
    if (msg) msg.textContent = result.remoteEnabled === false ? "Remote disabled." : "Remote enabled.";
  });

  loadSettings().then((settings) => {
    if (toggle) toggle.checked = settings.remoteEnabled !== false;
  }).catch(() => {});
}

wireSettingsSignOut();
wirePointerToggle();
wireTvRemotePanel();
if (document.documentElement.classList.contains("page-settings")) {
  document.body.classList.add("has-mouse");
}
bootPointerSetting();

function refreshHomeRouting() {
  const bridge = window.SlateTV;
  const panel = document.getElementById("home-routing-panel");
  if (!panel || !bridge || typeof bridge.homeRoutingStatus !== "function") return;
  panel.hidden = false;
  const status = bridge.homeRoutingStatus();
  document.getElementById("home-routing-toggle").checked = status === "active";
  document.getElementById("home-routing-status").textContent = {
    active: "Home returns to Slate. The Google TV tile still opens Google TV.",
    off: "Off. The Home button can open Google TV.",
    "permission-needed": "Enable Slate Home button in Accessibility settings to route Home to Slate.",
  }[status] || "Home button helper unavailable.";
}
document.getElementById("home-routing-toggle")?.addEventListener("change", event => {
  window.SlateTV.setHomeRoutingEnabled(event.target.checked);
  setTimeout(refreshHomeRouting, 250);
});
document.getElementById("home-routing-manage")?.addEventListener("click", () => window.SlateTV.openHomeRoutingSettings());
addEventListener("focus", refreshHomeRouting);
refreshHomeRouting();
