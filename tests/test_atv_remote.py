#!/usr/bin/env python3
"""Android TV remote and Wi-Fi remote broker tests (127.0.0.1 only)."""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import atv_remote  # noqa: E402
import isolate  # noqa: E402
import server  # noqa: E402

# Pin, settings, schedule, gallery, and the map key stay out of this checkout.
isolate.install(server)


class FakeTv:
    def __init__(self, pair_port: int, cmd_port: int, cert_file: Path, key_file: Path) -> None:
        self.pair_port = pair_port
        self.cmd_port = cmd_port
        self.cert_file = cert_file
        self.key_file = key_file
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.last_key: int | None = None
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(cert_file), str(key_file))
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    def start(self) -> None:
        for port, worker in ((self.pair_port, self._pair_worker), (self.cmd_port, self._cmd_worker)):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            thread = threading.Thread(target=worker, args=(sock,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self) -> None:
        self.stop.set()

    def _accept(self, sock: socket.socket) -> ssl.SSLSocket:
        sock.settimeout(0.5)
        while not self.stop.is_set():
            try:
                raw, _addr = sock.accept()
                return self.ctx.wrap_socket(raw, server_side=True)
            except socket.timeout:
                continue
            except OSError:
                break
        raise OSError("stopped")

    def _pair_worker(self, sock: socket.socket) -> None:
        try:
            conn = self._accept(sock)
        except OSError:
            return
        try:
            _ = atv_remote.read_frame(conn, 5)
            conn.sendall(atv_remote.encode_outer(200, {11: b""}))
            _ = atv_remote.read_frame(conn, 5)
            enc = atv_remote.encode_field_varint(1, 3) + atv_remote.encode_field_varint(2, 6)
            conn.sendall(atv_remote.encode_outer(200, {20: enc}))
            _ = atv_remote.read_frame(conn, 5)
            conn.sendall(atv_remote.encode_outer(200, {31: b""}))
            secret_msg = atv_remote.read_frame(conn, 10)
            if atv_remote.message_has_field(secret_msg, 40):
                conn.sendall(atv_remote.encode_outer(200, {41: b"\x01"}))
        except (OSError, ConnectionError, ValueError, ssl.SSLError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _cmd_worker(self, sock: socket.socket) -> None:
        try:
            conn = self._accept(sock)
        except OSError:
            return
        try:
            atv_remote.write_frame(conn, atv_remote.remote_configure_reply(99))
            _ = atv_remote.read_frame(conn, 5)
            atv_remote.write_frame(conn, atv_remote.remote_set_active(99))
            start = atv_remote.encode_field_bytes(40, atv_remote.encode_field_varint(1, 1))
            atv_remote.write_frame(conn, start)
            while not self.stop.is_set():
                msg = atv_remote.read_frame(conn, 2)
                if atv_remote.message_has_field(msg, 10):
                    pos = 0
                    while pos < len(msg):
                        tag, pos = atv_remote.read_varint(msg, pos)
                        if (tag >> 3) == 10 and (tag & 7) == 2:
                            ln, pos = atv_remote.read_varint(msg, pos)
                            sub = msg[pos:pos + ln]
                            sp = 0
                            while sp < len(sub):
                                stag, sp = atv_remote.read_varint(sub, sp)
                                if (stag >> 3) == 1 and (stag & 7) == 0:
                                    self.last_key, sp = atv_remote.read_varint(sub, sp)
                                elif (stag & 7) == 0:
                                    _, sp = atv_remote.read_varint(sub, sp)
                                elif (stag & 7) == 2:
                                    sln, sp = atv_remote.read_varint(sub, sp)
                                    sp += sln
                if atv_remote.message_has_field(msg, 9):
                    break
        except (OSError, ConnectionError, ValueError, ssl.SSLError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def _make_cert(tmp: Path) -> tuple[Path, Path]:
    cfg = tmp / "openssl.cnf"
    cfg.write_text("[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=FakeTV\n", encoding="utf-8")
    cert = tmp / "tv.crt"
    key = tmp / "tv.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "30",
            "-sha256",
            "-config",
            str(cfg),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    return cert, key


class RemoteHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.atv_path = root / "atv.local"
        self._atv_saved = atv_remote.ATV_PATH
        atv_remote.set_atv_path_for_tests(self.atv_path)
        self._old = (
            server.REMOTE_EVENTS,
            server.REMOTE_SEQ,
            server.REMOTE_SESSIONS,
            server.REMOTE_PAIRINGS,
            server.REMOTE_TV_LAST,
        )
        server.REMOTE_EVENTS.clear()
        server.REMOTE_SEQ = 0
        server.REMOTE_SESSIONS.clear()
        server.REMOTE_PAIRINGS.clear()
        server.REMOTE_TV_LAST = 0.0
        self.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        self.httpd.require_pin = False
        self.httpd.lan_enabled = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.REMOTE_EVENTS.clear()
        server.REMOTE_SEQ = 0
        server.REMOTE_SESSIONS.clear()
        server.REMOTE_PAIRINGS.clear()
        self.tmp.cleanup()
        atv_remote.set_atv_path_for_tests(self._atv_saved)

    def _post(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else b""
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        conn.request("POST", path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        if not data:
            return resp.status, {}
        try:
            return resp.status, json.loads(data)
        except json.JSONDecodeError:
            return resp.status, data

    def _phone_pair(self):
        status, body = self._post("/remote/v1/pairing.json")
        self.assertEqual(status, 200)
        code = body["code"]
        status, _body = self._post("/remote/v1/pair.json", {"code": code})
        self.assertEqual(status, 200)
        token = next(iter(server.REMOTE_SESSIONS))
        return f"{server.REMOTE_COOKIE}={token}"

    def test_golden_bytes(self):
        self.assertEqual(atv_remote.GOLDEN_PAIRING_REQUEST, atv_remote.pairing_request_message())
        self.assertEqual(atv_remote.GOLDEN_DPAD_DOWN, atv_remote.remote_key_message(20))

    def test_polo_fixture(self):
        digest = atv_remote.polo_check(0xAB, 0x10001, 0xCD, 0x10001, "CA1A2B")
        self.assertEqual(
            digest.hex(),
            "ca65ad099ee0eda253d993dfe81fca5d1bcddf1f0bfe97bff807099e6216bb41",
        )
        with self.assertRaises(ValueError):
            atv_remote.polo_check(0xAB, 0x10001, 0xCD, 0x10001, "001A2B")

    def test_remote_requires_lan(self):
        self.httpd.lan_enabled = False
        status, body = self._post("/remote/v1/command.json", {"type": "key", "key": "ArrowDown"})
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "lan")

    def test_arrow_down_queued_without_tv(self):
        cookie = self._phone_pair()
        status, body = self._post(
            "/remote/v1/command.json",
            {"type": "key", "key": "ArrowDown"},
            {"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("path"), "page")
        self.assertTrue(server.REMOTE_EVENTS)

    def test_heartbeat_ignores_phone_until_tv(self):
        status, body = self._post("/remote/v1/heartbeat.json", {"page": "index"})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ignored"))
        self.assertFalse(server.remote_tv_online())
        status, body = self._post("/remote/v1/heartbeat.json", {"page": "dashboard", "tv": True})
        self.assertEqual(status, 200)
        self.assertNotIn("ignored", body)
        self.assertTrue(server.remote_tv_online())
        self.assertEqual(server.REMOTE_TV_PAGE, "dashboard")

    def test_volume_409_when_tv_down(self):
        cookie = self._phone_pair()
        status, body = self._post(
            "/remote/v1/command.json",
            {"type": "key", "key": "VolumeUp"},
            {"Cookie": cookie},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body.get("error"), "tv")

    def test_atv_local_blocked(self):
        status, _body = self._get("/atv.local")
        self.assertEqual(status, 404)

    def test_note_tv_host(self):
        store = atv_remote.AtvStore(self.atv_path)
        store.note_host("10.1.2.3")
        store.load()
        self.assertEqual(store.host, "10.1.2.3")
        store.note_host("127.0.0.1")
        store.note_host("8.8.8.8")
        store.load()
        self.assertEqual(store.host, "10.1.2.3")


class AtvIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._atv_saved = atv_remote.ATV_PATH
        atv_remote.set_atv_path_for_tests(self.root / "atv.local")
        atv_remote.PAIR_PORT = 6477
        atv_remote.COMMAND_PORT = 6476
        self.cert, self.key = _make_cert(self.root)
        self.fake = FakeTv(atv_remote.PAIR_PORT, atv_remote.COMMAND_PORT, self.cert, self.key)
        self.fake.start()
        store = atv_remote.AtvStore()
        store.host = "127.0.0.1"
        store.save()
        self.svc = atv_remote.get_service(lambda: True)

    def tearDown(self):
        self.fake.close()
        atv_remote.PAIR_PORT = 6467
        atv_remote.COMMAND_PORT = 6466
        atv_remote.set_atv_path_for_tests(self._atv_saved)
        self.tmp.cleanup()

    def test_pair_and_key_inject(self):
        atv_remote.ensure_client_credentials(atv_remote.AtvStore())
        code, payload = self.svc.begin_tv_pair("127.0.0.1", "127.0.0.1")
        self.assertEqual(code, 200)
        self.assertEqual(payload.get("state"), "waiting")
        cert_der = ssl.PEM_cert_to_DER_cert(self.cert.read_text(encoding="utf-8"))
        client_mod, client_exp = atv_remote.rsa_mod_exp_from_der(
            ssl.PEM_cert_to_DER_cert(atv_remote.AtvStore().cert_pem or self._client_der())
        )
        server_mod, server_exp = atv_remote.rsa_mod_exp_from_der(cert_der)
        # Pick a valid code prefix by search (small space for test)
        chosen = None
        for prefix in range(256):
            code_str = f"{prefix:02X}1A2B"
            try:
                atv_remote.polo_check(client_mod, client_exp, server_mod, server_exp, code_str)
                chosen = code_str
                break
            except ValueError:
                continue
        self.assertTrue(chosen)
        status, body = self.svc.submit_tv_code(chosen)
        self.assertEqual(status, 200, body)
        deadline = time.time() + 8
        while time.time() < deadline and not self.svc.ready():
            time.sleep(0.1)
        self.assertTrue(self.svc.ready())
        self.assertTrue(self.svc.inject_key("ArrowDown"))
        deadline = time.time() + 3
        while time.time() < deadline and self.fake.last_key != 20:
            time.sleep(0.05)
        self.assertEqual(self.fake.last_key, 20)

    def _client_der(self) -> bytes:
        atv_remote.ensure_client_credentials(atv_remote.AtvStore())
        return ssl.PEM_cert_to_DER_cert(atv_remote.AtvStore().cert_pem)


if __name__ == "__main__":
    unittest.main()
