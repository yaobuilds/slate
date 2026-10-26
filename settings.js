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

function wireSettingsPinForm(onSuccess) {
  const form = pinForm();
  if (!form) return;
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
    if (typeof onSuccess === "function") onSuccess();
  });
}
