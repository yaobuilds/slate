const serverState = document.getElementById("server-state");
const serverDetail = document.getElementById("server-detail");
const internetState = document.getElementById("internet-state");
const internetDetail = document.getElementById("internet-detail");
const lanState = document.getElementById("lan-state");
const lanDetail = document.getElementById("lan-detail");
const networkMessage = document.getElementById("network-message");
const deviceList = document.getElementById("network-device-list");
const refreshButton = document.getElementById("network-refresh");
const scanButton = document.getElementById("network-scan");
let networkBusy = false;

function setStatus(element, label, state) {
  if (!element) return;
  element.textContent = label;
  element.dataset.state = state;
}

async function checkServer() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok || result.ok !== true || result.service !== "slate") throw new Error("unavailable");
    setStatus(serverState, "Online", "good");
    if (serverDetail) serverDetail.textContent = `${location.host} · health check passed`;
  } catch (err) {
    setStatus(serverState, "Offline", "bad");
    if (serverDetail) serverDetail.textContent = "The Slate server did not answer.";
  }
}

async function checkInternet() {
  if (!navigator.onLine) {
    setStatus(internetState, "Offline", "bad");
    if (internetDetail) internetDetail.textContent = "This device reports no network connection.";
    return;
  }
  try {
    const response = await fetch(
      "https://api.open-meteo.com/v1/forecast?latitude=40.7128&longitude=-74.0060&current=temperature_2m&timezone=UTC",
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(String(response.status));
    setStatus(internetState, "Online", "good");
    if (internetDetail) internetDetail.textContent = "Open-Meteo responded successfully.";
  } catch (err) {
    setStatus(internetState, "Unavailable", "bad");
    if (internetDetail) internetDetail.textContent = "Could not reach the weather service.";
  }
}

function renderDevices(result) {
  if (!deviceList) return;
  deviceList.replaceChildren();
  const devices = Array.isArray(result.devices) ? result.devices : [];
  for (const device of devices) {
    const item = document.createElement("li");
    item.className = `network-device${device.local ? " local" : ""}`;
    const name = document.createElement("span");
    name.className = "network-device-name";
    name.textContent = device.name || (device.local ? "This Mac" : "Device");
    const ip = document.createElement("span");
    ip.className = "network-device-ip";
    ip.textContent = device.ip;
    item.append(name, ip);
    deviceList.append(item);
  }
  if (!devices.length) {
    const item = document.createElement("li");
    item.className = "network-device-name";
    item.textContent = "No devices are currently known to the Mac.";
    deviceList.append(item);
  }
  if (lanState) setStatus(lanState, `${devices.length} ${devices.length === 1 ? "device" : "devices"}`, "good");
  if (lanDetail) {
    const network = result.network ? `${result.network} · ` : "";
    lanDetail.textContent = `${network}${result.interface || "Wi-Fi"} · Mac ${result.address || "unknown"}`;
  }
}

async function loadDevices(scan) {
  if (networkBusy) return;
  networkBusy = true;
  if (scanButton) scanButton.disabled = true;
  if (networkMessage) networkMessage.textContent = scan ? "Scanning the current private Wi-Fi subnet…" : "Loading devices known to this Mac…";
  try {
    const response = await fetch(`/network.json${scan ? "?scan=1" : ""}`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok || result.ok !== true) throw new Error(result.error || "Could not read the local network.");
    renderDevices(result);
    const found = Array.isArray(result.devices) ? result.devices.length : 0;
    const cached = result.cached ? " Recent scan reused." : "";
    if (networkMessage) {
      networkMessage.textContent = scan
        ? `Found ${found} ${found === 1 ? "device" : "devices"} on ${result.network || "Wi-Fi"}.${cached}`
        : `${found} ${found === 1 ? "device is" : "devices are"} in the Mac’s current network table.`;
    }
  } catch (err) {
    if (networkMessage) networkMessage.textContent = err && err.message ? err.message : "Could not load the Wi-Fi device list.";
    if (!scan && lanState) setStatus(lanState, "Unavailable", "bad");
  } finally {
    networkBusy = false;
    if (scanButton) scanButton.disabled = false;
  }
}

async function refreshAll() {
  if (refreshButton) refreshButton.disabled = true;
  await Promise.all([checkServer(), checkInternet(), loadDevices(false)]);
  if (refreshButton) refreshButton.disabled = false;
}

if (refreshButton) refreshButton.addEventListener("click", refreshAll);
if (scanButton) scanButton.addEventListener("click", () => loadDevices(true));

function networkFocusables() {
  return [...document.querySelectorAll(".network-back, .network-button:not([disabled]), #network-device-list")]
    .filter((el) => el.offsetParent !== null);
}

function moveNetworkFocus(direction) {
  const items = networkFocusables();
  if (!items.length) return;
  const current = document.activeElement;
  if (!items.includes(current)) {
    items[0].focus({ preventScroll: true });
    return;
  }
  const rect = current.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  let best = null;
  let bestScore = Infinity;
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
    const candidate = primary * 1000 + secondary;
    if (candidate < bestScore) {
      best = item;
      bestScore = candidate;
    }
  }
  if (best) best.focus({ preventScroll: true });
}

document.addEventListener("keydown", (event) => {
  if (["Escape", "Backspace", "BrowserBack", "GoBack", "Back"].includes(event.key)
    || [4, 461, 10009].includes(event.keyCode)) {
    event.preventDefault();
    location.href = "dashboard.html";
    return;
  }
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    if (document.activeElement === deviceList && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      deviceList.scrollBy({ top: event.key === "ArrowDown" ? 180 : -180, behavior: "smooth" });
      return;
    }
    moveNetworkFocus(event.key);
    return;
  }
  if (event.key === "Enter") {
    const active = document.activeElement;
    if (active && typeof active.click === "function") {
      event.preventDefault();
      active.click();
    }
  }
});

const backLink = document.querySelector(".network-back");
if (backLink) backLink.focus({ preventScroll: true });
refreshAll();
