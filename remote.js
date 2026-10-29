async function remoteJson(url, options) {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
  });
  let body = null;
  try {
    body = await response.json();
  } catch (err) {
    body = null;
  }
  return { response, body };
}

function setMsg(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || "";
}

function serviceLine(status, tvOnline) {
  if (status === "ready") return "Keys reach the TV.";
  if (tvOnline) {
    return "Arrow keys reach Slate until the TV code is entered. Volume needs that code.";
  }
  return "Waiting for the TV page to come online.";
}

async function refreshStatus() {
  const { response, body } = await remoteJson("/remote/v1/status.json");
  if (!response.ok) return;
  const line = document.getElementById("remote-service-line");
  if (line) line.textContent = serviceLine(body.tvService, body.tvOnline);
  const control = document.getElementById("remote-control-panel");
  const pairPanel = document.getElementById("remote-pair-panel");
  if (body.paired && control) control.hidden = false;
  if (body.paired && pairPanel) pairPanel.hidden = true;
}

async function sendCommand(payload) {
  const { response, body } = await remoteJson("/remote/v1/command.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.status === 401) {
    setMsg("remote-pair-msg", "Pair this phone first.");
    document.getElementById("remote-control-panel").hidden = true;
    document.getElementById("remote-pair-panel").hidden = false;
    return;
  }
  if (response.status === 409 && body && body.error === "tv") {
    setMsg("remote-tv-msg", "Volume needs the TV pairing code.");
    return;
  }
  return body;
}

document.getElementById("remote-gen-code")?.addEventListener("click", async () => {
  const { response, body } = await remoteJson("/remote/v1/pairing.json", { method: "POST" });
  if (!response.ok) {
    setMsg("remote-pair-msg", response.status === 403 ? "Use Slate with --lan on Wi-Fi." : "Could not generate a code.");
    return;
  }
  const codeEl = document.getElementById("remote-phone-code");
  if (codeEl) codeEl.textContent = body.code ? `Code: ${body.code}` : "";
  setMsg("remote-pair-msg", "Enter this code below within five minutes.");
});

document.getElementById("remote-pair-btn")?.addEventListener("click", async () => {
  const input = document.getElementById("remote-pair-input");
  const code = input && input.value.trim();
  if (!/^[0-9]{6}$/.test(code || "")) {
    setMsg("remote-pair-msg", "Enter the six-digit code.");
    return;
  }
  const { response } = await remoteJson("/remote/v1/pair.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!response.ok) {
    setMsg("remote-pair-msg", "That code did not work.");
    return;
  }
  setMsg("remote-pair-msg", "");
  await refreshStatus();
});

document.getElementById("remote-show-code")?.addEventListener("click", async () => {
  setMsg("remote-tv-msg", "Starting TV pairing…");
  const { response, body } = await remoteJson("/remote/v1/tv-pair.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (response.status === 409 && body && body.error === "no-host") {
    setMsg("remote-tv-msg", "Open Slate on the TV first so this Mac learns its address.");
    return;
  }
  if (!response.ok) {
    setMsg("remote-tv-msg", "Could not reach the TV service.");
    return;
  }
  setMsg("remote-tv-msg", "Enter the code shown on the TV.");
});

document.getElementById("remote-send-code")?.addEventListener("click", async () => {
  const input = document.getElementById("remote-tv-code");
  const code = input && input.value.trim();
  if (!/^[0-9a-fA-F]{6}$/.test(code || "")) {
    setMsg("remote-tv-msg", "Enter the six-character code from the TV.");
    return;
  }
  const { response } = await remoteJson("/remote/v1/tv-code.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (response.status === 401) {
    setMsg("remote-tv-msg", "That code did not match.");
    return;
  }
  if (!response.ok) {
    setMsg("remote-tv-msg", "Could not send the code.");
    return;
  }
  setMsg("remote-tv-msg", "TV paired.");
  await refreshStatus();
});

document.querySelectorAll("[data-key]").forEach((btn) => {
  btn.addEventListener("click", () => {
    sendCommand({ type: "key", key: btn.getAttribute("data-key") });
  });
});

document.querySelectorAll("[data-bridge]").forEach((btn) => {
  btn.addEventListener("click", () => {
    sendCommand({ type: "bridge", action: btn.getAttribute("data-bridge") });
  });
});

refreshStatus();
setInterval(refreshStatus, 5000);
