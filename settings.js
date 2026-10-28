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
  const response = await fetch("settings.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401) return { error: "pin" };
  if (response.status === 429) return { error: "slow" };
  if (!response.ok) return { error: "bad" };
  return response.json();
}

function pinForm() {
  return document.getElementById("settings-pin-form");
}

function showSettingsPin(message) {
  const form = pinForm();
  if (!form) return;
  form.hidden = false;
  const err = document.getElementById("settings-pin-error");
  if (err && message) err.textContent = message;
  const input = document.getElementById("settings-pin-input");
  if (input) input.focus();
}

async function unlockSettingsPin(pin) {
  const response = await fetch("unlock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin }),
    cache: "no-store",
  });
  if (response.status === 429) return "slow";
  if (!response.ok) return "pin";
  return "ok";
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

wireSettingsSignOut();
wirePointerToggle();
if (document.documentElement.classList.contains("page-settings")) {
  document.body.classList.add("has-mouse");
}
bootPointerSetting();
