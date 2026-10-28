#!/usr/bin/env python3
"""Fix-pass checks. The PIN cases use the same gate as python3 server.py --lan."""

import base64
import http.client
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

TITLE = "Piano lesson EXAMPLE"
DEADLINE = "Secret bill EXAMPLE"
MONEY = "Secret cushion EXAMPLE"
PIN = "135790"
WRONG = "246813"

FIXTURE = {
    "updated": "2026-10-24T09:41:00-04:00",
    "today": [{"time": "9:00", "title": TITLE}],
    "deadlines": [{"title": DEADLINE, "due": "Friday"}],
    "money": {"note": MONEY},
}


def png_pixels(data):
    """Return (width, height, rows of RGBA) for an 8-bit PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos = 8
    width = height = color = None
    raw = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit, color = struct.unpack(">IIBB", chunk[:10])
            if bit != 8 or color not in (2, 6):
                raise ValueError("unsupported png")
        elif kind == b"IDAT":
            raw += chunk
        elif kind == b"IEND":
            break
    bpp = 4 if color == 6 else 3
    stream = zlib.decompress(raw)
    stride = width * bpp
    rows = []
    i = 0
    prev = bytearray(stride)

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    for _ in range(height):
        filt = stream[i]
        i += 1
        row = bytearray(stream[i:i + stride])
        i += stride
        for x in range(stride):
            left = row[x - bpp] if x >= bpp else 0
            up = prev[x]
            ul = prev[x - bpp] if x >= bpp else 0
            if filt == 1:
                row[x] = (row[x] + left) & 255
            elif filt == 2:
                row[x] = (row[x] + up) & 255
            elif filt == 3:
                row[x] = (row[x] + ((left + up) // 2)) & 255
            elif filt == 4:
                row[x] = (row[x] + paeth(left, up, ul)) & 255
        prev = row
        if bpp == 3:
            rgba = bytearray()
            for x in range(0, stride, 3):
                rgba.extend(row[x:x + 3])
                rgba.append(255)
            row = rgba
        rows.append(bytes(row))
    return width, height, rows


class Cdp:
    def __init__(self, ws_url):
        host_path = ws_url.split("://", 1)[1]
        host, path = host_path.split("/", 1)
        hostname, port = host.rsplit(":", 1)
        self.sock = socket.create_connection((hostname, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf = b""
        self.next_id = 0

    def _frame(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _read(self):
        while True:
            if len(self.buf) < 2:
                self.buf += self.sock.recv(65536)
                continue
            b1 = self.buf[1]
            n = b1 & 127
            i = 2
            if n == 126:
                if len(self.buf) < 4:
                    self.buf += self.sock.recv(65536)
                    continue
                n = struct.unpack("!H", self.buf[2:4])[0]
                i = 4
            elif n == 127:
                if len(self.buf) < 10:
                    self.buf += self.sock.recv(65536)
                    continue
                n = struct.unpack("!Q", self.buf[2:10])[0]
                i = 10
            masked = b1 & 128
            if masked:
                i += 4
            if len(self.buf) < i + n:
                self.buf += self.sock.recv(65536)
                continue
            payload = self.buf[i:i + n]
            if masked:
                key = self.buf[i - 4:i]
                payload = bytes(b ^ key[k % 4] for k, b in enumerate(payload))
            opcode = self.buf[0] & 15
            self.buf = self.buf[i + n:]
            if opcode == 9:
                self._frame(10, payload)
                continue
            if opcode == 8:
                raise EOFError("socket closed")
            if opcode in (1, 0):
                return payload.decode()

    def send(self, method, params=None, timeout=15):
        self.next_id += 1
        mid = self.next_id
        self._frame(1, json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.sock.settimeout(max(0.2, deadline - time.time()))
            msg = self._read()
            if not msg:
                continue
            obj = json.loads(msg)
            if obj.get("id") == mid:
                if "error" in obj:
                    raise RuntimeError(str(obj["error"]))
                return obj.get("result")
        raise TimeoutError(method)

    def eval(self, expression, timeout=15):
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        }, timeout=timeout)
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"]))
        return result.get("result", {}).get("value")


def chrome_bin():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


class FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.local = root / "data.local.json"
        self.public = root / "data.json"
        self.local.write_text(json.dumps(FIXTURE), encoding="utf-8")
        self._old = (server.LOCAL, server.PUBLIC, server.EXPECTED_PIN, server.FULL_PAYLOAD)
        server.LOCAL = self.local
        server.PUBLIC = self.public
        server.EXPECTED_PIN = PIN
        server.FULL_PAYLOAD = None
        server.FAILS.clear()
        server.SESSIONS.clear()
        self.logs = []
        self._log = server.Handler.log_message

        def capture(handler, fmt, *args):
            self.logs.append(fmt % args)

        server.Handler.log_message = capture
        self.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        self.httpd.require_pin = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.Handler.log_message = self._log
        server.LOCAL, server.PUBLIC, server.EXPECTED_PIN, server.FULL_PAYLOAD = self._old
        server.FAILS.clear()
        server.SESSIONS.clear()
        self.tmp.cleanup()

    def _body(self, path, headers=None, method="GET", data=None):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=5) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def _raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read().decode(), {k.lower(): v for k, v in resp.getheaders()}
        finally:
            conn.close()

    def test_lan_pin_gate_sends_busy_until_show_all(self):
        status, body = self._body("/data.json")
        self.assertEqual(status, 401)
        self.assertNotIn(TITLE, body)
        self.assertNotIn(DEADLINE, body)
        self.assertNotIn(MONEY, body)
        self.assertNotIn(PIN, body)

        status, body = self._body("/data.local.json")
        self.assertEqual(status, 404)
        self.assertNotIn(TITLE, body)
        status, body = self._body("/portal.html")
        self.assertEqual(status, 404)
        status, body = self._body("/docs/design/SPEC.md")
        self.assertEqual(status, 404)

        leaked = WRONG + "99"
        self.logs.clear()
        status, body = self._body(
            "/unlock",
            {"Content-Type": "application/json"},
            "POST",
            json.dumps({"pin": leaked}).encode(),
        )
        self.assertEqual(status, 401)
        self.assertNotIn(leaked, body)
        self.assertNotIn(TITLE, body)
        joined = "\n".join(self.logs)
        self.assertNotIn(leaked, joined)
        self.assertNotIn(PIN, joined)
        self.assertNotIn(TITLE, joined)

        self.assertFalse(server.pin_matches("0000"))
        self.assertFalse(server.pin_matches(PIN + "1"))
        self.assertFalse(server.pin_matches(None))
        self.assertTrue(server.pin_matches(PIN))
        self.assertIn("compare_digest", Path(server.__file__).read_text(encoding="utf-8"))

        status, body = self._body(
            "/unlock",
            {"Content-Type": "application/json"},
            "POST",
            json.dumps({"pin": PIN}).encode(),
        )
        self.assertEqual(status, 200)
        self.assertNotIn(PIN, "\n".join(self.logs))

        status, body = self._body("/data.json")
        self.assertEqual(status, 200, body)
        self.assertIn("Busy", body)
        self.assertNotIn(TITLE, body)
        self.assertNotIn(DEADLINE, body)
        self.assertNotIn(MONEY, body)
        disk = self.public.read_text(encoding="utf-8")
        self.assertIn("Busy", disk)
        self.assertNotIn(TITLE, disk)

        status, body = self._body("/data.json", {"X-Slate-Full": "1"})
        self.assertEqual(status, 200)
        self.assertIn(TITLE, body)
        self.assertIn(DEADLINE, body)
        self.assertIn(MONEY, body)

        home, home_body = self._body("/index.html")
        self.assertEqual(home, 200)
        self.assertNotIn(TITLE, home_body)
        self.assertNotIn("data.json", (ROOT / "main.js").read_text(encoding="utf-8"))

    def test_pin_attempt_limit(self):
        clock = {"now": 1000.0}

        def fake_mono():
            return clock["now"]

        with mock.patch("server.time.monotonic", fake_mono):
            for _ in range(4):
                status, _body = self._body(
                    "/unlock",
                    {"Content-Type": "application/json"},
                    "POST",
                    json.dumps({"pin": WRONG}).encode(),
                )
                self.assertEqual(status, 401)
            status, body = self._body(
                "/unlock",
                {"Content-Type": "application/json"},
                "POST",
                json.dumps({"pin": PIN}).encode(),
            )
            self.assertEqual(status, 200, body)
            self.assertNotIn(TITLE, body)

            server.FAILS.clear()
            server.SESSIONS.clear()
            self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

            for _ in range(5):
                status, _body = self._body(
                    "/unlock",
                    {"Content-Type": "application/json"},
                    "POST",
                    json.dumps({"pin": WRONG}).encode(),
                )
                self.assertEqual(status, 401)
            status, body = self._body(
                "/unlock",
                {"Content-Type": "application/json"},
                "POST",
                json.dumps({"pin": PIN}).encode(),
            )
            self.assertEqual(status, 429, body)
            self.assertNotIn(TITLE, body)
            self.assertNotIn(PIN, body)

            clock["now"] += 59
            status, body = self._body(
                "/unlock",
                {"Content-Type": "application/json"},
                "POST",
                json.dumps({"pin": PIN}).encode(),
            )
            self.assertEqual(status, 429, body)

            clock["now"] += 2
            status, body = self._body(
                "/unlock",
                {"Content-Type": "application/json"},
                "POST",
                json.dumps({"pin": PIN}).encode(),
            )
            self.assertEqual(status, 200, body)
            self.assertNotIn(PIN, body)

    def test_session_cookie_max_age_and_sign_out(self):
        status, body, headers = self._raw(
            "POST",
            "/unlock",
            json.dumps({"pin": PIN}).encode(),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, body)
        cookie = headers.get("set-cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        match = re.search(r"Max-Age=(\d+)", cookie)
        self.assertIsNotNone(match, cookie)
        age = int(match.group(1))
        self.assertLessEqual(age, 7 * 24 * 60 * 60, cookie)
        self.assertEqual(age, server.COOKIE_MAX_AGE)
        self.assertEqual(server.COOKIE_MAX_AGE, 604800)
        token = cookie.split(";", 1)[0].split("=", 1)[1]
        self.assertTrue(server.session_ok(token))

        status, body, _headers = self._raw("GET", "/data.json", headers={"Cookie": f"slate={token}"})
        self.assertEqual(status, 200, body)
        self.assertIn("Busy", body)
        self.assertNotIn(TITLE, body)

        status, body, lock_headers = self._raw("POST", "/lock", headers={"Cookie": f"slate={token}"})
        self.assertEqual(status, 200, body)
        self.assertIn("Max-Age=0", lock_headers.get("set-cookie", ""))
        self.assertFalse(server.session_ok(token))

        status, body, _headers = self._raw("GET", "/data.json", headers={"Cookie": f"slate={token}"})
        self.assertEqual(status, 401, body)
        self.assertNotIn(TITLE, body)
        self.assertNotIn(DEADLINE, body)
        self.assertNotIn(MONEY, body)

        status, body, _headers = self._raw(
            "GET",
            "/data.json",
            headers={"Cookie": f"slate={token}", "X-Slate-Full": "1"},
        )
        self.assertEqual(status, 401, body)
        self.assertNotIn(TITLE, body)

    def test_file_allowlist_blocks_private_paths(self):
        blocked = [
            "/server.py",
            "/pin.local",
            "/data.local.json",
            "/settings.local.json",
            "/.git/config",
            "/.git/HEAD",
            "/AGENTS.md",
            "/STATUS.md",
            "/TASKS.md",
            "/tests/test_fix.py",
            "/docs/design/SPEC.md",
            "/../pin.local",
            "/%2e%2e/pin.local",
            "/assets/icons/../../pin.local",
            "/foo.py",
            "/secret.local",
            "/lock",
            "/unlock",
        ]
        for path in blocked:
            status, body, _headers = self._raw("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(TITLE, body)
            self.assertNotIn(PIN, body)
            self.assertNotIn("EXPECTED_PIN", body)
            self.assertNotIn("Phone PIN", body)

        status, body, _headers = self._raw("GET", "/data.json")
        self.assertEqual(status, 401)
        self.assertNotIn(TITLE, body)
        self.assertNotIn(DEADLINE, body)
        self.assertNotIn(MONEY, body)

        status, body, _headers = self._raw("GET", "/index.html")
        self.assertEqual(status, 200, body[:80])
        self.assertNotIn(TITLE, body)

    def test_settings_json_localhost(self):
        open_server = server.Server(("127.0.0.1", 0), server.Handler)
        open_server.require_pin = False
        thread = threading.Thread(target=open_server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{open_server.server_address[1]}"
        old_settings = server.SETTINGS_LOCAL
        old_apps = server.APPS_PUBLIC
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                server.SETTINGS_LOCAL = root / "settings.local.json"
                server.APPS_PUBLIC = root / "apps.json"
                server.CATALOG_IDS = server.load_catalog_ids()
                server.AMBIENT_PRESETS = server.load_ambient_preset_keys()
                with urllib.request.urlopen(base + "/settings.json", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    data = json.loads(resp.read().decode())
                self.assertIn("homeApps", data)
                self.assertIn("ambientPreset", data)
                req = urllib.request.Request(
                    base + "/settings.json",
                    data=json.dumps({"homeApps": ["netflix", "disney-plus"]}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    saved = json.loads(resp.read().decode())
                self.assertEqual(saved["homeApps"], ["netflix", "disney-plus"])
                written = json.loads(server.APPS_PUBLIC.read_text(encoding="utf-8"))
                self.assertEqual([item["id"] for item in written], ["netflix", "disney-plus"])
                self.assertTrue(server.SETTINGS_LOCAL.exists())
                self.assertFalse((ROOT / "settings.local.json") == server.SETTINGS_LOCAL)
                pointer = urllib.request.Request(
                    base + "/settings.json",
                    data=json.dumps({"hidePointer": True}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(pointer, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    saved_pointer = json.loads(resp.read().decode())
                self.assertIs(saved_pointer["hidePointer"], True)
                self.assertEqual(saved_pointer["homeApps"], ["netflix", "disney-plus"])
        finally:
            server.SETTINGS_LOCAL = old_settings
            server.APPS_PUBLIC = old_apps
            open_server.shutdown()
            open_server.server_close()

    def test_schedule_post_normalizes_and_stays_private(self):
        title = "Recital EXAMPLE"
        before = self.local.read_text(encoding="utf-8")
        body = json.dumps({
            "today": [
                {"time": "", "title": ""},
                {"time": "9:00", "title": title},
            ],
            "deadlines": [
                {"title": "Outline EXAMPLE", "due": "Friday"},
                {"title": "Draft EXAMPLE", "due": "2026-11-02"},
            ],
            "money": {"note": "No bills this week", "bars": [{"label": "Rent"}]},
        }).encode()
        status, raw, _headers = self._raw(
            "POST",
            "/schedule.json",
            body,
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401, raw)
        self.assertEqual(self.local.read_text(encoding="utf-8"), before)
        self.assertNotIn(title, raw)

        status, raw, _headers = self._raw("GET", "/data.local.json")
        self.assertEqual(status, 404)
        self.assertNotIn(title, raw)

        status, raw, _headers = self._raw("GET", "/settings-schedule.html")
        self.assertEqual(status, 200, raw[:80])
        self.assertNotIn(title, raw)

        open_server = server.Server(("127.0.0.1", 0), server.Handler)
        open_server.require_pin = False
        thread = threading.Thread(target=open_server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{open_server.server_address[1]}"
        try:
            self.local.write_text("{", encoding="utf-8")
            extra = json.dumps({
                "today": [],
                "deadlines": [],
                "money": {"note": ""},
                "extra": True,
            }).encode()
            req = urllib.request.Request(
                base + "/schedule.json",
                data=extra,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(caught.exception.code, 400)
            self.assertEqual(self.local.read_text(encoding="utf-8"), "{")

            req = urllib.request.Request(
                base + "/schedule.json",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                saved = json.loads(resp.read().decode())
            self.assertEqual(saved["today"], [{"time": "9:00", "title": title}])
            self.assertEqual(saved["deadlines"], [{"title": "Draft EXAMPLE", "due": "2026-11-02"}])
            self.assertEqual(saved["money"], {"note": "No bills this week"})
            self.assertNotIn("bars", saved["money"])
            self.assertIn("T", saved["updated"])
            disk = json.loads(self.local.read_text(encoding="utf-8"))
            self.assertEqual(disk["today"][0]["title"], title)
            self.assertEqual(self.local.stat().st_mode & 0o777, 0o600)

            with urllib.request.urlopen(base + "/data.json", timeout=5) as resp:
                guest = resp.read().decode()
            self.assertIn("Busy", guest)
            self.assertNotIn(title, guest)

            full_req = urllib.request.Request(base + "/data.json", headers={"X-Slate-Full": "1"})
            with urllib.request.urlopen(full_req, timeout=5) as resp:
                full = json.loads(resp.read().decode())
            self.assertEqual(full["today"][0]["title"], title)
            self.assertNotIn(title, "\n".join(self.logs))
        finally:
            open_server.shutdown()
            open_server.server_close()

    def test_home_apps_order_published(self):
        server.CATALOG_IDS = server.load_catalog_ids()
        order = ["hulu", "netflix", "youtube"]
        normalized = server.normalize_home_apps(order)
        self.assertEqual(normalized, order)
        self.assertEqual(server.normalize_home_apps([]), [])
        self.assertEqual(server.normalize_home_apps(None), list(server.DEFAULT_HOME_APPS))
        saved_ids = set(server.CATALOG_IDS)
        try:
            server.CATALOG_IDS = set()
            self.assertEqual(server.normalize_home_apps(["netflix"]), list(server.DEFAULT_HOME_APPS))
        finally:
            server.CATALOG_IDS = saved_ids
        with tempfile.TemporaryDirectory() as tmp:
            apps_path = Path(tmp) / "apps.json"
            old_apps = server.APPS_PUBLIC
            try:
                server.APPS_PUBLIC = apps_path
                server.publish_apps(normalized)
                entries = json.loads(apps_path.read_text(encoding="utf-8"))
                ids = [entry["id"] for entry in entries]
                self.assertEqual(ids, order)
            finally:
                server.APPS_PUBLIC = old_apps

    def test_pin_local_mode_600(self):
        pin_path = Path(self.tmp.name) / "pin.local"
        pin_path.write_text("246813\n", encoding="utf-8")
        os.chmod(pin_path, 0o644)
        old = server.PIN_PATH
        old_env = os.environ.pop("SLATE_PIN", None)
        try:
            server.PIN_PATH = pin_path
            loaded = server.load_pin(True)
            self.assertEqual(loaded, "246813")
            self.assertEqual(pin_path.stat().st_mode & 0o777, 0o600)
            pin_path.unlink()
            created = server.load_pin(True)
            self.assertRegex(created, r"^[0-9]{4,8}$")
            self.assertTrue(pin_path.exists())
            self.assertEqual(pin_path.stat().st_mode & 0o777, 0o600)
        finally:
            server.PIN_PATH = old
            if old_env is not None:
                os.environ["SLATE_PIN"] = old_env

    def test_shipped_js_has_no_prototype_controls(self):
        for name in ("ambient.js", "main.js", "dashboard.js"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("URLSearchParams", text, name)
            self.assertNotIn("location.search", text, name)
            self.assertNotIn("requestAnimationFrame", text, name)
        ambient_css = (ROOT / "ambient.css").read_text(encoding="utf-8")
        self.assertNotIn("filter:", ambient_css)
        self.assertNotIn("blur(", ambient_css)
        style = (ROOT / "style.css").read_text(encoding="utf-8")
        for banned in ("#5FA39A", "#0F0F12", "#E0D3BB", "#5fa39a"):
            self.assertNotIn(banned, style)
        kicker = style.split(".kicker {", 1)[1].split("}", 1)[0]
        self.assertNotIn("22px", kicker)
        main = (ROOT / "main.js").read_text(encoding="utf-8")
        self.assertIn("40.7128", main)
        self.assertIn("-74.0060", main)
        self.assertIn("timezone=auto", main)
        self.assertIn("forecast_hours=7", main)
        self.assertIn("WEATHER_STALE_MS = 20 * 60 * 1000", main)
        self.assertIn("WEATHER_DROP_MS = 3 * 60 * 60 * 1000", main)
        self.assertIn("if (wxBox || dwx)", main)
        self.assertNotIn("else if (dwx)", main)
        boot = main.split("async function bootWeatherAndTiles", 1)[1].split("bootWeatherAndTiles();", 1)[0]
        self.assertIn("loadWeather();", boot)
        self.assertNotIn("scene", (ROOT / "index.html").read_text(encoding="utf-8").lower())
        self.assertIn('style="visibility: hidden"', (ROOT / "index.html").read_text(encoding="utf-8"))


def wait_until(cdp, expression, timeout=8):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = cdp.eval(expression)
        if last:
            return last
        time.sleep(0.15)
    raise AssertionError(f"timed out waiting for {expression!r}, last={last!r}")


def glyph_luma(png):
    _w, _h, rows = png_pixels(png)
    values = []
    for row in rows:
        for i in range(0, len(row), 4):
            r, g, b, a = row[i:i + 4]
            if a < 200:
                continue
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luma > 40:
                values.append(luma)
    if len(values) < 20:
        raise AssertionError(f"not enough clock pixels ({len(values)})")
    values.sort()
    return values[int(len(values) * 0.95)]


def run_browser(base):
    binary = chrome_bin()
    if not binary:
        raise unittest.SkipTest("Chrome is not installed")
    profile = tempfile.mkdtemp(prefix="slate-chrome-")
    port = 9222 + (os.getpid() % 1000)
    proc = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--window-size=1920,1080",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    evidence = {"chrome": binary}
    try:
        version = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as resp:
                    version = json.load(resp)
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.1)
        if not version:
            raise RuntimeError("Chrome did not open a debugging port")
        target = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        try:
            with urllib.request.urlopen(target, timeout=5) as resp:
                page = json.load(resp)
        except urllib.error.HTTPError:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/new?about:blank", timeout=5) as resp:
                page = json.load(resp)
        cdp = Cdp(page["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Network.enable")
        cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False,
        })

        cdp.send("Network.setBlockedURLs", {"urls": ["*open-meteo.com*"]})
        cdp.send("Page.navigate", {"url": base + "/index.html"})
        wait_until(
            cdp,
            "document.getElementById('wx-stale') && document.getElementById('wx-stale').textContent.includes('Weather unavailable')",
            timeout=8,
        )
        first = cdp.eval("""(() => ({
          msg: document.getElementById('wx-stale').textContent,
          temp: document.getElementById('wx-temp').textContent
        }))()""")
        evidence["first_fetch_failed"] = first
        if "Weather unavailable" not in (first or {}).get("msg", ""):
            raise AssertionError(f"first failed fetch did not say Weather unavailable: {first}")
        if (first or {}).get("temp"):
            raise AssertionError(f"first failed fetch showed a number: {first}")

        cdp.send("Network.setBlockedURLs", {"urls": []})
        cdp.send("Page.reload", {"ignoreCache": True})
        wait_until(cdp, "document.getElementById('wx-temp') && document.getElementById('wx-temp').textContent.includes('°')", timeout=12)
        live = cdp.eval("""(() => ({
          temp: document.getElementById('wx-temp').textContent,
          cond: document.getElementById('wx-cond').textContent,
          hours: document.getElementById('wx-hours').childElementCount
        }))()""")
        evidence["live_weather"] = live

        stale = cdp.eval("""(async () => {
          wxLoadGen += 1;
          const past = Date.now() - 21 * 60 * 1000;
          wx = { current: { temperature_2m: 61, weather_code: 999, is_day: 1 },
                 hourly: { time: [], temperature_2m: [], weather_code: [], is_day: [] } };
          wxGoodAt = past;
          wxTriedAt = Date.now();
          await renderWeather();
          const el = document.getElementById('wx-stale');
          const style = getComputedStyle(el);
          const freshAt = Date.now() - 10 * 60 * 1000;
          const aged = { msg: el.textContent, expected: hmNy(new Date(past)),
            color: style.color, size: style.fontSize, align: style.alignSelf,
            justify: style.justifyContent };
          wxGoodAt = freshAt;
          wxTriedAt = Date.now();
          await renderWeather();
          const quiet = document.getElementById('wx-stale').textContent;
          wxGoodAt = Date.now() - 3 * 60 * 60 * 1000 - 5000;
          await renderWeather();
          return { aged, quiet, dropped: document.getElementById('wx-stale').textContent,
                   temp: document.getElementById('wx-temp').textContent,
                   hours: document.getElementById('wx-hours').childElementCount };
        })()""")
        evidence["stale"] = stale
        if "Couldn't refresh weather" not in stale["aged"]["msg"] or stale["aged"]["expected"] not in stale["aged"]["msg"]:
            raise AssertionError(f"stale line wrong: {stale['aged']}")
        if stale["quiet"]:
            raise AssertionError(f"stale line showed before 20 minutes: {stale['quiet']}")
        if stale["dropped"] != "Weather unavailable" or stale["temp"] or stale["hours"]:
            raise AssertionError(f"3 hour drop wrong: {stale}")
        if stale["aged"]["size"] != "24px":
            raise AssertionError(f"stale size {stale['aged']['size']}")
        if stale["aged"]["color"] != "rgb(171, 166, 157)":
            raise AssertionError(f"stale color {stale['aged']['color']}")

        colors = cdp.eval("""(() => {
          const stage = document.getElementById('stage');
          const ink = getComputedStyle(document.body).backgroundColor;
          const stageBg = getComputedStyle(stage).backgroundColor;
          const date = getComputedStyle(document.getElementById('date')).color;
          const clock = getComputedStyle(document.querySelector('.clock')).color;
          const texts = [...document.querySelectorAll('.stage *')].slice(0, 40).map((el) => getComputedStyle(el).color);
          return { ink, stageBg, date, clock, verdigris: texts.some((c) => c === 'rgb(95, 163, 154)') };
        })()""")
        evidence["colors_1920"] = colors
        if colors["ink"] != "rgb(16, 20, 26)":
            raise AssertionError(f"page background {colors['ink']}")
        if colors["verdigris"]:
            raise AssertionError("Verdigris is still on the stage")

        wait_until(cdp, "document.body.innerText.includes('Netflix')")
        entered = cdp.eval("""(async () => {
          const tiles = [...document.querySelectorAll('.tile')];
          const netflix = tiles.find((tile) => tile.textContent.includes('Netflix'));
          netflix.focus();
          document.body.classList.remove('show-focus');
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 200));
          const ring = getComputedStyle(netflix);
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 50));
          return {
            href: location.pathname,
            outline: ring.outlineColor,
            width: ring.outlineWidth,
            focused: document.activeElement === netflix,
            shown: document.body.classList.contains('show-focus')
          };
        })()""")
        evidence["enter_netflix"] = entered
        if "index" not in entered["href"] and entered["href"] not in ("/", ""):
            raise AssertionError(f"Enter left Home: {entered}")
        if entered["outline"] != "rgb(169, 194, 218)" or entered["width"] != "6px":
            raise AssertionError(f"focus ring {entered}")

        cdp.eval("document.querySelector('.amb') && (document.querySelector('.amb').style.opacity = '0')")
        cdp.eval("document.documentElement.classList.remove('night')")
        time.sleep(0.2)
        rect = cdp.eval("""(() => {
          const r = document.querySelector('.clock').getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: Math.min(r.height, 80) };
        })()""")
        day = cdp.send("Page.captureScreenshot", {"format": "png", "clip": {
            "x": rect["x"], "y": rect["y"], "width": rect["width"], "height": rect["height"], "scale": 1,
        }})
        cdp.eval("""(() => {
          document.documentElement.classList.add('night');
          const amb = document.querySelector('.amb');
          if (amb) amb.style.opacity = '0.35';
        })()""")
        time.sleep(0.2)
        night = cdp.send("Page.captureScreenshot", {"format": "png", "clip": {
            "x": rect["x"], "y": rect["y"], "width": rect["width"], "height": rect["height"], "scale": 1,
        }})
        day_luma = glyph_luma(base64.b64decode(day["data"]))
        night_luma = glyph_luma(base64.b64decode(night["data"]))
        ratio = night_luma / day_luma if day_luma else 0
        text_opacity = cdp.eval("getComputedStyle(document.querySelector('.clock')).opacity")
        evidence["night"] = {
            "day_luma": round(day_luma, 1),
            "night_luma": round(night_luma, 1),
            "ratio": round(ratio, 3),
            "clock_opacity": text_opacity,
        }
        if text_opacity != "1":
            raise AssertionError(f"clock opacity {text_opacity}")
        if not (0.50 <= ratio <= 0.75):
            raise AssertionError(f"night dim ratio {ratio} (expected about 0.60, not a second dim)")

        fit = cdp.eval("""(() => ({
          layout: document.documentElement.dataset.layout,
          scroll: document.documentElement.scrollHeight - innerHeight,
          wide: document.documentElement.scrollWidth - innerWidth,
          w: innerWidth, h: innerHeight
        }))()""")
        evidence["fit_1920"] = fit
        if fit["layout"] != "laptop" or fit["scroll"] > 2 or fit["wide"] > 2:
            raise AssertionError(f"1920 scroll {fit}")

        cdp.send("Page.navigate", {"url": base + "/dashboard.html"})
        wait_until(cdp, "document.getElementById('pin-form') && !document.getElementById('pin-form').hidden")
        cdp.eval(f"""(() => {{
          document.getElementById('pin-input').value = {json.dumps(PIN)};
          document.getElementById('pin-form').requestSubmit();
        }})()""")
        wait_until(cdp, "document.body.innerText.includes('Busy')")
        guest = cdp.eval("""(() => ({
          text: document.body.innerText,
          html: document.getElementById('today-list').innerHTML,
          held: data ? JSON.stringify(data) : ''
        }))()""")
        evidence["guest_has_busy"] = "Busy" in guest["text"]
        if TITLE in guest["text"] or TITLE in guest["html"] or TITLE in guest["held"]:
            raise AssertionError("guest dashboard showed the event title")
        if DEADLINE in guest["text"] or MONEY in guest["text"]:
            raise AssertionError("guest dashboard showed deadlines or money")
        meteo = cdp.eval("""performance.getEntriesByType('resource').filter((e) => e.name.includes('open-meteo')).length""")
        evidence["dashboard_meteo_requests"] = meteo
        if meteo:
            raise AssertionError(f"dashboard fetched weather {meteo} times")

        cdp.eval("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', bubbles: true }))")
        wait_until(cdp, f"document.body.innerText.includes({json.dumps(TITLE)})")
        shown = cdp.eval("document.body.innerText")
        if DEADLINE not in shown or MONEY not in shown:
            raise AssertionError("show all did not reveal the fixture")
        cdp.eval("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', bubbles: true }))")
        wait_until(cdp, f"!document.body.innerText.includes({json.dumps(TITLE)})")
        again = cdp.eval("document.getElementById('today-list').innerHTML")
        if TITLE in again or DEADLINE in again:
            raise AssertionError("titles stayed in the DOM after returning to guest")

        locked = cdp.eval(f"""(async () => {{
          const lock = await fetch('lock', {{ method: 'POST', cache: 'no-store' }});
          const full = await fetch('data.json', {{ cache: 'no-store', headers: {{ 'X-Slate-Full': '1' }} }});
          const text = await full.text();
          return {{
            lockStatus: lock.status,
            fullStatus: full.status,
            hasTitle: text.includes({json.dumps(TITLE)}),
            hasDeadline: text.includes({json.dumps(DEADLINE)})
          }};
        }})()""")
        evidence["sign_out"] = locked
        if locked["lockStatus"] != 200 or locked["fullStatus"] != 401:
            raise AssertionError(f"sign-out did not close the session: {locked}")
        if locked["hasTitle"] or locked["hasDeadline"]:
            raise AssertionError(f"sign-out still returned private text: {locked}")
        cdp.eval("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', bubbles: true }))")
        wait_until(cdp, "document.getElementById('pin-form') && !document.getElementById('pin-form').hidden")
        if TITLE in cdp.eval("document.body.innerText"):
            raise AssertionError("title stayed on screen after lock")

        for label, width, height, mobile in (
            ("mac", 1440, 900, False),
            ("iphone", 390, 844, True),
            ("tv720", 1280, 720, False),
        ):
            cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile,
            })
            cdp.send("Page.navigate", {"url": base + "/index.html"})
            wait_until(cdp, "document.querySelectorAll('.tile').length >= 1")
            info = cdp.eval("""(() => ({
              layout: document.documentElement.dataset.layout,
              tiles: document.querySelectorAll('.tile').length,
              w: innerWidth, h: innerHeight,
              text: document.body.innerText.slice(0, 80)
            }))()""")
            evidence[label] = info
            if info["tiles"] < 1:
                raise AssertionError(f"{label} showed no tiles: {info}")
            if TITLE in cdp.eval("document.body.innerText"):
                raise AssertionError(f"{label} showed the event title")
        if evidence["tv720"]["layout"] != "laptop":
            raise AssertionError(f"1280x720 layout {evidence['tv720']}")
        if evidence["iphone"]["layout"] != "phone":
            raise AssertionError(f"iPhone layout {evidence['iphone']}")
        if evidence["mac"]["layout"] != "laptop":
            raise AssertionError(f"Mac layout {evidence['mac']}")
        try:
            cdp.sock.close()
        except OSError:
            pass
        return evidence
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


class BrowserTests(unittest.TestCase):
    def test_browser_at_tv_mac_and_iphone(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        local = root / "data.local.json"
        public = root / "data.json"
        local.write_text(json.dumps(FIXTURE), encoding="utf-8")
        old = (server.LOCAL, server.PUBLIC, server.EXPECTED_PIN, server.FULL_PAYLOAD)
        server.LOCAL = local
        server.PUBLIC = public
        server.EXPECTED_PIN = PIN
        server.FULL_PAYLOAD = None
        server.CATALOG_IDS = server.load_catalog_ids()
        server.AMBIENT_PRESETS = server.load_ambient_preset_keys()
        server.FAILS.clear()
        server.SESSIONS.clear()
        httpd = server.Server(("127.0.0.1", 0), server.Handler)
        httpd.require_pin = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            evidence = run_browser(base)
            out = Path(self.tmp.name) / "evidence.json"
            out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print("\nBROWSER_EVIDENCE")
            print(json.dumps(evidence, indent=2))
        finally:
            httpd.shutdown()
            httpd.server_close()
            server.LOCAL, server.PUBLIC, server.EXPECTED_PIN, server.FULL_PAYLOAD = old
            server.FAILS.clear()
            server.SESSIONS.clear()
            self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
