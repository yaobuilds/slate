#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

import argparse
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
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
PORT = 8000
LOCAL = ROOT / "data.local.json"
PUBLIC = ROOT / "data.json"
PIN_PATH = ROOT / "pin.local"
PIN_RE = re.compile(r"^[0-9]{4,8}$")
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

PUBLISH_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
SESSIONS = set()
FAILS = {}
EXPECTED_PIN = ""


def write_public(text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if PUBLIC.exists() and PUBLIC.read_text(encoding="utf-8") == text:
        return
    PUBLIC.write_text(text, encoding="utf-8")


def publish_data() -> None:
    """Copy data.local.json onto data.json. Otherwise publish placeholder text."""
    with PUBLISH_LOCK:
        if LOCAL.exists():
            try:
                text = LOCAL.read_text(encoding="utf-8")
                json.loads(text)
            except (OSError, json.JSONDecodeError):
                print(
                    "data.local.json was not published: the file could not be read as JSON",
                    file=sys.stderr,
                )
                if not PUBLIC.exists():
                    write_public(json.dumps(PLACEHOLDER, indent=2))
                return
            write_public(text)
            return
        write_public(json.dumps(PLACEHOLDER, indent=2))


ALLOWED_FILES = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/style.css",
    "/tokens.css",
    "/main.js",
    "/dashboard.js",
    "/data.json",
    "/apps.json",
    "/apps-catalog.json",
    "/ambient.js",
    "/ambient.css",
    "/ambient.json",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/favicon.svg",
}
FONT_FILE = re.compile(r"^/assets/fonts/[a-z0-9][a-z0-9.-]*\.ttf$")
ICON_FILE = re.compile(r"^/assets/icons/[a-z0-9][a-z0-9-]*\.svg$")
APP_ICON = re.compile(r"^/assets/app/[a-z0-9][a-z0-9.-]*\.png$")
BLOCKED_FILES = {"/data.local.json", "/server.py", "/pin.local"}
COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def public_path(raw):
    """Return a normalized URL path, or None when the request is not safe to serve."""
    path = unquote(urlsplit(raw).path)
    if not path.startswith("/") or "\\" in path or "\x00" in path or ".." in path:
        return None
    parts = [part for part in path.split("/") if part not in ("", ".")]
    return "/" + "/".join(parts) if parts else "/"


def path_allowed(path):
    if path in BLOCKED_FILES:
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
        if lan:
            print("The phone needs the PIN saved in pin.local.")
        return pin
    if not lan:
        return ""
    pin = f"{secrets.randbelow(900000) + 100000}"
    PIN_PATH.write_text(pin + "\n", encoding="utf-8")
    os.chmod(PIN_PATH, 0o600)
    print(f"Phone PIN: {pin}")
    print("Saved in pin.local on this Mac. That file is not served and not committed.")
    return pin


def too_many(ip: str) -> bool:
    now = time.monotonic()
    with STATE_LOCK:
        count, start = FAILS.get(ip, (0, now))
        if now - start > 60:
            return False
        return count >= 8


def note_fail(ip: str) -> None:
    now = time.monotonic()
    with STATE_LOCK:
        count, start = FAILS.get(ip, (0, now))
        if now - start > 60:
            count, start = 0, now
        FAILS[ip] = (count + 1, start)


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


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".svg": "image/svg+xml",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

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

    def guard(self, path):
        """Return True when this request may continue. A private file on Wi-Fi needs the PIN."""
        if path == "/data.json" and not self.pin_ok():
            self.send_json(401, {"error": "pin"})
            return False
        if path == "/data.json":
            publish_data()
        return True

    def do_GET(self):
        path = public_path(self.path)
        if path is None or not path_allowed(path):
            self.reject()
            return
        if not self.guard(path):
            return
        super().do_GET()

    def do_HEAD(self):
        path = public_path(self.path)
        if path is None or not path_allowed(path):
            self.reject()
            return
        if not self.guard(path):
            return
        super().do_HEAD()

    def read_object(self):
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
        if length > 128 or not ctype.startswith("application/json"):
            return None
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    def do_POST(self):
        path = public_path(self.path)
        if path != "/unlock" or not getattr(self.server, "require_pin", False):
            self.reject()
            return
        ip = self.client_address[0]
        if too_many(ip):
            self.send_json(429, {"error": "slow"})
            return
        obj = self.read_object()
        offered = obj.get("pin") if obj is not None and set(obj) == {"pin"} else ""
        if (
            not isinstance(offered, str)
            or not PIN_RE.fullmatch(offered)
            or len(offered) != len(EXPECTED_PIN)
            or not hmac.compare_digest(offered, EXPECTED_PIN)
        ):
            note_fail(ip)
            self.send_json(401, {"error": "pin"})
            return
        note_ok(ip)
        token = secrets.token_urlsafe(32)
        remember_session(token)
        cookie = f"slate={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"
        self.send_json(200, {"ok": True}, (("Set-Cookie", cookie),))

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
    publish_data()

    local = listen("127.0.0.1", False)
    if local is None:
        sys.exit(1)
    servers = [local]
    print(f"On this Mac: http://127.0.0.1:{PORT}")

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
            print("Same Wi-Fi only. The address is also in System Settings, Network, Wi-Fi, Details.")
            print("Or in Terminal: ipconfig getifaddr en0")
    else:
        print("This Mac only. For a phone on the same Wi-Fi, run: python3 server.py --lan")
    print("Do not forward port 8000.")

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
