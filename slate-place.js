(function () {
  const DEVICE_KEY = "slate-device-place";
  const DISMISS_KEY = "slate-place-prompt-dismiss";
  const PROMPT_KM = 25;

  function finiteCoord(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function normalizePlace(raw) {
    if (!raw || typeof raw !== "object") return null;
    const lat = raw.lat;
    const lon = raw.lon;
    if (!finiteCoord(lat) || !finiteCoord(lon)) return null;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
    const label = typeof raw.label === "string" ? raw.label.trim() : "";
    const out = { lat, lon, label: label || `${lat.toFixed(2)}, ${lon.toFixed(2)}` };
    if (typeof raw.timezone === "string" && raw.timezone.includes("/")) out.timezone = raw.timezone;
    return out;
  }

  function readDevicePlace() {
    try {
      return normalizePlace(JSON.parse(localStorage.getItem(DEVICE_KEY) || "null"));
    } catch (err) {
      return null;
    }
  }

  function writeDevicePlace(place) {
    const normalized = normalizePlace(place);
    if (!normalized) return;
    try {
      localStorage.setItem(DEVICE_KEY, JSON.stringify(normalized));
    } catch (err) {
      /* Storage blocked. */
    }
  }

  function spotKey(lat, lon) {
    return `${Number(lat).toFixed(2)},${Number(lon).toFixed(2)}`;
  }

  function localDateKey(timeZone) {
    const tz = typeof timeZone === "string" && timeZone.includes("/") ? timeZone : "America/New_York";
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    } catch (err) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  function readDismissRecord() {
    try {
      const raw = JSON.parse(localStorage.getItem(DISMISS_KEY) || "null");
      if (!raw || typeof raw !== "object") return null;
      if (typeof raw.day !== "string" || typeof raw.spot !== "string") return null;
      return raw;
    } catch (err) {
      return null;
    }
  }

  function isPromptDismissed(lat, lon, timeZone) {
    const record = readDismissRecord();
    if (!record) return false;
    return record.day === localDateKey(timeZone) && record.spot === spotKey(lat, lon);
  }

  function dismissPrompt(lat, lon, timeZone) {
    try {
      localStorage.setItem(
        DISMISS_KEY,
        JSON.stringify({ day: localDateKey(timeZone), spot: spotKey(lat, lon) }),
      );
    } catch (err) {
      /* Storage blocked. */
    }
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const r = 6371;
    const p1 = (lat1 * Math.PI) / 180;
    const p2 = (lat2 * Math.PI) / 180;
    const dlat = ((lat2 - lat1) * Math.PI) / 180;
    const dlon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dlat / 2) * Math.sin(dlat / 2) +
      Math.cos(p1) * Math.cos(p2) * Math.sin(dlon / 2) * Math.sin(dlon / 2);
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function trafficJsonUrl() {
    const device = readDevicePlace();
    if (!device) return "traffic.json";
    return (
      "traffic.json?lat=" + encodeURIComponent(String(device.lat)) +
      "&lon=" + encodeURIComponent(String(device.lon))
    );
  }

  window.SlatePlace = {
    PROMPT_KM,
    readDevicePlace,
    writeDevicePlace,
    isPromptDismissed,
    dismissPrompt,
    haversineKm,
    trafficJsonUrl,
  };
})();
