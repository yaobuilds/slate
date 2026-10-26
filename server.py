#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PORT = 8000
LOCAL = ROOT / "data.local.json"
PUBLIC = ROOT / "data.json"
SETTINGS_LOCAL = ROOT / "settings.local.json"
APPS_PUBLIC = ROOT / "apps.json"
CATALOG = ROOT / "apps-catalog.json"
AMBIENT = ROOT / "ambient.json"
DEFAULT_HOME_APPS = ["netflix", "hulu", "hbo", "youtube", "youtube-music"]
DEFAULT_AMBIENT_PRESET = "aurora"
DEFAULT_LOCATION = {
    "lat": 40.7128,
    "lon": -74.0060,
    "label": "New York, NY",
    "timezone": "America/New_York",
    "locked": False,
}
MAX_HOME_APPS = 5
PIN_PATH = ROOT / "pin.local"
PIN_RE = re.compile(r"^[0-9]{4,8}$")
FAIL_LIMIT = 5
LOCKOUT_S = 60
COOKIE_MAX_AGE = 7 * 24 * 60 * 60
PLACEHOLDER = {
    "updated": "2026-10-24T09:00:00-04:00",
    "today": [
        {"time": "9:00", "title": "Morning notes"},
        {"time": "12:30", "title": "Lunch"},
        {"time": "6:00", "title": "Evening walk"},
    ],
    "deadlines": [
        {"title": "Draft the outline", "due": "Friday"},
        {"title": "Return the books", "due": "Oct 30"},
    ],
    "money": {"note": "No bills due this week"},
}

PUBLISH_LOCK = threading.RLock()
STATE_LOCK = threading.Lock()
SESSIONS = set()
FAILS = {}
EXPECTED_PIN = ""
FULL_PAYLOAD = None
SETTINGS_STATE = {
    "homeApps": list(DEFAULT_HOME_APPS),
    "ambientPreset": DEFAULT_AMBIENT_PRESET,
    "location": dict(DEFAULT_LOCATION),
}
CATALOG_IDS = set()
AMBIENT_PRESETS = set()
NOMINATIM_UA = "SlateDashboard/1.0 (local personal dashboard)"
PLACE_LAST_CALL = 0.0
PLACE_LOCK = threading.Lock()


def write_public(text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if PUBLIC.exists() and PUBLIC.read_text(encoding="utf-8") == text:
        return
    PUBLIC.write_text(text, encoding="utf-8")


def guest_schedule(payload: dict) -> dict:
    """What Home and guest mode may see. Event titles are Busy, never the real words."""
    today = []
    for item in payload.get("today") or []:
        if not isinstance(item, dict):
            continue
        when = item.get("time") if isinstance(item.get("time"), str) else ""
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        if not when.strip() and not title.strip():
            continue
        today.append({"time": when, "title": "Busy"})
    updated = payload.get("updated") if isinstance(payload.get("updated"), str) else ""
    return {"updated": updated, "today": today, "deadlines": [], "money": {}}


def publish_data() -> None:
    """Keep the full schedule in memory. The file on disk is the guest copy."""
    global FULL_PAYLOAD
    with PUBLISH_LOCK:
        payload = None
        if LOCAL.exists():
            try:
                loaded = json.loads(LOCAL.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise json.JSONDecodeError("not an object", "", 0)
                payload = loaded
            except (OSError, json.JSONDecodeError):
                print(
                    "data.local.json was not published: the file could not be read as JSON",
                    file=sys.stderr,
                )
                if FULL_PAYLOAD is None and not PUBLIC.exists():
                    FULL_PAYLOAD = PLACEHOLDER
                    write_public(json.dumps(guest_schedule(PLACEHOLDER), indent=2))
                return
        else:
            payload = PLACEHOLDER
        FULL_PAYLOAD = payload
        write_public(json.dumps(guest_schedule(payload), indent=2))


def load_catalog_ids() -> set:
    ids = set()
    try:
        raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ids
    if not isinstance(raw, list):
        return ids
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            ids.add(item["id"])
    return ids


def load_ambient_preset_keys() -> set:
    keys = set()
    try:
        raw = json.loads(AMBIENT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return keys
    presets = raw.get("presets") if isinstance(raw, dict) else None
    if isinstance(presets, dict):
        keys.update(presets.keys())
    return keys


def protect_local_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def normalize_home_apps(values) -> list:
    if not isinstance(values, list):
        return list(DEFAULT_HOME_APPS)
    out = []
    seen = set()
    for item in values:
        if not isinstance(item, str) or not item or item in seen:
            continue
        if item not in CATALOG_IDS:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= MAX_HOME_APPS:
            break
    return out if out else list(DEFAULT_HOME_APPS)


def normalize_ambient_preset(value) -> str:
    if isinstance(value, str) and value in AMBIENT_PRESETS:
        return value
    return DEFAULT_AMBIENT_PRESET


def normalize_location(raw) -> dict:
    base = dict(DEFAULT_LOCATION)
    if not isinstance(raw, dict):
        return base
    lat = raw.get("lat")
    lon = raw.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            base["lat"] = round(float(lat), 4)
            base["lon"] = round(float(lon), 4)
    label = raw.get("label")
    if isinstance(label, str):
        cleaned = label.strip().replace("\n", " ")[:80]
        if cleaned:
            base["label"] = cleaned
    tz = raw.get("timezone")
    if isinstance(tz, str) and re.fullmatch(r"[A-Za-z_]+(/[A-Za-z_]+)+", tz.strip()):
        base["timezone"] = tz.strip()
    base["locked"] = raw.get("locked") is True
    return base


def read_settings_local() -> dict:
    if not SETTINGS_LOCAL.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_LOCAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_settings_local(data: dict) -> None:
    text = json.dumps(data, indent=2) + "\n"
    SETTINGS_LOCAL.write_text(text, encoding="utf-8")
    protect_local_file(SETTINGS_LOCAL)


def publish_apps(home_apps: list) -> None:
    entries = [{"id": app_id} for app_id in home_apps]
    text = json.dumps(entries, indent=2) + "\n"
    if APPS_PUBLIC.exists() and APPS_PUBLIC.read_text(encoding="utf-8") == text:
        return
    APPS_PUBLIC.write_text(text, encoding="utf-8")


def publish_settings() -> None:
    """Merge settings.local.json into memory and regenerate apps.json."""
    global SETTINGS_STATE
    with PUBLISH_LOCK:
        local = read_settings_local()
        home = normalize_home_apps(local.get("homeApps"))
        preset = normalize_ambient_preset(local.get("ambientPreset"))
        location = normalize_location(local.get("location"))
        SETTINGS_STATE = {"homeApps": home, "ambientPreset": preset, "location": location}
        publish_apps(home)


def label_from_nominatim(payload: dict) -> str:
    address = payload.get("address") if isinstance(payload, dict) else None
    if isinstance(address, dict):
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("hamlet")
            or address.get("municipality")
            or address.get("county")
            or address.get("borough")
        )
        state = address.get("state") or address.get("region") or address.get("state_district")
        if isinstance(city, str) and isinstance(state, str):
            return f"{city.strip()}, {state.strip()}"
        if isinstance(city, str) and city.strip():
            return city.strip()
        country = address.get("country")
        if isinstance(country, str) and country.strip():
            return country.strip()
    name = payload.get("display_name") if isinstance(payload, dict) else ""
    if isinstance(name, str) and name.strip():
        parts = [part.strip() for part in name.split(",") if part.strip()]
        if len(parts) >= 2:
            return f"{parts[0]}, {parts[-1]}"
        return parts[0]
    return ""


def reverse_place_label(lat: float, lon: float) -> str:
    global PLACE_LAST_CALL
    with PLACE_LOCK:
        now = time.monotonic()
        wait = 1.05 - (now - PLACE_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        PLACE_LAST_CALL = time.monotonic()
    query = urlsplit(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1"
    )
    req = Request(query.geturl(), headers={"User-Agent": NOMINATIM_UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    return label_from_nominatim(payload)


def merge_ambient_payload() -> dict:
    try:
        base = json.loads(AMBIENT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        base = {}
    if not isinstance(base, dict):
        base = {}
    with PUBLISH_LOCK:
        preset = SETTINGS_STATE.get("ambientPreset", DEFAULT_AMBIENT_PRESET)
    if preset in AMBIENT_PRESETS:
        base = dict(base)
        base["preset"] = preset
    base = dict(base)
    base["speed"] = min(2.5, float(base.get("speed") or 1) * 1.35)
    if isinstance(base.get("night"), dict):
        night = dict(base["night"])
        night["speed"] = min(2, float(night.get("speed") or 0.5) * 1.25)
        base["night"] = night
    return base


def pin_matches(offered) -> bool:
    """Constant-time check. The length of a wrong PIN does not skip the compare."""
    raw = offered if isinstance(offered, str) else ""
    left = hashlib.sha256(raw.encode("utf-8")).digest()
    right = hashlib.sha256(EXPECTED_PIN.encode("utf-8")).digest()
    same = hmac.compare_digest(left, right)
    return bool(PIN_RE.fullmatch(raw)) and same


ALLOWED_FILES = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/settings.html",
    "/settings-apps.html",
    "/settings-theme.html",
    "/settings-location.html",
    "/style.css",
    "/settings.css",
    "/tokens.css",
    "/main.js",
    "/dashboard.js",
    "/settings.js",
    "/settings-apps.js",
    "/settings-theme.js",
    "/settings-location.js",
    "/data.json",
    "/apps.json",
    "/apps-catalog.json",
    "/ambient.js",
    "/ambient.css",
    "/ambient.json",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/favicon.svg",
    "/assets/shift-a-slate-dim.svg",
}
FONT_FILE = re.compile(r"^/assets/fonts/[a-z0-9][a-z0-9.-]*\.ttf$")
ICON_FILE = re.compile(r"^/assets/icons/[a-z0-9][a-z0-9-]*\.svg$")
APP_ICON = re.compile(r"^/assets/app/[a-z0-9][a-z0-9.-]*\.png$")
BLOCKED_FILES = {"/data.local.json", "/server.py", "/pin.local"}
ROUTE_REDIRECTS = {
    "/settings": "/settings.html",
    "/settings/": "/settings.html",
}
COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def public_path(raw):
    """Return a normalized URL path, or None when the request is not safe to serve."""
    path = unquote(urlsplit(raw).path)
    if not path.startswith("/") or "\\" in path or "\x00" in path or ".." in path:
        return None
    parts = [part for part in path.split("/") if part not in ("", ".")]
    return "/" + "/".join(parts) if parts else "/"


def path_blocked(path):
    """Never serve code, local files, git, or the private schedule file."""
    lowered = path.lower()
    if path in BLOCKED_FILES:
        return True
    if lowered.endswith(".py") or lowered.endswith(".local"):
        return True
    if lowered == "/.git" or lowered.startswith("/.git/") or "/.git/" in lowered:
        return True
    return False


def path_allowed(path):
    if path_blocked(path):
        return False
    if path in ALLOWED_FILES:
        return True
    return bool(FONT_FILE.match(path) or ICON_FILE.match(path) or APP_ICON.match(path))


def load_pin(lan: bool) -> str:
    """Return the phone PIN. Generate one only when this Mac is shared on Wi-Fi."""
    env = os.environ.get("SLATE_PIN", "").strip()
    if env:
        if not PIN_RE.fullmatch(env):
            print("SLATE_PIN must be 4 to 8 digits.", file=sys.stderr)
            sys.exit(1)
        if lan:
            print("The phone needs the PIN from SLATE_PIN.")
        return env
    if PIN_PATH.exists():
        pin = PIN_PATH.read_text(encoding="utf-8").strip()
        if not PIN_RE.fullmatch(pin):
            print("pin.local must contain 4 to 8 digits and nothing else.", file=sys.stderr)
            sys.exit(1)
        protect_pin_file()
        if lan:
            print("The phone needs the PIN saved in pin.local.")
        return pin
    if not lan:
        return ""
    pin = f"{secrets.randbelow(900000) + 100000}"
    PIN_PATH.write_text(pin + "\n", encoding="utf-8")
    protect_pin_file()
    print(f"Phone PIN: {pin}")
    print("Saved in pin.local on this Mac. That file is not served and not committed.")
    return pin


def protect_pin_file() -> None:
    try:
        os.chmod(PIN_PATH, 0o600)
    except OSError:
        pass


def too_many(ip: str) -> bool:
    now = time.monotonic()
    with STATE_LOCK:
        count, locked_until = FAILS.get(ip, (0, 0.0))
        if locked_until and now < locked_until:
            return True
        if locked_until and now >= locked_until:
            FAILS.pop(ip, None)
        return False


def note_fail(ip: str) -> None:
    now = time.monotonic()
    with STATE_LOCK:
        count, locked_until = FAILS.get(ip, (0, 0.0))
        if locked_until and now < locked_until:
            return
        if locked_until and now >= locked_until:
            count = 0
        count += 1
        if count >= FAIL_LIMIT:
            FAILS[ip] = (count, now + LOCKOUT_S)
        else:
            FAILS[ip] = (count, 0.0)


def note_ok(ip: str) -> None:
    with STATE_LOCK:
        FAILS.pop(ip, None)


def remember_session(token: str) -> None:
    with STATE_LOCK:
        if len(SESSIONS) >= 32:
            SESSIONS.clear()
        SESSIONS.add(token)


def session_ok(token: str) -> bool:
    if not token or not COOKIE_RE.fullmatch(token):
        return False
    with STATE_LOCK:
        return token in SESSIONS


def forget_session(token: str) -> None:
    if not token:
        return
    with STATE_LOCK:
        SESSIONS.discard(token)


def cookie_header(token: str, max_age: int) -> str:
    return f"slate={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}"


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".svg": "image/svg+xml",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def redirect(self, target: str, code=302):
        self.send_response(code)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def reject(self, code=404):
        self.close_connection = True
        body = b"Not found\n"
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, code, payload, extra=None):
        body = (json.dumps(payload) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in extra or ():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def cookie(self, name):
        raw = self.headers.get("Cookie", "")
        prefix = name + "="
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):]
        return ""

    def pin_ok(self):
        if not getattr(self.server, "require_pin", False):
            return True
        return session_ok(self.cookie("slate"))

    def serve_schedule(self):
        """Guest view is Busy. The real titles need the PIN on Wi-Fi and Show all."""
        if not self.pin_ok():
            self.send_json(401, {"error": "pin"})
            return
        with PUBLISH_LOCK:
            publish_data()
            payload = FULL_PAYLOAD if isinstance(FULL_PAYLOAD, dict) else PLACEHOLDER
            full = self.headers.get("X-Slate-Full", "") == "1"
            body = payload if full else guest_schedule(payload)
        self.send_json(200, body)

    def serve_settings_get(self):
        with PUBLISH_LOCK:
            publish_settings()
            body = dict(SETTINGS_STATE)
        self.send_json(200, body)

    def serve_ambient(self):
        self.send_json(200, merge_ambient_payload())

    def serve_place(self):
        split = urlsplit(self.path)
        params = parse_qs(split.query)
        lat_raw = params.get("lat", [""])[0]
        lon_raw = params.get("lon", [""])[0]
        try:
            lat = round(float(lat_raw), 4)
            lon = round(float(lon_raw), 4)
        except (TypeError, ValueError):
            self.send_json(400, {"error": "bad"})
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            self.send_json(400, {"error": "bad"})
            return
        label = reverse_place_label(lat, lon)
        if not label:
            label = f"{lat:.2f}, {lon:.2f}"
        self.send_json(200, {"lat": lat, "lon": lon, "label": label})

    def settings_write_ok(self) -> bool:
        if not getattr(self.server, "require_pin", False):
            return True
        return session_ok(self.cookie("slate"))

    def save_settings(self, obj):
        if obj is None:
            self.send_json(400, {"error": "bad"})
            return
        allowed = set(obj.keys())
        if not allowed or not allowed.issubset({"homeApps", "ambientPreset", "location"}):
            self.send_json(400, {"error": "bad"})
            return
        with PUBLISH_LOCK:
            current = dict(SETTINGS_STATE)
            if "homeApps" in obj:
                current["homeApps"] = normalize_home_apps(obj.get("homeApps"))
            if "ambientPreset" in obj:
                current["ambientPreset"] = normalize_ambient_preset(obj.get("ambientPreset"))
            if "location" in obj:
                merged = dict(current.get("location", DEFAULT_LOCATION))
                if isinstance(obj.get("location"), dict):
                    merged.update(obj["location"])
                current["location"] = normalize_location(merged)
            write_settings_local(current)
            publish_settings()
            body = dict(SETTINGS_STATE)
        self.send_json(200, body)

    def do_GET(self):
        path = public_path(self.path)
        if path is None:
            self.reject()
            return
        if path in ROUTE_REDIRECTS:
            self.redirect(ROUTE_REDIRECTS[path])
            return
        if path.lower() == "/settings.html" and path != "/settings.html":
            self.redirect("/settings.html")
            return
        if not path_allowed(path):
            self.reject()
            return
        if path == "/data.json":
            self.serve_schedule()
            return
        if path == "/settings.json":
            self.serve_settings_get()
            return
        if path == "/ambient.json":
            self.serve_ambient()
            return
        if path == "/place.json":
            self.serve_place()
            return
        super().do_GET()

    def do_HEAD(self):
        path = public_path(self.path)
        if path is None or not path_allowed(path):
            self.reject()
            return
        if path == "/data.json":
            self.serve_schedule()
            return
        if path == "/settings.json":
            self.serve_settings_get()
            return
        if path == "/ambient.json":
            self.serve_ambient()
            return
        if path == "/place.json":
            self.serve_place()
            return
        super().do_HEAD()

    def read_object(self, max_len=8192):
        raw_len = self.headers.get("Content-Length", "")
        if not raw_len.isdigit():
            self.close_connection = True
            return None
        length = int(raw_len)
        if length > 65536:
            self.close_connection = True
            return None
        data = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if length > max_len or not ctype.startswith("application/json"):
            return None
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    def sign_out(self):
        forget_session(self.cookie("slate"))
        self.send_json(200, {"ok": True}, (("Set-Cookie", cookie_header("", 0)),))

    def do_POST(self):
        path = public_path(self.path)
        if path == "/settings.json":
            if not self.settings_write_ok():
                self.send_json(401, {"error": "pin"})
                return
            obj = self.read_object()
            self.save_settings(obj)
            return
        if not getattr(self.server, "require_pin", False):
            self.reject()
            return
        if path == "/lock":
            self.close_connection = True
            self.sign_out()
            return
        if path != "/unlock":
            self.reject()
            return
        ip = self.client_address[0]
        if too_many(ip):
            self.send_json(429, {"error": "slow"})
            return
        obj = self.read_object(max_len=128)
        offered = obj.get("pin") if obj is not None and set(obj) == {"pin"} else ""
        if not pin_matches(offered):
            note_fail(ip)
            self.send_json(401, {"error": "pin"})
            return
        note_ok(ip)
        token = secrets.token_urlsafe(32)
        remember_session(token)
        self.send_json(200, {"ok": True}, (("Set-Cookie", cookie_header(token, COOKIE_MAX_AGE)),))

    def do_PUT(self):
        self.reject()

    def do_DELETE(self):
        self.reject()

    def list_directory(self, path):
        self.send_error(404, "Not found")
        return None

    def log_message(self, fmt, *args):
        """Log the request line only. Never the body, the PIN, or the schedule."""
        sys.stderr.write("%s - %s\n" % (self.client_address[0], fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    require_pin = False


def lan_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def listen(host, require_pin):
    try:
        server = Server((host, PORT), Handler)
    except OSError as exc:
        print(f"Could not listen on {host}:{PORT}: {exc}", file=sys.stderr)
        return None
    server.require_pin = require_pin
    return server


def main() -> None:
    global EXPECTED_PIN
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="Serve the TV dashboard")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Also listen on this Mac's Wi-Fi address so a phone can open it",
    )
    args = parser.parse_args()
    lan = args.lan or os.environ.get("SLATE_LAN", "").strip() == "1"
    EXPECTED_PIN = load_pin(lan)
    global CATALOG_IDS, AMBIENT_PRESETS
    CATALOG_IDS = load_catalog_ids()
    AMBIENT_PRESETS = load_ambient_preset_keys()
    publish_settings()
    publish_data()

    local = listen("127.0.0.1", False)
    if local is None:
        sys.exit(1)
    servers = [local]
    print(f"On this Mac: http://127.0.0.1:{PORT}")
    print(f"Settings: http://127.0.0.1:{PORT}/settings.html")

    if lan:
        ip = lan_address()
        if not ip or ip.startswith("127."):
            print("No Wi-Fi address found. The phone cannot connect until this Mac is on Wi-Fi.")
        else:
            remote = listen(ip, True)
            if remote is None:
                for server in servers:
                    server.server_close()
                sys.exit(1)
            servers.append(remote)
            print(f"On this Wi-Fi: http://{ip}:{PORT}")
            print(f"Dashboard: http://{ip}:{PORT}/dashboard.html")
            print(f"Settings: http://{ip}:{PORT}/settings.html")
            print("Same Wi-Fi only. The address is also in System Settings, Network, Wi-Fi, Details.")
            print("Or in Terminal: ipconfig getifaddr en0")
    else:
        print("This Mac only. For a phone on the same Wi-Fi, run: python3 server.py --lan")
    print("Do not forward port 8000.")
    print("The PIN over http is a convenience lock, not security.")
    print("Leave this Mac awake. If it sleeps, the page stops.")

    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
