#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

import json
import re
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
PORT = 8000
LOCAL = ROOT / "data.local.json"
PUBLIC = ROOT / "data.json"
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


def write_public(text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if PUBLIC.exists() and PUBLIC.read_text(encoding="utf-8") == text:
        return
    PUBLIC.write_text(text, encoding="utf-8")


def publish_data() -> None:
    """Copy data.local.json onto data.json. Otherwise publish placeholder text."""
    if LOCAL.exists():
        try:
            text = LOCAL.read_text(encoding="utf-8")
            json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"data.local.json was not published: {exc}", file=sys.stderr)
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
}
FONT_FILE = re.compile(r"^/assets/fonts/[a-z0-9][a-z0-9.-]*\.ttf$")
ICON_FILE = re.compile(r"^/assets/icons/[a-z0-9][a-z0-9-]*\.svg$")
BLOCKED_FILES = {"/data.local.json", "/server.py"}


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
    return bool(FONT_FILE.match(path) or ICON_FILE.match(path))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def reject(self):
        self.send_error(404, "Not found")

    def do_GET(self):
        path = public_path(self.path)
        if path is None or not path_allowed(path):
            self.reject()
            return
        if path == "/data.json":
            publish_data()
        super().do_GET()

    def do_HEAD(self):
        path = public_path(self.path)
        if path is None or not path_allowed(path):
            self.reject()
            return
        if path == "/data.json":
            publish_data()
        super().do_HEAD()

    def do_POST(self):
        self.reject()

    def do_PUT(self):
        self.reject()

    def do_DELETE(self):
        self.reject()

    def list_directory(self, path):
        self.send_error(404, "Not found")
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def lan_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def main() -> None:
    publish_data()
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as exc:
        print(f"Could not listen on port {PORT}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"TV dashboard at http://127.0.0.1:{PORT}")
    lan = lan_address()
    if lan and not lan.startswith("127."):
        print(f"On this Wi-Fi: http://{lan}:{PORT}")
    print("Do not forward port 8000.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
