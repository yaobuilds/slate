"""Android TV Remote Service client (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

PAIR_PORT = 6467
COMMAND_PORT = 6466
FEATURE_MASK = 99  # PING(1) | KEY(2) | POWER(32) | VOLUME(64)
STEP_TIMEOUT = 10.0
PAIRING_WAIT_S = 180.0
HANDSHAKE_FAIL_S = 15.0
RECONNECT_DELAYS = (1, 2, 4, 30)

GOLDEN_PAIRING_REQUEST = bytes.fromhex(
    "19080210c80152120a0961747672656d6f74651205536c617465"
)
GOLDEN_DPAD_DOWN = bytes.fromhex("06520408141003")

KEY_MAP = {
    "ArrowUp": 19,
    "ArrowDown": 20,
    "ArrowLeft": 21,
    "ArrowRight": 22,
    "Enter": 23,
    "Escape": 4,
    "Backspace": 4,
    "BrowserBack": 4,
    "g": 35,
    "G": 35,
    "Home": 3,
    "VolumeUp": 24,
    "VolumeDown": 25,
    "VolumeMute": 164,
}

PAGE_KEYS = {
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Enter",
    "Escape",
    "Backspace",
    "BrowserBack",
    "g",
    "G",
    "Home",
}
VOLUME_KEYS = {"VolumeUp", "VolumeDown", "VolumeMute"}

ROOT = Path(__file__).resolve().parent
ATV_PATH = ROOT / "atv.local"

STATUS_UNPAIRED = "unpaired"
STATUS_WAITING = "waiting"
STATUS_READY = "ready"
STATUS_OFFLINE = "offline"
STATUS_REJECTED = "rejected"


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        out.append(bits | (0x80 if value else 0))
        if not value:
            break
    return bytes(out)


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
    raise ValueError("truncated varint")


def encode_field_varint(field: int, value: int) -> bytes:
    return encode_varint((field << 3) | 0) + encode_varint(value)


def encode_field_bytes(field: int, payload: bytes) -> bytes:
    return encode_varint((field << 3) | 2) + encode_varint(len(payload)) + payload


def encode_string_field(field: int, text: str) -> bytes:
    raw = text.encode("utf-8")
    return encode_field_bytes(field, raw)


def encode_outer(status: int = 200, fields: dict[int, bytes] | None = None) -> bytes:
    body = encode_field_varint(1, 2) + encode_field_varint(2, status)
    for field_num, payload in (fields or {}).items():
        body += encode_field_bytes(field_num, payload)
    return encode_varint(len(body)) + body


def pairing_request_message() -> bytes:
    inner = encode_string_field(1, "atvremote") + encode_string_field(2, "Slate")
    msg = encode_field_varint(1, 2) + encode_field_varint(2, 200) + encode_field_bytes(10, inner)
    framed = encode_varint(len(msg)) + msg
    if framed != GOLDEN_PAIRING_REQUEST:
        raise RuntimeError("pairing request golden mismatch")
    return framed


def options_message() -> bytes:
    enc = encode_field_varint(1, 3) + encode_field_varint(2, 6)
    inner = encode_field_bytes(1, enc) + encode_field_varint(3, 1)
    return encode_outer(200, {20: inner})


def configuration_message() -> bytes:
    enc = encode_field_varint(1, 3) + encode_field_varint(2, 6)
    inner = encode_field_bytes(1, enc) + encode_field_varint(2, 1)
    return encode_outer(200, {30: inner})


def secret_message(digest: bytes) -> bytes:
    inner = encode_field_bytes(1, digest)
    return encode_outer(200, {40: inner})


def remote_key_message(key_code: int, direction: int = 3) -> bytes:
    inner = encode_field_varint(1, key_code) + encode_field_varint(2, direction)
    msg = encode_field_bytes(10, inner)
    framed = encode_varint(len(msg)) + msg
    if key_code == 20 and framed != GOLDEN_DPAD_DOWN:
        raise RuntimeError("dpad down golden mismatch")
    return framed


def remote_configure_reply(code1: int) -> bytes:
    dev = (
        encode_field_varint(3, 1)
        + encode_string_field(4, "1")
        + encode_string_field(5, "atvremote")
        + encode_string_field(6, "1.0.0")
    )
    inner = encode_field_varint(1, code1) + encode_field_bytes(2, dev)
    return encode_field_bytes(1, inner)


def remote_set_active(active: int) -> bytes:
    inner = encode_field_varint(1, active)
    return encode_field_bytes(2, inner)


def remote_ping_response(val1: int) -> bytes:
    inner = encode_field_varint(1, val1)
    return encode_field_bytes(9, inner)


def read_frame(sock: ssl.SSLSocket, timeout: float | None = None) -> bytes:
    if timeout is not None:
        sock.settimeout(timeout)
    header = b""
    while len(header) < 1:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("closed")
        header += chunk
    length, _ = read_varint(header, 0)
    # varint may span bytes; re-read properly
    data = header
    while True:
        try:
            length, used = read_varint(data, 0)
            if used == len(data):
                break
        except ValueError:
            pass
        more = sock.recv(1)
        if not more:
            raise ConnectionError("closed")
        data += more
    length, used = read_varint(data, 0)
    rest = length
    body = b""
    while len(body) < rest:
        chunk = sock.recv(rest - len(body))
        if not chunk:
            raise ConnectionError("closed")
        body += chunk
    return body


def write_frame(sock: ssl.SSLSocket, payload: bytes) -> None:
    sock.sendall(encode_varint(len(payload)) + payload)


def message_has_field(data: bytes, field_num: int) -> bool:
    pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        wire = tag & 7
        num = tag >> 3
        if wire == 0:
            _, pos = read_varint(data, pos)
        elif wire == 1:
            pos += 8
        elif wire == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        elif wire == 5:
            pos += 4
        else:
            return False
        if num == field_num:
            return True
    return False


def outer_status(data: bytes) -> int | None:
    pos = 0
    status = None
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        wire = tag & 7
        num = tag >> 3
        if wire == 0:
            val, pos = read_varint(data, pos)
            if num == 2:
                status = val
        elif wire == 1:
            pos += 8
        elif wire == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        elif wire == 5:
            pos += 4
    return status


def ping_val1(data: bytes) -> int | None:
    if not message_has_field(data, 8):
        return None
    pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        wire = tag & 7
        num = tag >> 3
        if wire == 2 and num == 8:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            sp = 0
            while sp < len(sub):
                stag, sp = read_varint(sub, sp)
                if (stag & 7) == 0 and (stag >> 3) == 1:
                    val, sp = read_varint(sub, sp)
                    return val
        elif wire == 0:
            _, pos = read_varint(data, pos)
        elif wire == 1:
            pos += 8
        elif wire == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        elif wire == 5:
            pos += 4
    return None


def configure_code1(data: bytes) -> int | None:
    pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        wire = tag & 7
        num = tag >> 3
        if wire == 2 and num == 1:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            sp = 0
            while sp < len(sub):
                stag, sp = read_varint(sub, sp)
                if (stag & 7) == 0 and (stag >> 3) == 1:
                    val, sp = read_varint(sub, sp)
                    return val
                elif (stag & 7) == 0:
                    _, sp = read_varint(sub, sp)
                elif (stag & 7) == 2:
                    sln, sp = read_varint(sub, sp)
                    sp += sln
                elif (stag & 7) == 1:
                    sp += 8
                elif (stag & 7) == 5:
                    sp += 4
        elif wire == 0:
            _, pos = read_varint(data, pos)
        elif wire == 1:
            pos += 8
        elif wire == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        elif wire == 5:
            pos += 4
    return None


def polo_check(client_n, client_e, server_n, server_e, code: str) -> bytes:
    digest = hashlib.sha256()
    digest.update(bytes.fromhex(f"{client_n:X}"))
    digest.update(bytes.fromhex(f"0{client_e:X}"))
    digest.update(bytes.fromhex(f"{server_n:X}"))
    digest.update(bytes.fromhex(f"0{server_e:X}"))
    digest.update(bytes.fromhex(code[2:]))
    out = digest.digest()
    if out[0] != int(code[0:2], 16):
        raise ValueError("code check byte")
    return out


def rsa_mod_exp_from_der(der: bytes) -> tuple[int, int]:
    pos = 0
    if der[pos] != 0x30:
        raise ValueError("not der")
    _, pos = _read_asn1_len(der, pos + 1)
    # certificate or subjectPublicKeyInfo
    return _walk_to_rsa(der, pos)


def _read_asn1_len(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos]
    pos += 1
    if first & 0x80:
        count = first & 0x7F
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    else:
        length = first
    return length, pos


def _walk_to_rsa(data: bytes, pos: int) -> tuple[int, int]:
    """Find first SEQUENCE of two INTEGERs inside SPKI bit string."""
    while pos < len(data):
        tag = data[pos]
        pos += 1
        length, pos = _read_asn1_len(data, pos)
        end = pos + length
        if tag == 0x30:
            try:
                return _read_rsa_seq(data, pos, end)
            except ValueError:
                pass
        pos = end
    raise ValueError("rsa not found")


def _read_rsa_seq(data: bytes, pos: int, end: int) -> tuple[int, int]:
    nums = []
    while pos < end:
        tag = data[pos]
        pos += 1
        length, pos = _read_asn1_len(data, pos)
        chunk = data[pos:pos + length]
        pos += length
        if tag == 0x02:
            nums.append(int.from_bytes(chunk.lstrip(b"\x00") or b"\x00", "big"))
        elif tag == 0x03 and chunk:
            inner = chunk[1:]
            n, e = _walk_to_rsa(inner, 0)
            return n, e
        elif tag == 0x30:
            try:
                return _read_rsa_seq(data, pos - length, pos - length + length)
            except ValueError:
                pass
    if len(nums) >= 2:
        return nums[0], nums[1]
    raise ValueError("rsa seq")


def private_ip_ok(raw: str, client_is_loopback: bool = False) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if ip.is_loopback:
        return client_is_loopback
    if ip.is_private and not ip.is_loopback:
        return True
    return False


def protect_atv_file() -> None:
    try:
        os.chmod(ATV_PATH, 0o600)
    except OSError:
        pass


class AtvStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ATV_PATH
        self.lock = threading.RLock()
        self.host = ""
        self.cert_pem = ""
        self.key_pem = ""
        self.tv_cert_der = b""
        self.load()

    def load(self) -> None:
        with self.lock:
            self.host = ""
            self.cert_pem = ""
            self.key_pem = ""
            self.tv_cert_der = b""
            if not self.path.exists():
                return
            text = self.path.read_text(encoding="utf-8")
            lines = text.splitlines()
            idx = 0
            if lines and lines[0].startswith("host="):
                self.host = lines[0].split("=", 1)[1].strip()
                idx = 1
            rest = "\n".join(lines[idx:])
            cert_match = re.search(
                r"-----BEGIN CERTIFICATE-----\n(.+?)\n-----END CERTIFICATE-----",
                rest,
                re.DOTALL,
            )
            key_match = re.search(
                r"-----BEGIN (?:RSA )?PRIVATE KEY-----\n(.+?)\n-----END (?:RSA )?PRIVATE KEY-----",
                rest,
                re.DOTALL,
            )
            tv_match = re.search(
                r"-----BEGIN TV-CERTIFICATE-----\n(.+?)\n-----END TV-CERTIFICATE-----",
                rest,
                re.DOTALL,
            )
            if cert_match:
                self.cert_pem = "-----BEGIN CERTIFICATE-----\n" + cert_match.group(1).strip() + "\n-----END CERTIFICATE-----\n"
            if key_match:
                header = "PRIVATE KEY" if "RSA" not in key_match.group(0) else "RSA PRIVATE KEY"
                self.key_pem = f"-----BEGIN {header}-----\n{key_match.group(1).strip()}\n-----END {header}-----\n"
            if tv_match:
                self.tv_cert_der = base64.b64decode("".join(tv_match.group(1).split()))

    def save(self) -> None:
        with self.lock:
            parts = []
            if self.host:
                parts.append(f"host={self.host}")
            if self.cert_pem:
                parts.append(self.cert_pem.strip())
            if self.key_pem:
                parts.append(self.key_pem.strip())
            if self.tv_cert_der:
                b64 = base64.encodebytes(self.tv_cert_der).decode("ascii").strip()
                parts.append("-----BEGIN TV-CERTIFICATE-----")
                parts.append(b64)
                parts.append("-----END TV-CERTIFICATE-----")
            text = "\n".join(parts) + ("\n" if parts else "")
            self.path.write_text(text, encoding="utf-8")
            protect_atv_file()

    def note_host(self, ip: str) -> None:
        if not private_ip_ok(ip):
            return
        with self.lock:
            if self.host == ip:
                return
            self.host = ip
            self.save()

    def tv_known(self) -> bool:
        with self.lock:
            return bool(self.host and private_ip_ok(self.host))

    def pinned(self) -> bool:
        with self.lock:
            return bool(self.tv_cert_der)


def openssl_available() -> bool:
    return bool(shutil_which("openssl"))


def shutil_which(name: str) -> str | None:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def ensure_client_credentials(store: AtvStore) -> None:
    with store.lock:
        if store.cert_pem and store.key_pem:
            return
    if not openssl_available():
        raise RuntimeError("cert")
    tmp = store.path.parent
    cfg = tmp / ".atv-openssl.cnf"
    cfg.write_text(
        "[req]\n"
        "distinguished_name=dn\n"
        "prompt=no\n"
        "[dn]\n"
        "CN=Slate\n",
        encoding="utf-8",
    )
    key_path = tmp / ".atv-client.key"
    cert_path = tmp / ".atv-client.crt"
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
                "-days",
                "3650",
                "-sha256",
                "-config",
                str(cfg),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        cert_pem = cert_path.read_text(encoding="utf-8")
        key_pem = key_path.read_text(encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cert") from exc
    finally:
        cfg.unlink(missing_ok=True)
        key_path.unlink(missing_ok=True)
        cert_path.unlink(missing_ok=True)
    with store.lock:
        store.cert_pem = cert_pem
        store.key_pem = key_pem
        store.save()


class AtvRemoteService:
    def __init__(self, enabled_fn) -> None:
        self.enabled_fn = enabled_fn
        self.store = AtvStore()
        self.lock = threading.RLock()
        self.pair_thread: threading.Thread | None = None
        self.cmd_thread: threading.Thread | None = None
        self.pair_sock: ssl.SSLSocket | None = None
        self.cmd_sock: ssl.SSLSocket | None = None
        self.pair_stop = threading.Event()
        self.cmd_stop = threading.Event()
        self.waiting = threading.Event()
        self.pair_done = threading.Event()
        self.pair_error: str | None = None
        self.server_mod = 0
        self.server_exp = 0
        self.client_mod = 0
        self.client_exp = 0
        self.service_status = STATUS_UNPAIRED
        self.session_ready = threading.Event()
        self.active_mask = 0
        self._cmd_send_lock = threading.Lock()
        self._pair_generation = 0

    def start_background(self) -> None:
        if self.store.pinned() and self.store.host:
            self._start_command_thread()

    def set_enabled(self, on: bool) -> None:
        if not on:
            self._close_pairing()
            self._close_command()
            with self.lock:
                self.service_status = STATUS_UNPAIRED if not self.store.pinned() else STATUS_OFFLINE

    def status(self) -> str:
        with self.lock:
            if not self.enabled_fn():
                return STATUS_OFFLINE
            if self.session_ready.is_set() and self.cmd_sock:
                return STATUS_READY
            if self.waiting.is_set():
                return STATUS_WAITING
            if self.service_status == STATUS_REJECTED:
                return STATUS_REJECTED
            if self.store.pinned() and self.store.host:
                return STATUS_OFFLINE
            return STATUS_UNPAIRED

    def tv_known(self) -> bool:
        return self.store.tv_known()

    def ready(self) -> bool:
        return self.enabled_fn() and self.session_ready.is_set() and self.cmd_sock is not None

    def inject_key(self, key: str) -> bool:
        code = KEY_MAP.get(key)
        if code is None:
            return False
        sock = self.cmd_sock
        if not self.ready() or not sock:
            return False
        msg = remote_key_message(code)
        payload = msg[read_varint(msg, 0)[1]:]
        with self._cmd_send_lock:
            write_frame(sock, payload)
        return True

    def begin_tv_pair(self, host: str | None, client_ip: str) -> tuple[int, dict]:
        if not self.enabled_fn():
            return 403, {"error": "remote"}
        if not openssl_available():
            return 500, {"error": "cert"}
        try:
            ensure_client_credentials(self.store)
        except RuntimeError:
            return 500, {"error": "cert"}
        with self.lock:
            if host:
                if not private_ip_ok(host, client_ip in {"127.0.0.1", "::1"}):
                    return 400, {"error": "bad"}
                self.store.host = host
                self.store.save()
            elif not self.store.host:
                return 409, {"error": "no-host"}
            target = self.store.host
        self._close_pairing()
        self.pair_error = None
        self.waiting.clear()
        self.pair_done.clear()
        self._pair_generation += 1
        gen = self._pair_generation
        self.pair_stop = threading.Event()
        self.pair_thread = threading.Thread(
            target=self._pair_worker,
            args=(target, gen),
            name="atv-pair",
            daemon=True,
        )
        self.pair_thread.start()
        if not self.waiting.wait(timeout=HANDSHAKE_FAIL_S):
            self._close_pairing()
            if self.pair_error == "unreachable":
                return 502, {"error": "unreachable"}
            return 502, {"error": "unreachable"}
        return 200, {"ok": True, "state": "waiting"}

    def submit_tv_code(self, code: str) -> tuple[int, dict]:
        if not re.fullmatch(r"[0-9a-fA-F]{6}", code or ""):
            return 400, {"error": "bad"}
        if not self.waiting.is_set():
            return 409, {"error": "not-waiting"}
        try:
            digest = polo_check(
                self.client_mod,
                self.client_exp,
                self.server_mod,
                self.server_exp,
                code,
            )
        except ValueError:
            return 401, {"error": "code"}
        sock = self.pair_sock
        if not sock:
            return 502, {"error": "unreachable"}
        secret = secret_message(digest)
        _, used = read_varint(secret, 0)
        try:
            write_frame(sock, secret[used:])
            body = read_frame(sock, STEP_TIMEOUT)
        except (OSError, ConnectionError, ValueError, ssl.SSLError):
            self._fail_pairing()
            return 502, {"error": "unreachable"}
        if outer_status(body) != 200 or not message_has_field(body, 41):
            self._fail_pairing()
            return 401, {"error": "code"}
        try:
            der = sock.getpeercert(binary_form=True)
        except (TypeError, ssl.SSLError):
            der = b""
        if not der:
            self._fail_pairing()
            return 401, {"error": "code"}
        with self.store.lock:
            self.store.tv_cert_der = der
            self.store.save()
        self._close_pairing()
        self.session_ready.clear()
        self._start_command_thread()
        with self.lock:
            self.service_status = STATUS_OFFLINE
        return 200, {"ok": True}

    def note_tv_host(self, ip: str) -> None:
        self.store.note_host(ip)

    def _fail_pairing(self) -> None:
        with self.lock:
            self.service_status = STATUS_UNPAIRED
        self._close_pairing()

    def _close_pairing(self) -> None:
        self.pair_stop.set()
        self.waiting.clear()
        self._pair_generation += 1
        sock = self.pair_sock
        self.pair_sock = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if self.pair_thread and self.pair_thread.is_alive():
            self.pair_thread.join(timeout=0.5)
        self.pair_thread = None

    def _close_command(self) -> None:
        self.cmd_stop.set()
        self.session_ready.clear()
        sock = self.cmd_sock
        self.cmd_sock = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if self.cmd_thread and self.cmd_thread.is_alive():
            self.cmd_thread.join(timeout=0.5)
        self.cmd_thread = None

    def _pair_worker(self, host: str, generation: int) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        cert_file = self.store.path.parent / ".atv-tmp-cert.pem"
        key_file = self.store.path.parent / ".atv-tmp-key.pem"
        with self.store.lock:
            cert = self.store.cert_pem
            key = self.store.key_pem
        try:
            cert_file.write_text(cert, encoding="utf-8")
            key_file.write_text(key, encoding="utf-8")
            os.chmod(key_file, 0o600)
            ctx.load_cert_chain(str(cert_file), str(key_file))
        except (OSError, ssl.SSLError):
            with self.lock:
                self.pair_error = "unreachable"
            return
        finally:
            cert_file.unlink(missing_ok=True)
            key_file.unlink(missing_ok=True)
        sock: ssl.SSLSocket | None = None
        try:
            raw = socket.create_connection((host, PAIR_PORT), timeout=STEP_TIMEOUT)
            sock = ctx.wrap_socket(raw, server_hostname=host)
            self.pair_sock = sock
            peer = sock.getpeercert(binary_form=True) or b""
            if peer:
                self.server_mod, self.server_exp = rsa_mod_exp_from_der(peer)
            cert_der = ssl.PEM_cert_to_DER_cert(self.store.cert_pem)
            self.client_mod, self.client_exp = rsa_mod_exp_from_der(cert_der)
            write_frame(sock, pairing_request_message()[read_varint(pairing_request_message(), 0)[1]:])
            body = read_frame(sock, STEP_TIMEOUT)
            if outer_status(body) != 200:
                raise ConnectionError("status")
            write_frame(sock, options_message()[read_varint(options_message(), 0)[1]:])
            body = read_frame(sock, STEP_TIMEOUT)
            if outer_status(body) != 200:
                raise ConnectionError("status")
            if peer:
                self.server_mod, self.server_exp = rsa_mod_exp_from_der(peer)
            write_frame(sock, configuration_message()[read_varint(configuration_message(), 0)[1]:])
            body = read_frame(sock, STEP_TIMEOUT)
            if outer_status(body) != 200 or not message_has_field(body, 31):
                raise ConnectionError("status")
            if generation != self._pair_generation:
                return
            self.waiting.set()
            deadline = time.monotonic() + PAIRING_WAIT_S
            while time.monotonic() < deadline and not self.pair_stop.is_set():
                time.sleep(0.2)
        except (OSError, ConnectionError, ValueError, ssl.SSLError):
            with self.lock:
                self.pair_error = "unreachable"
                self.service_status = STATUS_UNPAIRED
        finally:
            self.waiting.clear()
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if self.pair_sock is sock:
                self.pair_sock = None

    def _start_command_thread(self) -> None:
        self._close_command()
        if not self.store.host or not self.store.pinned():
            return
        self.cmd_stop = threading.Event()
        self.cmd_thread = threading.Thread(target=self._command_worker, name="atv-cmd", daemon=True)
        self.cmd_thread.start()

    def _command_worker(self) -> None:
        delay_idx = 0
        while not self.cmd_stop.is_set() and self.enabled_fn():
            if not self.store.host or not self.store.tv_cert_der:
                break
            try:
                self._command_session()
                delay_idx = 0
            except _CertRejected:
                with self.lock:
                    self.service_status = STATUS_REJECTED
                break
            except (OSError, ConnectionError, ssl.SSLError, ValueError):
                pass
            if self.cmd_stop.is_set() or not self.enabled_fn():
                break
            wait = RECONNECT_DELAYS[min(delay_idx, len(RECONNECT_DELAYS) - 1)]
            delay_idx = min(delay_idx + 1, len(RECONNECT_DELAYS) - 1)
            if self.cmd_stop.wait(wait):
                break
        self.session_ready.clear()
        self.cmd_sock = None

    def _command_session(self) -> None:
        host = self.store.host
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        cert_file = self.store.path.parent / ".atv-tmp-cert.pem"
        key_file = self.store.path.parent / ".atv-tmp-key.pem"
        with self.store.lock:
            cert_file.write_text(self.store.cert_pem, encoding="utf-8")
            key_file.write_text(self.store.key_pem, encoding="utf-8")
        os.chmod(key_file, 0o600)
        try:
            ctx.load_cert_chain(str(cert_file), str(key_file))
        finally:
            cert_file.unlink(missing_ok=True)
            key_file.unlink(missing_ok=True)
        raw = socket.create_connection((host, COMMAND_PORT), timeout=STEP_TIMEOUT)
        sock = ctx.wrap_socket(raw, server_hostname=host)
        peer = sock.getpeercert(binary_form=True) or b""
        if peer != self.store.tv_cert_der:
            sock.close()
            raise _CertRejected()
        self.cmd_sock = sock
        self.session_ready.clear()
        self.active_mask = 0
        reader = threading.Thread(target=self._command_reader, args=(sock,), daemon=True)
        reader.start()
        while not self.cmd_stop.is_set() and reader.is_alive():
            reader.join(timeout=0.5)
        self.session_ready.clear()
        try:
            sock.close()
        except OSError:
            pass
        self.cmd_sock = None

    def _command_reader(self, sock: ssl.SSLSocket) -> None:
        while not self.cmd_stop.is_set():
            try:
                body = read_frame(sock, STEP_TIMEOUT)
            except (OSError, ConnectionError, ValueError, ssl.SSLError):
                break
            if message_has_field(body, 1):
                code1 = configure_code1(body) or 0
                mask = code1 & FEATURE_MASK
                if not (mask & 2):
                    break
                self.active_mask = mask
                reply = remote_configure_reply(mask)
                write_frame(sock, reply)
            elif message_has_field(body, 2):
                write_frame(sock, remote_set_active(self.active_mask))
            elif message_has_field(body, 8):
                val1 = ping_val1(body) or 0
                write_frame(sock, remote_ping_response(val1))
            elif message_has_field(body, 40):
                self.session_ready.set()
                with self.lock:
                    self.service_status = STATUS_READY
            else:
                continue


class _CertRejected(Exception):
    pass


_SERVICE: AtvRemoteService | None = None


def get_service(enabled_fn) -> AtvRemoteService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = AtvRemoteService(enabled_fn)
    return _SERVICE


def set_atv_path_for_tests(path: Path) -> None:
    global _SERVICE, ATV_PATH
    ATV_PATH = path
    _SERVICE = None
