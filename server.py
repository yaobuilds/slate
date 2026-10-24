#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/data.json":
            publish_data()
        super().do_GET()

    def list_directory(self, path):
        self.send_error(404, "Not found")
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    publish_data()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"Could not listen on port {PORT}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"TV dashboard at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
