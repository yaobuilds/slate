#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import email.utils
import hashlib
import html
import math
from email.utils import parsedate_to_datetime
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import shutil
import struct
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

import atv_remote

ROOT = Path(__file__).resolve().parent
PORT = 8000
DISCOVERY_PORT = 8001
LOCAL = ROOT / "data.local.json"
PUBLIC = ROOT / "data.json"
SETTINGS_LOCAL = ROOT / "settings.local.json"
APPS_PUBLIC = ROOT / "apps.json"
CATALOG = ROOT / "apps-catalog.json"
AMBIENT = ROOT / "ambient.json"
CALENDAR_CACHE_LOCAL = ROOT / "calendar-cache.local.json"
DEFAULT_HOME_APPS = ["netflix", "hulu", "hbo", "youtube", "youtube-music"]
DEFAULT_AMBIENT_PRESET = "aurora"
DEFAULT_LOCATION = {
    "lat": 40.7128,
    "lon": -74.0060,
    "label": "New York, NY",
    "timezone": "America/New_York",
    "locked": False,
}
PIN_PATH = ROOT / "pin.local"
PIN_RE = re.compile(r"^[0-9]{4,8}$")
FAIL_LIMIT = 5
LOCKOUT_S = 60
COOKIE_MAX_AGE = 7 * 24 * 60 * 60
NETWORK_SCAN_CACHE = None
NETWORK_SCAN_AT = 0.0
NETWORK_SCAN_LOCK = threading.Lock()
CALENDAR_LOCK = threading.Lock()
CALENDAR_CACHE = None
CALENDAR_FETCHED_AT = 0.0
CALENDAR_REFRESH_S = 120
HEADLINES_LOCK = threading.Lock()
HEADLINES_CACHE = {"updated": "", "items": []}
HEADLINES_REFRESH_S = 15 * 60
HEADLINES_READ_LIMIT = 300 * 1024
HEADLINES_PRECONFIGURED = (
    ("npr", "NPR", "https://feeds.npr.org/1001/rss.xml", True),
    ("bbc", "BBC", "https://feeds.bbci.co.uk/news/rss.xml", True),
    ("nyt", "NYT", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", True),
    ("gothamist", "Gothamist", "https://gothamist.com/feed", False),
    ("thecity", "The City", "https://www.thecity.nyc/feed", False),
)
HEADLINES_BUILTIN_IDS = {row[0] for row in HEADLINES_PRECONFIGURED}
HEADLINES_CUSTOM_MAX = 8
HEADLINES_NAME_MAX = 32
HEADLINES_FEEDS = tuple((name, url) for _fid, name, url, on in HEADLINES_PRECONFIGURED if on)
HEADLINES_UA = "Slate/1.0 (local TV dashboard)"


def feed_url_allowed(url: str) -> bool:
    if not isinstance(url, str):
        return False
    split = urlsplit(url.strip())
    if split.scheme != "https":
        return False
    if split.username or split.password:
        return False
    host = split.hostname
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host == "localhost":
        return False
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            return False
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return False
    return True


def default_headlines_feed_flags() -> dict:
    return {fid: default for fid, _name, _url, default in HEADLINES_PRECONFIGURED}


def normalize_headlines(raw) -> dict:
    flags = default_headlines_feed_flags()
    custom = []
    if isinstance(raw, dict):
        feed_raw = raw.get("feeds")
        if not isinstance(feed_raw, dict) and isinstance(raw.get("builtin"), list):
            feed_raw = {}
            for row in raw["builtin"]:
                if not isinstance(row, dict):
                    continue
                fid = row.get("id")
                if fid in HEADLINES_BUILTIN_IDS:
                    feed_raw[fid] = row.get("enabled") is True
        if isinstance(feed_raw, dict):
            for fid in HEADLINES_BUILTIN_IDS:
                if fid in feed_raw:
                    flags[fid] = feed_raw[fid] is True
        custom_raw = raw.get("custom")
        if isinstance(custom_raw, list):
            for entry in custom_raw[:HEADLINES_CUSTOM_MAX]:
                if not isinstance(entry, dict):
                    continue
                name_raw = entry.get("name")
                url_raw = entry.get("url")
                if not isinstance(name_raw, str) or not isinstance(url_raw, str):
                    continue
                name = name_raw.strip().replace("\n", " ")[:HEADLINES_NAME_MAX]
                url = url_raw.strip()
                if not name or not feed_url_allowed(url):
                    continue
                custom.append({
                    "name": name,
                    "url": url,
                    "enabled": entry.get("enabled") is not False,
                })
    return {"feeds": flags, "custom": custom}


def headlines_for_client(raw) -> dict:
    cfg = normalize_headlines(raw)
    builtin = []
    for fid, name, url, _default in HEADLINES_PRECONFIGURED:
        builtin.append({
            "id": fid,
            "name": name,
            "url": url,
            "enabled": cfg["feeds"].get(fid, False),
        })
    return {"builtin": builtin, "custom": list(cfg["custom"])}


CALENDAR_PREFETCH_BACK_DAYS = 1
CALENDAR_PREFETCH_FORWARD_DAYS = 45
RADAR_LOCK = threading.Lock()
RADAR_CACHE = {}
MAP_CACHE = {}
OAUTH_LOCK = threading.Lock()
OAUTH_PENDING: dict[str, float] = {}
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
OAUTH_REDIRECT = "http://127.0.0.1:8000/oauth/callback"
TRAFFIC_LOCK = threading.Lock()
TRAFFIC_CACHE = None
TRAFFIC_CACHE_AT = 0.0
TRAFFIC_CACHE_TTL = 180
TRAFFIC_INCIDENT_MAX_AGE = timedelta(hours=36)
TRAFFIC_INCIDENT_MAX_KM = 160.0
TRAFFIC_EVENTS_JSON = "https://511ny.org/api/getevents?format=json"
TRAFFIC_RSS = "https://511nj.org/client/rest/rss/RSSActiveIncidents"
SPEED_LOCK = threading.Lock()
SPEED_CACHE = None
SPEED_CACHE_AT = 0.0
SPEED_CACHE_TTL = 240
SPEED_SEGMENT_LIMIT = 250
# Public OpenConditions emitter (README: GET /observations.geojson and /segments.geojson, bbox-filterable).
OPENCONDITIONS_EMITTER = os.environ.get("SLATE_OPENCONDITIONS_URL", "https://ingest.openconditions.org").rstrip("/")
NY_STATE_BOUNDS = (40.49, 45.12, -79.76, -71.85)
GEORSS_NS = {"g": "http://www.georss.org/georss"}
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
    "hidePointer": False,
    "showCredit": True,
    "tileSize": "auto",
    "hdmiInput": "1",
    "tvAppearance": "sculptural",
    "tvBackdrop": "ambient",
    "tvMotion": "drift",
    "tvIntensity": "balanced",
    "tvAquaPalette": "tide",
    "tvFlurryPalette": "spectrum",
    "remoteEnabled": True,
    "headlines": headlines_for_client({}),
}


def active_headline_feeds() -> list:
    with PUBLISH_LOCK:
        cfg = normalize_headlines(SETTINGS_STATE.get("headlines"))
    order = []
    for fid, name, url, _default in HEADLINES_PRECONFIGURED:
        if cfg["feeds"].get(fid):
            order.append((name, url))
    for entry in cfg["custom"]:
        if entry.get("enabled") is False:
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else ""
        url = entry.get("url") if isinstance(entry.get("url"), str) else ""
        if name and url and feed_url_allowed(url):
            order.append((name, url))
    return order


REMOTE_COOKIE = "slate_remote"
REMOTE_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
REMOTE_PAIR_LOCK = threading.Lock()
REMOTE_PAIRINGS: dict[str, float] = {}
REMOTE_SESSIONS: set[str] = set()
REMOTE_EVENTS_LOCK = threading.Lock()
REMOTE_EVENTS: list[dict] = []
REMOTE_SEQ = 0
REMOTE_TV_PAGE = ""
REMOTE_TV_LAST = 0.0
REMOTE_PHONE_TTL = 300
REMOTE_TV_ONLINE_S = 45
CATALOG_IDS = set()
AMBIENT_PRESETS = set()
NOMINATIM_UA = "SlateDashboard/1.0 (local personal dashboard)"
PLACE_LAST_CALL = 0.0
PLACE_LOCK = threading.Lock()

GALLERY_DIR = ROOT / "gallery.local"
GALLERY_MAX_UPLOAD = 40 * 1024 * 1024
GALLERY_MAX_COUNT = 200
GALLERY_MAX_TOTAL = 500 * 1024 * 1024
GALLERY_MAX_EDGE = 1920
GALLERY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
GALLERY_IMAGE_RE = re.compile(r"^/gallery/([0-9a-f]{32})\.jpg$")
GALLERY_LOCK = threading.Lock()


class GalleryError(Exception):
    pass


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
    if not isinstance(values, list) or not CATALOG_IDS:
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
    return out


def normalize_tile_size(value) -> str:
    return value if isinstance(value, str) and value in {"auto", "large"} else "auto"


def normalize_hdmi_input(value) -> str:
    return value if isinstance(value, str) and value in {"1", "2", "3"} else "1"


def normalize_ambient_preset(value) -> str:
    if isinstance(value, str) and value in AMBIENT_PRESETS:
        return value
    return DEFAULT_AMBIENT_PRESET


ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TODAY_CAP = 8
DEADLINE_CAP = 8


def clip_text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace("\n", " ")[:limit]


def collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def xml_local_tag(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def normalize_headline_title(raw) -> str:
    if not isinstance(raw, str):
        return ""
    text = html.unescape(raw)
    text = collapse_ws(text)
    if len(text) > 120:
        text = text[:119].rstrip() + "…"
    return text


def valid_headline_link(raw) -> str:
    if not isinstance(raw, str):
        return ""
    link = raw.strip()
    if link.startswith("https://") or link.startswith("http://"):
        return link
    return ""


def parse_rss_pubdate(raw) -> tuple[str, float]:
    if not isinstance(raw, str) or not raw.strip():
        return "", 0.0
    try:
        parsed = email.utils.parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError, OverflowError):
        return "", 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().isoformat(timespec="seconds"), parsed.timestamp()


def rss_xml_root(xml_bytes: bytes):
    text = xml_bytes.decode("utf-8", errors="replace")
    if "content:" in text and "xmlns:content" not in text:
        text = re.sub(
            r"<rss\b",
            '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"',
            text,
            count=1,
        )
    if "media:" in text and "xmlns:media" not in text:
        text = re.sub(
            r"<rss\b",
            '<rss xmlns:media="http://search.yahoo.com/mrss/"',
            text,
            count=1,
        )
    return ET.fromstring(text.encode("utf-8"))


def parse_rss_items(xml_bytes: bytes, source: str) -> list:
    """Parse RSS 2.0 channel items. Returns title, source, time, url, and _ts for sorting."""
    try:
        root = rss_xml_root(xml_bytes)
    except ET.ParseError:
        return []
    channel = None
    if xml_local_tag(root.tag) == "rss":
        for child in root:
            if xml_local_tag(child.tag) == "channel":
                channel = child
                break
    elif xml_local_tag(root.tag) == "channel":
        channel = root
    if channel is None:
        return []
    items = []
    for element in channel:
        if xml_local_tag(element.tag) != "item":
            continue
        title_raw = link_raw = pub_raw = ""
        for field in element:
            name = xml_local_tag(field.tag)
            if name == "title":
                title_raw = field.text or ""
            elif name == "link":
                link_raw = (field.text or "").strip()
            elif name == "pubDate":
                pub_raw = field.text or ""
        title = normalize_headline_title(title_raw)
        url = valid_headline_link(link_raw)
        if not title or not url:
            continue
        time_iso, sort_ts = parse_rss_pubdate(pub_raw)
        items.append({
            "title": title,
            "source": source,
            "time": time_iso,
            "url": url,
            "_ts": sort_ts,
        })
    items.sort(key=lambda item: item["_ts"], reverse=True)
    return items


def fetch_rss_bytes(url: str) -> bytes:
    if not feed_url_allowed(url):
        raise ValueError("feed url not allowed")
    request = Request(
        url,
        headers={
            "User-Agent": HEADLINES_UA,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urlopen(request, timeout=8) as response:
        chunks = []
        total = 0
        while total < HEADLINES_READ_LIMIT:
            piece = response.read(min(65536, HEADLINES_READ_LIMIT - total))
            if not piece:
                break
            chunks.append(piece)
            total += len(piece)
        return b"".join(chunks)


def merge_headline_round_robin(per_source: dict, feed_order: list) -> list:
    pools = {label: list(items) for label, items in per_source.items() if items}
    picked = []
    while len(picked) < 4:
        added = False
        for label, _url in feed_order:
            pool = pools.get(label)
            if not pool:
                continue
            picked.append(pool.pop(0))
            added = True
            if len(picked) >= 4:
                break
        if not added:
            break
    picked.sort(key=lambda item: item.get("_ts", 0.0), reverse=True)
    return [
        {
            "title": item["title"],
            "source": item["source"],
            "time": item["time"],
            "url": item["url"],
        }
        for item in picked[:4]
    ]


def refresh_headlines_store() -> None:
    global HEADLINES_CACHE
    feed_order = active_headline_feeds()
    if not feed_order:
        with HEADLINES_LOCK:
            HEADLINES_CACHE = {"updated": local_iso_now(), "items": []}
        return
    per_source = {}
    any_ok = False
    for label, url in feed_order:
        try:
            raw = fetch_rss_bytes(url)
            parsed = parse_rss_items(raw, label)
            if parsed:
                per_source[label] = parsed[:5]
                any_ok = True
        except (OSError, HTTPError, ValueError, ET.ParseError):
            continue
    if not any_ok:
        return
    payload = {
        "updated": local_iso_now(),
        "items": merge_headline_round_robin(per_source, feed_order),
    }
    with HEADLINES_LOCK:
        HEADLINES_CACHE = payload


def headlines_payload() -> dict:
    with HEADLINES_LOCK:
        store = HEADLINES_CACHE if isinstance(HEADLINES_CACHE, dict) else {"updated": "", "items": []}
        items = store.get("items") if isinstance(store.get("items"), list) else []
        updated = store.get("updated") if isinstance(store.get("updated"), str) else ""
    clean = []
    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        source = item.get("source") if isinstance(item.get("source"), str) else ""
        url = item.get("url") if isinstance(item.get("url"), str) else ""
        time_val = item.get("time") if isinstance(item.get("time"), str) else ""
        if not title or not valid_headline_link(url):
            continue
        clean.append({"title": title, "source": source, "time": time_val, "url": url})
    return {"updated": updated, "items": clean}


def headlines_refresh_loop(stop_event: threading.Event) -> None:
    refresh_headlines_store()
    while not stop_event.is_set():
        if stop_event.wait(HEADLINES_REFRESH_S):
            break
        refresh_headlines_store()


def valid_iso_date(value) -> bool:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value.strip()):
        return False
    year, month, day = (int(part) for part in value.strip().split("-"))
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


def local_iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_schedule(obj: dict) -> dict:
    today = []
    raw_today = obj.get("today") if isinstance(obj.get("today"), list) else []
    for item in raw_today:
        if not isinstance(item, dict):
            continue
        when = clip_text(item.get("time"), 16)
        title = clip_text(item.get("title"), 120)
        if not when and not title:
            continue
        today.append({"time": when, "title": title})
        if len(today) >= TODAY_CAP:
            break
    deadlines = []
    raw_deadlines = obj.get("deadlines") if isinstance(obj.get("deadlines"), list) else []
    for item in raw_deadlines:
        if not isinstance(item, dict):
            continue
        title = clip_text(item.get("title"), 120)
        due = item.get("due").strip() if isinstance(item.get("due"), str) else ""
        if not title or not valid_iso_date(due):
            continue
        deadlines.append({"title": title, "due": due})
        if len(deadlines) >= DEADLINE_CAP:
            break
    money_raw = obj.get("money") if isinstance(obj.get("money"), dict) else {}
    note = clip_text(money_raw.get("note"), 200)
    return {
        "updated": local_iso_now(),
        "today": today,
        "deadlines": deadlines,
        "money": {"note": note},
    }


def write_schedule_local(payload: dict) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    LOCAL.write_text(text, encoding="utf-8")
    protect_local_file(LOCAL)


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
    local = read_settings_local()
    payload = dict(data)
    if "calendarId" in data:
        calendar_id = data.get("calendarId")
        if isinstance(calendar_id, str) and calendar_id.strip():
            payload["calendarId"] = calendar_id.strip()
        else:
            payload.pop("calendarId", None)
    else:
        calendar_id = local.get("calendarId")
        if isinstance(calendar_id, str) and calendar_id.strip():
            payload["calendarId"] = calendar_id.strip()
        else:
            payload.pop("calendarId", None)
    if "headlines" in payload:
        payload["headlines"] = normalize_headlines(payload["headlines"])
    text = json.dumps(payload, indent=2) + "\n"
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
        hide_pointer = local.get("hidePointer") is True
        show_credit = local.get("showCredit") is not False
        tile_size = normalize_tile_size(local.get("tileSize"))
        hdmi_input = normalize_hdmi_input(local.get("hdmiInput"))
        remote_on = local.get("remoteEnabled")
        if remote_on is False:
            remote_flag = False
        else:
            remote_flag = True
        SETTINGS_STATE = {
            "homeApps": home,
            "ambientPreset": preset,
            "location": location,
            "hidePointer": hide_pointer,
            "showCredit": show_credit,
            "tileSize": tile_size,
            "hdmiInput": hdmi_input,
            "remoteEnabled": remote_flag,
            "headlines": headlines_for_client(local.get("headlines")),
            **normalize_tv_appearance(local),
        }
        publish_apps(home)
        atv_remote.get_service(remote_enabled).set_enabled(remote_flag)


def normalize_tv_appearance(source: dict) -> dict:
    appearance = source.get("tvAppearance")
    if appearance == "classic":
        appearance = "sculptural"
    if appearance == "scenic":
        appearance = "aqua"
    if appearance not in ("sculptural", "aqua", "flurry"):
        appearance = "sculptural"
    choices = {
        "tvBackdrop": ("ambient", "landscape", "aqua", "flurry", "orbit"),
        "tvMotion": ("drift", "still", "reactive"),
        "tvIntensity": ("balanced", "soft", "vivid"),
        "tvAquaPalette": ("tide", "glacier", "lagoon", "dusk", "moss", "ember"),
        "tvFlurryPalette": ("spectrum", "ice", "aurora", "ember", "lagoon", "bloom"),
    }
    normalized = {key: source.get(key) if source.get(key) in values else values[0]
                  for key, values in choices.items()}
    normalized["tvAppearance"] = appearance
    if appearance in ("sculptural", "aqua", "flurry"):
        normalized["tvBackdrop"] = appearance
    return normalized


def keychain_value(account: str) -> str:
    """Read a Slate secret from macOS Keychain without putting it in repo files."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Slate Calendar", "-a", account, "-w"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def keychain_set(account: str, secret: str) -> bool:
    if not secret:
        return False
    subprocess.run(
        ["security", "delete-generic-password", "-s", "Slate Calendar", "-a", account],
        capture_output=True, timeout=3, check=False,
    )
    try:
        result = subprocess.run(
            ["security", "add-generic-password", "-s", "Slate Calendar", "-a", account, "-w", secret, "-U"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def keychain_delete(account: str) -> None:
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", "Slate Calendar", "-a", account],
            capture_output=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def request_is_localhost(handler) -> bool:
    host = handler.headers.get("Host", "").split(":")[0].lower()
    if host not in {"127.0.0.1", "localhost", "[::1]"}:
        return False
    ip = handler.client_address[0]
    return ip in {"127.0.0.1", "::1"}


def calendar_credentials() -> tuple[str, str, str, str]:
    settings = read_settings_local()
    calendar_id = settings.get("calendarId") if isinstance(settings.get("calendarId"), str) else ""
    return (
        calendar_id.strip(),
        keychain_value("client-id"),
        keychain_value("client-secret"),
        keychain_value("refresh-token"),
    )


def google_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    body = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = Request(
        "https://oauth2.googleapis.com/token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("access_token", "") if isinstance(payload, dict) else ""


def parse_google_event(item: dict) -> dict | None:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    end = item.get("end") if isinstance(item.get("end"), dict) else {}
    all_day = isinstance(start.get("date"), str)
    start_value = start.get("date") if all_day else start.get("dateTime")
    end_value = end.get("date") if all_day else end.get("dateTime")
    if not isinstance(start_value, str) or not start_value:
        return None
    return {
        "id": clip_text(item.get("id"), 256),
        "title": clip_text(item.get("summary"), 160) or "Untitled event",
        "start": start_value,
        "end": end_value if isinstance(end_value, str) else "",
        "allDay": all_day,
        "location": clip_text(item.get("location"), 180),
        "notes": clip_text(item.get("description"), 600),
        "status": clip_text(item.get("status"), 24),
    }


def write_calendar_cache(payload: dict) -> None:
    try:
        CALENDAR_CACHE_LOCAL.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        protect_local_file(CALENDAR_CACHE_LOCAL)
    except OSError:
        pass


def read_calendar_cache() -> dict | None:
    try:
        payload = json.loads(CALENDAR_CACHE_LOCAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def fetch_google_calendar(start: str, end: str) -> dict:
    calendar_id, client_id, client_secret, refresh_token = calendar_credentials()
    if not all((calendar_id, client_id, client_secret, refresh_token)):
        return {"configured": False, "stale": False, "syncedAt": "", "events": []}
    token = google_access_token(client_id, client_secret, refresh_token)
    if not token:
        raise OSError("Google did not return an access token")
    params = urlencode({
        "timeMin": start,
        "timeMax": end,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "2500",
        "timeZone": SETTINGS_STATE.get("location", {}).get("timezone", "America/New_York"),
    })
    url = (
        "https://www.googleapis.com/calendar/v3/calendars/"
        + quote(calendar_id, safe="")
        + "/events?"
        + params
    )
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8"))
    events = []
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict) or item.get("status") == "cancelled":
            continue
        event = parse_google_event(item)
        if event:
            events.append(event)
    return {"configured": True, "stale": False, "syncedAt": local_iso_now(), "events": events}


def parse_iso_datetime(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def calendar_prefetch_bounds(now: datetime | None = None) -> tuple[str, str]:
    anchor = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    start = anchor - timedelta(days=CALENDAR_PREFETCH_BACK_DAYS)
    end = anchor + timedelta(days=CALENDAR_PREFETCH_FORWARD_DAYS)
    return start.isoformat(), end.isoformat()


def event_window(event: dict) -> tuple[datetime | None, datetime | None]:
    if not isinstance(event, dict):
        return None, None
    if event.get("allDay") is True:
        start = parse_iso_datetime(f"{event.get('start', '')}T00:00:00")
        end_raw = event.get("end") or event.get("start")
        end = parse_iso_datetime(f"{end_raw}T00:00:00") if isinstance(end_raw, str) else None
        if start and end and end > start:
            end = end - timedelta(seconds=1)
        elif start and not end:
            end = start + timedelta(hours=23, minutes=59, seconds=59)
        return start, end
    start = parse_iso_datetime(event.get("start", ""))
    end = parse_iso_datetime(event.get("end") or event.get("start", ""))
    return start, end


def events_in_range(events: list, start_iso: str, end_iso: str) -> list:
    start_dt = parse_iso_datetime(start_iso)
    end_dt = parse_iso_datetime(end_iso)
    if start_dt is None or end_dt is None:
        return []
    filtered = []
    for event in events:
        if not isinstance(event, dict):
            continue
        ev_start, ev_end = event_window(event)
        if ev_start is None:
            continue
        if ev_end is None:
            ev_end = ev_start
        if ev_start < end_dt and ev_end >= start_dt:
            filtered.append(event)
    filtered.sort(key=lambda item: item.get("start", ""))
    return filtered


def merge_calendar_events(existing: list, incoming: list) -> list:
    merged = {}
    for event in existing + incoming:
        if isinstance(event, dict) and isinstance(event.get("id"), str):
            merged[event["id"]] = event
    out = list(merged.values())
    out.sort(key=lambda item: item.get("start", ""))
    return out


def refresh_calendar_store(force: bool = False) -> None:
    global CALENDAR_CACHE, CALENDAR_FETCHED_AT
    now = time.monotonic()
    prefetch_start, prefetch_end = calendar_prefetch_bounds()
    with CALENDAR_LOCK:
        if (
            not force
            and isinstance(CALENDAR_CACHE, dict)
            and CALENDAR_CACHE.get("windowStart") == prefetch_start
            and CALENDAR_CACHE.get("windowEnd") == prefetch_end
            and now - CALENDAR_FETCHED_AT < CALENDAR_REFRESH_S
        ):
            return
    try:
        payload = fetch_google_calendar(prefetch_start, prefetch_end)
        payload["windowStart"] = prefetch_start
        payload["windowEnd"] = prefetch_end
        with CALENDAR_LOCK:
            CALENDAR_CACHE = payload
            CALENDAR_FETCHED_AT = time.monotonic()
        if payload.get("configured"):
            write_calendar_cache(payload)
    except (OSError, ValueError, json.JSONDecodeError, HTTPError):
        with CALENDAR_LOCK:
            fallback = CALENDAR_CACHE if isinstance(CALENDAR_CACHE, dict) else read_calendar_cache()
            if isinstance(fallback, dict):
                stale = dict(fallback)
                stale["stale"] = True
                CALENDAR_CACHE = stale


def calendar_payload(start: str, end: str) -> dict:
    refresh_calendar_store()
    with CALENDAR_LOCK:
        store = dict(CALENDAR_CACHE) if isinstance(CALENDAR_CACHE, dict) else {}
    if not store:
        disk = read_calendar_cache()
        store = dict(disk) if isinstance(disk, dict) else {}
    if not store.get("configured"):
        return {"configured": False, "stale": False, "syncedAt": "", "events": []}

    req_start = parse_iso_datetime(start)
    req_end = parse_iso_datetime(end)
    win_start = parse_iso_datetime(store.get("windowStart", ""))
    win_end = parse_iso_datetime(store.get("windowEnd", ""))
    stale = store.get("stale") is True
    synced_at = store.get("syncedAt") if isinstance(store.get("syncedAt"), str) else ""
    events = events_in_range(store.get("events") or [], start, end)

    needs_fetch = (
        req_start is not None
        and req_end is not None
        and win_start is not None
        and win_end is not None
        and (req_start < win_start or req_end > win_end)
    )
    if needs_fetch:
        try:
            fetched = fetch_google_calendar(start, end)
            events = fetched.get("events") or []
            stale = False
            synced_at = fetched.get("syncedAt") if isinstance(fetched.get("syncedAt"), str) else synced_at
            with CALENDAR_LOCK:
                if isinstance(CALENDAR_CACHE, dict):
                    merged = merge_calendar_events(CALENDAR_CACHE.get("events") or [], events)
                    CALENDAR_CACHE["events"] = merged
                    CALENDAR_CACHE["stale"] = False
                    CALENDAR_CACHE["syncedAt"] = synced_at
                    write_calendar_cache(CALENDAR_CACHE)
        except (OSError, ValueError, json.JSONDecodeError, HTTPError):
            stale = True
            if req_start and req_end and win_start and win_end:
                if req_end <= win_start or req_start >= win_end:
                    events = []
                else:
                    events = events_in_range(store.get("events") or [], start, end)

    return {
        "configured": True,
        "stale": stale,
        "syncedAt": synced_at,
        "events": events,
    }


def guest_calendar(payload: dict) -> dict:
    body = {key: payload.get(key) for key in ("configured", "stale", "syncedAt")}
    body["events"] = []
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        body["events"].append({
            "id": event.get("id", ""), "title": "Busy", "start": event.get("start", ""),
            "end": event.get("end", ""), "allDay": event.get("allDay") is True,
            "location": "", "notes": "", "status": event.get("status", ""),
        })
    return body


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


def slate_settings_place() -> dict | None:
    """Same location object published on GET /settings.json (after merge with defaults)."""
    with PUBLISH_LOCK:
        publish_settings()
        loc = normalize_location(SETTINGS_STATE.get("location"))
    lat = loc.get("lat")
    lon = loc.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return loc


def in_new_york_state(lat: float, lon: float) -> bool:
    min_lat, max_lat, min_lon, max_lon = NY_STATE_BOUNDS
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def fetch_http_text(url: str, accept: str = "*/*", timeout: int = 15) -> tuple[str, str]:
    req = Request(url, headers={"User-Agent": NOMINATIM_UA, "Accept": accept})
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        content_type = resp.headers.get_content_type()
    return body, content_type


def parse_511ny_events(body: str, content_type: str) -> list | None:
    if "json" not in content_type and not body.lstrip().startswith(("{", "[")):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("events", "Events", "features"):
            raw = data.get(key)
            if isinstance(raw, list):
                return raw
    return None


def normalize_511ny_event(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    lat = raw.get("Latitude", raw.get("latitude", raw.get("lat")))
    lon = raw.get("Longitude", raw.get("longitude", raw.get("lon")))
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        geom = raw.get("geometry")
        if isinstance(geom, dict) and geom.get("type") == "Point":
            coords = geom.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    road = clip_text(
        raw.get("RoadwayName")
        or raw.get("roadway_name")
        or raw.get("facility_name")
        or raw.get("title")
        or "Incident",
        120,
    )
    desc = clip_text(
        raw.get("Description")
        or raw.get("description")
        or raw.get("event_description")
        or raw.get("Summary")
        or "",
        220,
    )
    when = raw.get("LastUpdated") or raw.get("lastUpdated") or raw.get("create_time") or raw.get("StartDate")
    if not isinstance(when, str):
        when = ""
    return {"road": road, "description": desc, "time": when, "lat": float(lat), "lon": float(lon)}


def ny_incident_from_rss(title: str, description: str) -> bool:
    blob = f"{title} {description}".upper()
    markers = (
        "NYSDOT",
        "NYSTA",
        "NYS THRUWAY",
        "NYS DOT",
        "MTA ",
        "NYC DOT",
        "(NEW YORK)",
        "NEW YORK COUNTY",
        "KINGS COUNTY",
        "QUEENS COUNTY",
        "BRONX",
        "RICHMOND COUNTY",
        "WESTCHESTER",
        "NASSAU COUNTY",
        "SUFFOLK COUNTY",
    )
    return any(marker in blob for marker in markers)


def parse_transcom_rss(body: str) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    rows = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        lat = lon = None
        point = item.find("g:point", GEORSS_NS)
        if point is not None and point.text:
            parts = point.text.strip().split()
            if len(parts) >= 2:
                try:
                    lat = float(parts[0])
                    lon = float(parts[1])
                except ValueError:
                    lat = lon = None
        in_ny = ny_incident_from_rss(title, description)
        if isinstance(lat, float) and isinstance(lon, float) and in_new_york_state(lat, lon):
            in_ny = True
        if not in_ny:
            continue
        road = title.split(":", 1)[0].strip() if title else "Incident"
        desc = description
        for prefix in ("NYSDOT - ", "NYSTA - ", "NYS DOT - ", "ConnDOT: "):
            if desc.startswith(prefix):
                desc = desc[len(prefix) :].strip()
                break
        when = pub
        if pub:
            try:
                when = parsedate_to_datetime(pub).isoformat()
            except (TypeError, ValueError, IndexError):
                when = pub
        row = {
            "road": clip_text(road, 120),
            "description": clip_text(desc, 220),
            "time": when,
        }
        if isinstance(lat, float) and isinstance(lon, float):
            row["lat"] = lat
            row["lon"] = lon
        rows.append(row)
    return rows


def load_ny_incidents() -> tuple[list[dict], str]:
    """Return incident rows and feed id ('511ny-json', '511ny-rss', or '')."""
    try:
        body, content_type = fetch_http_text(TRAFFIC_EVENTS_JSON, accept="application/json")
        events = parse_511ny_events(body, content_type)
        if events is not None:
            rows = []
            for raw in events:
                row = normalize_511ny_event(raw if isinstance(raw, dict) else {})
                if row:
                    rows.append(row)
            if rows:
                return rows, "511ny-json"
    except (OSError, HTTPError, ValueError):
        pass
    try:
        body, _ = fetch_http_text(TRAFFIC_RSS, accept="application/rss+xml, application/xml, text/xml")
        rows = parse_transcom_rss(body)
        if rows:
            return rows, "511nj-transcom-rss"
    except (OSError, HTTPError, ValueError):
        pass
    return [], ""


def incident_datetime(when: str) -> datetime | None:
    if not isinstance(when, str) or not when.strip():
        return None
    parsed = parse_iso_datetime(when)
    if parsed is not None:
        return parsed.astimezone(timezone.utc)
    try:
        return parsedate_to_datetime(when).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def traffic_incidents_for(lat: float, lon: float) -> tuple[list[dict], bool, str]:
    if not in_new_york_state(lat, lon):
        return [], False, ""
    now = time.monotonic()
    global TRAFFIC_CACHE, TRAFFIC_CACHE_AT
    with TRAFFIC_LOCK:
        if TRAFFIC_CACHE and now - TRAFFIC_CACHE_AT < TRAFFIC_CACHE_TTL:
            cached_rows, feed = TRAFFIC_CACHE
        else:
            cached_rows, feed = load_ny_incidents()
            TRAFFIC_CACHE = (cached_rows, feed)
            TRAFFIC_CACHE_AT = now
    if not cached_rows:
        return [], bool(feed), feed
    cutoff = datetime.now(timezone.utc) - TRAFFIC_INCIDENT_MAX_AGE
    ranked = []
    for row in cached_rows:
        item = dict(row)
        when = incident_datetime(item.get("time", ""))
        if when is None or when < cutoff:
            continue
        if not isinstance(item.get("lat"), float) or not isinstance(item.get("lon"), float):
            continue
        dist = haversine_km(lat, lon, item["lat"], item["lon"])
        if dist > TRAFFIC_INCIDENT_MAX_KM:
            continue
        item["distanceKm"] = round(dist, 1)
        item["_whenTs"] = when.timestamp()
        ranked.append(item)
    ranked.sort(key=lambda row: (-row.get("_whenTs", 0.0), row.get("distanceKm", 9999.0)))
    picked = []
    for row in ranked:
        out = {k: v for k, v in row.items() if k not in ("distanceKm", "_whenTs")}
        picked.append(out)
        if len(picked) >= 8:
            break
    return picked, True, feed


def traffic_speed_bbox(lat: float, lon: float, radius_km: float = 32.0) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.0
    cos_lat = max(0.2, abs(math.cos(math.radians(lat))))
    dlon = radius_km / (111.0 * cos_lat)
    west = lon - dlon
    east = lon + dlon
    south = lat - dlat
    north = lat + dlat
    return west, south, east, north


def congestion_level(ratio: float) -> str:
    if ratio >= 0.8:
        return "green"
    if ratio >= 0.5:
        return "yellow"
    return "red"


def speed_ratio_from_properties(props: dict) -> float | None:
    ratio = props.get("speed_ratio")
    if isinstance(ratio, (int, float)) and ratio > 0:
        return float(ratio)
    current = props.get("current_kph", props.get("speed", props.get("result")))
    free_flow = props.get(
        "free_flow_kph",
        props.get("freeFlow", props.get("referenceSpeed", props.get("free_flow"))),
    )
    qualifiers = props.get("qualifiers")
    if isinstance(qualifiers, dict):
        free_flow = free_flow or qualifiers.get("freeFlow") or qualifiers.get("free_flow")
    ref = props.get("reference")
    if isinstance(ref, dict):
        free_flow = free_flow or ref.get("freeFlow") or ref.get("speed")
    if isinstance(current, str):
        try:
            current = float(current)
        except ValueError:
            current = None
    if isinstance(free_flow, str):
        try:
            free_flow = float(free_flow)
        except ValueError:
            free_flow = None
    if isinstance(current, (int, float)) and isinstance(free_flow, (int, float)) and free_flow > 0:
        return float(current) / float(free_flow)
    return None


def line_midpoint(coords: list) -> tuple[float, float] | None:
    if not coords:
        return None
    if len(coords) == 1 and isinstance(coords[0], (list, tuple)) and len(coords[0]) >= 2:
        return float(coords[0][1]), float(coords[0][0])
    mid = coords[len(coords) // 2]
    if isinstance(mid, (list, tuple)) and len(mid) >= 2:
        return float(mid[1]), float(mid[0])
    return None


def speed_mark_from_feature(feature: dict) -> dict | None:
    if not isinstance(feature, dict):
        return None
    geom = feature.get("geometry")
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    if isinstance(props.get("properties"), dict):
        props = {**props, **props["properties"]}
    ratio = speed_ratio_from_properties(props)
    if ratio is None:
        ratio = speed_ratio_from_properties(feature)
    if ratio is None:
        return None
    lat = lon = None
    if isinstance(geom, dict):
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
        elif gtype == "LineString" and isinstance(coords, list):
            mid = line_midpoint(coords)
            if mid:
                lat, lon = mid
        elif gtype == "MultiLineString" and isinstance(coords, list) and coords:
            first = coords[0]
            if isinstance(first, list):
                mid = line_midpoint(first)
                if mid:
                    lat, lon = mid
    loc = props.get("location")
    if (lat is None or lon is None) and isinstance(loc, dict):
        loc_geom = loc.get("geometry")
        if isinstance(loc_geom, dict):
            return speed_mark_from_feature({"geometry": loc_geom, "properties": props})
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon, "level": congestion_level(ratio)}


def parse_openconditions_speed_body(body: str) -> list[dict]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    marks: list[dict] = []
    if isinstance(data, dict) and isinstance(data.get("features"), list):
        for feature in data["features"]:
            mark = speed_mark_from_feature(feature if isinstance(feature, dict) else {})
            if mark:
                marks.append(mark)
        return marks
    records = None
    if isinstance(data, dict):
        records = data.get("records")
        if records is None and isinstance(data.get("observations"), list):
            records = data["observations"]
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            mark = speed_mark_from_feature({"geometry": None, "properties": record})
            if not mark and isinstance(record.get("location"), dict):
                mark = speed_mark_from_feature(
                    {
                        "geometry": record["location"].get("geometry"),
                        "properties": record,
                    }
                )
            if mark:
                marks.append(mark)
    return marks


NYC_SPEEDS_URL = (
    "https://data.cityofnewyork.us/resource/i4gi-tjb9.json"
    "?$select=speed,status,data_as_of,encoded_poly_line&$where=status=%270%27&$limit=5000"
)
NYC_SPEED_MAX_AGE = timedelta(hours=8)


def in_new_york_city(lat: float, lon: float) -> bool:
    return 40.49 <= lat <= 40.92 and -74.26 <= lon <= -73.70


def nyc_speed_level(mph: float) -> str:
    if mph >= 40:
        return "green"
    if mph >= 20:
        return "yellow"
    return "red"


def decode_polyline(raw: str) -> list[list[float]]:
    """Google encoded polyline. A cut-off string keeps only complete points."""
    if not isinstance(raw, str) or not raw:
        return []
    index = 0
    lat = 0
    lon = 0
    points: list[list[float]] = []
    length = len(raw)
    while index < length:
        for axis in (0, 1):
            shift = 0
            result = 0
            while True:
                if index >= length:
                    return points
                byte = ord(raw[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if axis == 0:
                lat += delta
            else:
                lon += delta
        points.append([round(lat / 1e5, 5), round(lon / 1e5, 5)])
    return points


def nyc_line_points(raw: str) -> list[list[float]]:
    """Stop a road before a broken point. The plain point list is clipped at 255 characters."""
    kept: list[list[float]] = []
    for lat, lon in decode_polyline(raw):
        if not (40.40 <= lat <= 41.05 and -74.40 <= lon <= -73.50):
            break
        if kept and (abs(lat - kept[-1][0]) > 0.02 or abs(lon - kept[-1][1]) > 0.03):
            break
        kept.append([lat, lon])
    return kept if len(kept) >= 2 else []


def nyc_speed_time(raw: str) -> datetime | None:
    """NYC open data stamps are local time without a zone."""
    if not raw:
        return None
    text = raw.strip().replace("Z", "")
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(timezone.utc)


def fetch_nyc_speed_segments(lat: float, lon: float) -> tuple[list[dict], bool, bool]:
    """NYC DOT live speeds. No key. Roads are green, yellow, or red by measured mph."""
    if not in_new_york_city(lat, lon):
        return [], False, False
    west, south, east, north = traffic_speed_bbox(lat, lon, radius_km=18)
    try:
        body, content_type = fetch_http_text(NYC_SPEEDS_URL, accept="application/json", timeout=20)
    except (OSError, HTTPError, ValueError):
        return [], False, False
    if "json" not in content_type and not body.lstrip().startswith("["):
        return [], False, False
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return [], False, False
    if not isinstance(rows, list) or not rows:
        return [], True, False
    newest = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = nyc_speed_time(str(row.get("data_as_of") or ""))
        if when is not None and (newest is None or when > newest):
            newest = when
    if newest is None or newest < datetime.now(timezone.utc) - NYC_SPEED_MAX_AGE:
        return [], True, False
    segments = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("status")) != "0":
            continue
        try:
            mph = float(row.get("speed"))
        except (TypeError, ValueError):
            continue
        if mph <= 1:
            continue
        points = nyc_line_points(str(row.get("encoded_poly_line") or ""))
        if len(points) < 2:
            continue
        mid_lat, mid_lon = points[len(points) // 2]
        if not (south <= mid_lat <= north and west <= mid_lon <= east):
            continue
        segments.append({"level": nyc_speed_level(mph), "points": points})
        if len(segments) >= SPEED_SEGMENT_LIMIT:
            break
    return segments, True, bool(segments)


def traffic_speed_segments_for(lat: float, lon: float) -> tuple[list[dict], bool, bool]:
    now = time.monotonic()
    key = (round(lat, 2), round(lon, 2))
    global SPEED_CACHE, SPEED_CACHE_AT
    with SPEED_LOCK:
        if SPEED_CACHE and now - SPEED_CACHE_AT < SPEED_CACHE_TTL:
            cached_key, segments, feed_ok, speeds_ok = SPEED_CACHE
            if cached_key == key:
                return segments, feed_ok, speeds_ok
    segments, feed_ok, speeds_ok = fetch_nyc_speed_segments(lat, lon)
    with SPEED_LOCK:
        SPEED_CACHE = (key, segments, feed_ok, speeds_ok)
        SPEED_CACHE_AT = now
    return segments, feed_ok, speeds_ok


def parse_traffic_center(params: dict) -> tuple[float, float] | None:
    raw_lat = params.get("lat", [""])[0] if params else ""
    raw_lon = params.get("lon", [""])[0] if params else ""
    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def traffic_payload(center: tuple[float, float] | None = None) -> dict:
    updated = datetime.now(timezone.utc).isoformat()
    settings_place = slate_settings_place()
    if center is not None:
        lat, lon = center
        label = ""
        if settings_place and isinstance(settings_place.get("label"), str):
            slat = settings_place.get("lat")
            slon = settings_place.get("lon")
            if isinstance(slat, (int, float)) and isinstance(slon, (int, float)):
                if haversine_km(lat, lon, float(slat), float(slon)) < 1.0:
                    label = settings_place.get("label") or ""
        tz = (settings_place or {}).get("timezone") or "America/New_York"
        place = {"lat": lat, "lon": lon, "label": label, "timezone": tz}
    elif settings_place is None:
        return {
            "hasPlace": False,
            "incidentsAvailable": False,
            "incidents": [],
            "speedsAvailable": False,
            "segments": [],
            "updated": updated,
        }
    else:
        place = settings_place
    lat, lon = float(place["lat"]), float(place["lon"])
    incidents, available, feed = traffic_incidents_for(lat, lon)
    segments, _speed_feed_ok, speeds_ok = traffic_speed_segments_for(lat, lon)
    body = {
        "hasPlace": True,
        "place": {
            "lat": lat,
            "lon": lon,
            "label": place.get("label") or "",
            "timezone": place.get("timezone") or "America/New_York",
        },
        "incidentsAvailable": available,
        "incidents": incidents,
        "speedsAvailable": speeds_ok,
        "segments": segments,
        "updated": updated,
    }
    if feed:
        body["feed"] = feed
    return body


def pin_matches(offered) -> bool:
    """Constant-time check. The length of a wrong PIN does not skip the compare."""
    if not pin_configured():
        return False
    raw = offered if isinstance(offered, str) else ""
    left = hashlib.sha256(raw.encode("utf-8")).digest()
    right = hashlib.sha256(EXPECTED_PIN.encode("utf-8")).digest()
    same = hmac.compare_digest(left, right)
    return bool(PIN_RE.fullmatch(raw)) and same


def _gallery_path_inside(path: Path) -> bool:
    try:
        path.resolve().relative_to(GALLERY_DIR.resolve())
    except (OSError, ValueError):
        return False
    return True


def gallery_ensure_dir() -> None:
    GALLERY_DIR.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(GALLERY_DIR, 0o700)
    except OSError:
        pass


def gallery_temp_path() -> Path:
    gallery_ensure_dir()
    while True:
        name = f".{secrets.token_hex(16)}.tmp"
        path = GALLERY_DIR / name
        if not path.exists():
            return path


def gallery_delete_temps(*paths: Path) -> None:
    for path in paths:
        if not path:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def sniff_media(data: bytes) -> str | None:
    if len(data) < 4:
        return None
    head = data[:512].lstrip()
    lower = head.lower()
    if lower.startswith(b"<!doctype") or lower.startswith(b"<html") or lower.startswith(b"<script"):
        return "html"
    if b"<svg" in lower[:256]:
        return "svg"
    if b"<script" in lower[:256]:
        return "script"
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and len(data) >= 12:
        kind = data[8:12]
        if kind == b"WEBP":
            return "webp"
        if kind == b"AVI ":
            return "video"
    if data[4:8] == b"ftyp" and len(data) >= 12:
        brand = data[8:12]
        if brand == b"avif":
            return "avif"
        if brand in (b"heic", b"heif", b"mif1"):
            return "heif"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:4] == b"%PDF":
        return "pdf"
    return None


def sniff_accepts_still(data: bytes) -> bool:
    kind = sniff_media(data)
    return kind in {"jpeg", "png", "gif", "webp", "heif"}


def orientation_sips_flags(exif_value: int | None) -> list[str]:
    if exif_value is None or exif_value == 1 or exif_value < 2 or exif_value > 8:
        return []
    table = {
        2: ["-f", "horizontal"],
        3: ["-r", "180"],
        4: ["-f", "vertical"],
        5: ["-f", "horizontal", "-r", "90"],
        6: ["-r", "90"],
        7: ["-f", "horizontal", "-r", "270"],
        8: ["-r", "270"],
    }
    return list(table.get(exif_value, []))


def irot_sips_flags(quarters: int) -> list[str]:
    table = {1: ["-r", "270"], 2: ["-r", "180"], 3: ["-r", "90"]}
    return list(table.get(quarters, []))


def _tiff_short_at(value_field: int, little: bool) -> int:
    if little:
        return value_field & 0xFFFF
    return (value_field >> 16) & 0xFFFF


def _exif_orientation_from_tiff(tiff: bytes) -> int | None:
    if len(tiff) < 8:
        return None
    if tiff[:2] == b"II":
        little = True
    elif tiff[:2] == b"MM":
        little = False
    else:
        return None
    u16 = lambda off: int.from_bytes(tiff[off:off + 2], "little" if little else "big")
    u32 = lambda off: int.from_bytes(tiff[off:off + 4], "little" if little else "big")
    if u16(2) != 0x002A:
        return None
    ifd0 = u32(4)
    if ifd0 + 2 > len(tiff):
        return None
    count = u16(ifd0)
    pos = ifd0 + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag = u16(pos)
        field_type = u16(pos + 2)
        count_val = u32(pos + 4)
        value_field = u32(pos + 8)
        if tag == 0x0112 and field_type == 3 and count_val == 1:
            return _tiff_short_at(value_field, little)
        pos += 12
    return None


def jpeg_exif_orientation(data: bytes) -> int | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0x01):
            continue
        if marker == 0xD9:
            break
        if i + 2 > len(data):
            break
        seglen = int.from_bytes(data[i:i + 2], "big")
        if seglen < 2 or i + seglen > len(data):
            break
        if marker == 0xE1:
            payload = data[i + 2:i + seglen]
            if payload.startswith(b"Exif\x00\x00"):
                return _exif_orientation_from_tiff(payload[6:])
        i += seglen
    return None


def webp_exif_orientation(data: bytes) -> int | None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    pos = 12
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        chunk = data[pos:pos + 8]
        if chunk[:4] == b"EXIF":
            payload = data[pos + 8:pos + 8 + size]
            if payload.startswith(b"Exif\x00\x00"):
                return _exif_orientation_from_tiff(payload[6:])
            return _exif_orientation_from_tiff(payload)
        pos += 8 + size + (size & 1)
    return None


def _heif_box_iter(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        if size == 0:
            size = end - pos
        elif size == 1 and pos + 16 <= end:
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            header = 16
        else:
            header = 8
        if size < header or pos + size > end:
            break
        yield kind, pos + header, pos + size, size
        pos += size


def heif_exif_orientation(data: bytes) -> int | None:
    idx = 0
    while True:
        idx = data.find(b"Exif\x00\x00", idx)
        if idx < 0:
            return None
        value = _exif_orientation_from_tiff(data[idx + 6:])
        if value is not None:
            return value
        idx += 6


def heif_irot_quarters(data: bytes) -> int | None:
    if sniff_media(data) != "heif":
        return None
    for kind, start, end, _size in _heif_box_iter(data, 0, len(data)):
        if kind != b"meta":
            continue
        for sub, s, e, _ in _heif_box_iter(data, start, end):
            if sub != b"iprp":
                continue
            for sub2, s2, e2, _ in _heif_box_iter(data, s, e):
                if sub2 != b"ipco":
                    continue
                for sub3, s3, e3, _ in _heif_box_iter(data, s2, e2):
                    if sub3 == b"irot" and e3 - s3 >= 2:
                        return data[s3 + 1] & 3
    return None


def media_orientation_flags(data: bytes, kind: str) -> list[str]:
    if kind in {"png", "gif"}:
        return []
    exif = None
    if kind == "jpeg":
        exif = jpeg_exif_orientation(data)
    elif kind == "webp":
        exif = webp_exif_orientation(data)
    elif kind == "heif":
        exif = heif_exif_orientation(data)
    if exif is not None and 2 <= exif <= 8:
        return orientation_sips_flags(exif)
    if kind == "heif":
        irot = heif_irot_quarters(data)
        if irot:
            return irot_sips_flags(irot)
    return []


def sips_measure(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GalleryError("measure")
    width = height = 0
    for line in proc.stdout.splitlines():
        if "pixelWidth:" in line:
            width = int(line.rsplit(":", 1)[-1].strip())
        if "pixelHeight:" in line:
            height = int(line.rsplit(":", 1)[-1].strip())
    if width < 1 or height < 1:
        raise GalleryError("measure")
    return width, height


def strip_jpeg_app1_metadata(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise GalleryError("strip")
    out = bytearray()
    out.extend(data[:2])
    i = 2
    while i + 2 <= len(data):
        if data[i] != 0xFF:
            raise GalleryError("strip")
        marker = data[i + 1]
        if marker == 0xD9:
            out.extend(data[i:])
            break
        if marker == 0xDA:
            out.extend(data[i:])
            break
        if i + 4 > len(data):
            raise GalleryError("strip")
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        if seglen < 2 or i + 2 + seglen > len(data):
            raise GalleryError("strip")
        segment = data[i:i + 2 + seglen]
        if marker == 0xE1:
            payload = data[i + 4:i + 2 + seglen]
            if payload.startswith(b"Exif\x00\x00") or payload.startswith(
                b"http://ns.adobe.com/xap/1.0/\x00"
            ) or payload.startswith(b"http://ns.adobe.com/xmp/extension/\x00"):
                i += 2 + seglen
                continue
        out.extend(segment)
        i += 2 + seglen
    else:
        raise GalleryError("strip")
    return bytes(out)


def jpeg_sof_size(data: bytes) -> tuple[int, int]:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0x01):
            continue
        if marker == 0xD9:
            break
        if i + 2 > len(data):
            break
        seglen = int.from_bytes(data[i:i + 2], "big")
        if marker == 0xC0 and seglen >= 7 and i + 7 <= len(data):
            height = int.from_bytes(data[i + 3:i + 5], "big")
            width = int.from_bytes(data[i + 5:i + 7], "big")
            return width, height
        i += seglen
    return 0, 0


def validate_gallery_jpeg(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8\xff"):
        raise GalleryError("validate")
    i = 2
    saw_baseline = False
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise GalleryError("validate")
        marker = data[i + 1]
        i += 2
        if marker == 0xC0:
            saw_baseline = True
            break
        if marker in (0xD8, 0x01):
            continue
        if marker == 0xD9:
            break
        if i + 2 > len(data):
            break
        seglen = int.from_bytes(data[i:i + 2], "big")
        i += seglen
    if not saw_baseline:
        raise GalleryError("validate")
    width, height = jpeg_sof_size(data)
    if width < 1 or height < 1:
        raise GalleryError("validate")
    if max(width, height) > GALLERY_MAX_EDGE:
        raise GalleryError("validate")
    return width, height


def gallery_convert(src: Path, header_data: bytes, kind: str) -> tuple[bytes, int, int]:
    if not shutil.which("sips"):
        raise GalleryError("sips")
    orient = media_orientation_flags(header_data, kind)
    width, height = sips_measure(src)
    out_temp = gallery_temp_path()
    cmd = ["sips"]
    cmd.extend(orient)
    if max(width, height) > GALLERY_MAX_EDGE:
        cmd.extend(["-Z", str(GALLERY_MAX_EDGE)])
    cmd.extend(["-s", "format", "jpeg", "-s", "formatOptions", "80", "--out", str(out_temp), str(src)])
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        gallery_delete_temps(out_temp)
        raise GalleryError("convert")
    try:
        raw = out_temp.read_bytes()
        cleaned = strip_jpeg_app1_metadata(raw)
        width, height = validate_gallery_jpeg(cleaned)
    except GalleryError:
        gallery_delete_temps(out_temp)
        raise
    finally:
        gallery_delete_temps(out_temp)
    return cleaned, width, height


def gallery_usage() -> tuple[int, int]:
    if not GALLERY_DIR.is_dir():
        return 0, 0
    count = 0
    total = 0
    for entry in GALLERY_DIR.iterdir():
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        if not entry.is_file() or entry.suffix.lower() != ".jpg":
            continue
        if not GALLERY_ID_RE.fullmatch(entry.stem):
            continue
        count += 1
        try:
            total += entry.stat().st_size
        except OSError:
            pass
    return count, total


def gallery_list_payload(full: bool) -> dict:
    if not full:
        return {"photos": []}
    photos = []
    if GALLERY_DIR.is_dir():
        items = []
        for entry in GALLERY_DIR.iterdir():
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if not entry.is_file() or entry.suffix.lower() != ".jpg":
                continue
            if not GALLERY_ID_RE.fullmatch(entry.stem):
                continue
            try:
                mtime = entry.stat().st_mtime
                data = entry.read_bytes()
                width, height = jpeg_sof_size(data)
            except OSError:
                continue
            if width < 1 or height < 1:
                continue
            photo_id = entry.stem
            items.append((mtime, photo_id, width, height))
        items.sort(key=lambda row: row[0], reverse=True)
        for _mtime, photo_id, width, height in items:
            photos.append(
                {
                    "id": photo_id,
                    "w": width,
                    "h": height,
                    "src": f"/gallery/{photo_id}.jpg",
                }
            )
    return {"photos": photos}


def parse_multipart_file(body: bytes, content_type: str) -> tuple[str, bytes | None]:
    """Return ('ok', data), ('many', None), or ('bad', None)."""
    if not content_type.startswith("multipart/form-data"):
        return "bad", None
    match = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type)
    if not match:
        return "bad", None
    boundary = (match.group(1) or match.group(2)).encode("latin-1")
    delimiter = b"--" + boundary
    parts = body.split(delimiter)
    file_parts = []
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2]
        header_blob, _, payload = part.partition(b"\r\n\r\n")
        if not header_blob:
            continue
        headers = header_blob.decode("latin-1", errors="replace").split("\r\n")
        disp = ""
        for line in headers:
            if line.lower().startswith("content-disposition:"):
                disp = line
                break
        if 'name="file"' not in disp and "name=file" not in disp:
            continue
        file_parts.append(payload.rstrip(b"\r\n"))
    if len(file_parts) > 1:
        return "many", None
    if len(file_parts) != 1:
        return "bad", None
    return "ok", file_parts[0]


ALLOWED_FILES = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/calendar.html",
    "/weather.html",
    "/traffic.html",
    "/network.html",
    "/remote.html",
    "/settings.html",
    "/settings-apps.html",
    "/settings-theme.html",
    "/settings-location.html",
    "/settings-headlines.html",
    "/settings-schedule.html",
    "/screensaver.html",
    "/screensaver.css",
    "/screensaver.js",
    "/keel.html",
    "/keel.css",
    "/keel.js",
    "/style.css",
    "/settings.css",
    "/network.css",
    "/tokens.css",
    "/main.js",
    "/dashboard.js",
    "/calendar.js",
    "/weather.js",
    "/traffic.js",
    "/slate-surface.js",
    "/slate-place.js",
    "/network.js",
    "/calendar.css",
    "/weather.css",
    "/traffic.css",
    "/settings.js",
    "/remote.js",
    "/remote.css",
    "/remote-consumer.js",
    "/remote-send.js",
    "/settings-apps.js",
    "/settings-theme.js",
    "/settings-location.js",
    "/settings-headlines.js",
    "/settings-schedule.js",
    "/data.json",
    "/apps.json",
    "/apps-catalog.json",
    "/settings.json",
    "/place.json",
    "/ambient.js",
    "/ambient.css",
    "/ambient.json",
    "/tv-appearance.css",
    "/tv-appearance.js",
    "/assets/wallpapers/alpine.jpg",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/favicon.svg",
    "/assets/shift-a-slate-dim.svg",
    "/gallery.html",
    "/gallery.css",
    "/gallery.js",
    "/slate-surface.js",
    "/slate-place.js",
}
FONT_FILE = re.compile(r"^/assets/fonts/[a-z0-9][a-z0-9.-]*\.ttf$")
ICON_FILE = re.compile(r"^/assets/icons/[a-z0-9][a-z0-9-]*\.svg$")
APP_ICON = re.compile(r"^/assets/app/[a-z0-9][a-z0-9.-]*\.png$")
BLOCKED_FILES = {
    "/data.local.json",
    "/calendar-cache.local.json",
    "/server.py",
    "/pin.local",
    "/atv.local",
    "/gallery.local",
}
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
    if path == "/gallery.local" or path.startswith("/gallery.local/"):
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


def new_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def load_pin(lan: bool) -> str:
    """Return the Wi-Fi PIN. Create pin.local the first time it is missing."""
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
        if pin:
            if not PIN_RE.fullmatch(pin):
                print("pin.local must contain 4 to 8 digits and nothing else.", file=sys.stderr)
                sys.exit(1)
            protect_pin_file()
            if lan:
                print("The phone needs the PIN saved in pin.local.")
            return pin
    pin = new_pin()
    PIN_PATH.write_text(pin + "\n", encoding="utf-8")
    protect_pin_file()
    print(f"Phone PIN: {pin}")
    print("Saved in pin.local. Change it in Settings. It is printed only this once.")
    return pin


def home_apps_from_public() -> list:
    """Use the shipped apps.json row when a new settings file is created."""
    try:
        raw = json.loads(APPS_PUBLIC.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_HOME_APPS)
    if not isinstance(raw, list):
        return list(DEFAULT_HOME_APPS)
    ids = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    found = normalize_home_apps(ids)
    return found if found else list(DEFAULT_HOME_APPS)


def default_settings_payload() -> dict:
    return {
        "homeApps": home_apps_from_public(),
        "ambientPreset": DEFAULT_AMBIENT_PRESET,
        "location": dict(DEFAULT_LOCATION),
        "hidePointer": False,
        "showCredit": True,
        "tileSize": "auto",
        "hdmiInput": "1",
        "remoteEnabled": True,
        "tvAppearance": "sculptural",
        "tvBackdrop": "ambient",
        "tvMotion": "drift",
        "tvIntensity": "balanced",
        "tvAquaPalette": "tide",
        "tvFlurryPalette": "spectrum",
    }


def ensure_local_files() -> None:
    """Create the gitignored files a fresh checkout does not have."""
    gallery_ensure_dir()
    if not SETTINGS_LOCAL.exists():
        write_settings_local(default_settings_payload())
        print("Wrote settings.local.json. Home apps and the place can be changed in Settings.")
    if not LOCAL.exists():
        LOCAL.write_text(json.dumps(PLACEHOLDER, indent=2) + "\n", encoding="utf-8")
        protect_local_file(LOCAL)
        print("Wrote data.local.json with an example schedule. Guest pages show Busy.")


def protect_pin_file() -> None:
    try:
        os.chmod(PIN_PATH, 0o600)
    except OSError:
        pass


def set_pin_value(pin: str, keep_token: str = "") -> None:
    global EXPECTED_PIN
    PIN_PATH.write_text(pin + "\n", encoding="utf-8")
    protect_pin_file()
    EXPECTED_PIN = pin
    with STATE_LOCK:
        if keep_token and keep_token in SESSIONS:
            SESSIONS.clear()
            SESSIONS.add(keep_token)
        else:
            SESSIONS.clear()


def pin_configured() -> bool:
    return bool(PIN_RE.fullmatch(EXPECTED_PIN or ""))


def calendar_connection_status() -> dict:
    calendar_id, client_id, client_secret, refresh_token = calendar_credentials()
    name = ""
    if calendar_id and refresh_token:
        try:
            token = google_access_token(client_id, client_secret, refresh_token)
            if token:
                url = "https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar_id, safe="")
                request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                with urlopen(request, timeout=12) as response:
                    meta = json.loads(response.read().decode("utf-8"))
                if isinstance(meta, dict) and isinstance(meta.get("summary"), str):
                    name = meta["summary"].strip()
        except (OSError, HTTPError, json.JSONDecodeError, ValueError):
            pass
    synced = ""
    stale = False
    with CALENDAR_LOCK:
        if isinstance(CALENDAR_CACHE, dict):
            synced = CALENDAR_CACHE.get("syncedAt", "") if isinstance(CALENDAR_CACHE.get("syncedAt"), str) else ""
            stale = CALENDAR_CACHE.get("stale") is True
    return {
        "configured": bool(calendar_id and client_id and client_secret and refresh_token),
        "hasClient": bool(client_id and client_secret),
        "hasToken": bool(refresh_token),
        "calendarId": calendar_id if calendar_id else "",
        "calendarName": name,
        "syncedAt": synced,
        "stale": stale,
    }


def list_google_calendars() -> list[dict]:
    calendar_id, client_id, client_secret, refresh_token = calendar_credentials()
    if not all((client_id, client_secret, refresh_token)):
        return []
    token = google_access_token(client_id, client_secret, refresh_token)
    if not token:
        return []
    request = Request(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=50",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8"))
    out = []
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        if not isinstance(cid, str) or not cid.strip():
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), str) else cid
        out.append({"id": cid.strip(), "summary": summary.strip() or cid.strip()})
    out.sort(key=lambda row: row["summary"].lower())
    return out


def oauth_exchange_code(code: str) -> dict:
    client_id = keychain_value("client-id")
    client_secret = keychain_value("client-secret")
    body = urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": OAUTH_REDIRECT,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


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


def remote_cookie_header(token: str, max_age: int) -> str:
    return f"{REMOTE_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}"


def remote_enabled() -> bool:
    return SETTINGS_STATE.get("remoteEnabled") is not False


def remote_lan_ok(server) -> bool:
    return bool(getattr(server, "lan_enabled", False))


def remote_session_ok(token: str) -> bool:
    if not token or not REMOTE_COOKIE_RE.fullmatch(token):
        return False
    with STATE_LOCK:
        return token in REMOTE_SESSIONS


def remember_remote_session(token: str) -> None:
    with STATE_LOCK:
        if len(REMOTE_SESSIONS) >= 32:
            REMOTE_SESSIONS.clear()
        REMOTE_SESSIONS.add(token)


def forget_remote_session(token: str) -> None:
    if not token:
        return
    with STATE_LOCK:
        REMOTE_SESSIONS.discard(token)


def prune_remote_pairings() -> None:
    now = time.time()
    with REMOTE_PAIR_LOCK:
        expired = [code for code, exp in REMOTE_PAIRINGS.items() if exp <= now]
        for code in expired:
            REMOTE_PAIRINGS.pop(code, None)


def queue_remote_event(event: dict) -> dict:
    global REMOTE_SEQ
    with REMOTE_EVENTS_LOCK:
        REMOTE_SEQ += 1
        item = {"seq": REMOTE_SEQ, **event}
        REMOTE_EVENTS.append(item)
        if len(REMOTE_EVENTS) > 200:
            del REMOTE_EVENTS[:-200]
        return item


TV_UA = re.compile(
    r"Android TV|Google TV|AFT[A-Z0-9]|BRAVIA|CrKey|SMART-TV|SmartTV|Smart-TV|Television",
    re.I,
)


def remote_client_is_tv(handler, obj) -> bool:
    """A phone page must not count as the set. An older TV page still can."""
    if isinstance(obj, dict) and obj.get("tv") is True:
        return True
    ua = handler.headers.get("User-Agent", "")
    if TV_UA.search(ua):
        return True
    store = atv_remote.get_service(remote_enabled).store
    with store.lock:
        known = store.host
    return bool(known) and known == handler.client_address[0]


def remote_tv_online() -> bool:
    return (time.time() - REMOTE_TV_LAST) <= REMOTE_TV_ONLINE_S


def remote_status_payload(paired: bool) -> dict:
    svc = atv_remote.get_service(remote_enabled)
    return {
        "ok": True,
        "remoteEnabled": remote_enabled(),
        "paired": paired,
        "tvOnline": remote_tv_online(),
        "tvKnown": svc.tv_known(),
        "tvService": svc.status(),
    }


def remote_bridge_action(action: str) -> dict | None:
    if action == "openScreensaverSettings":
        return {"type": "bridge", "action": action}
    if action == "openGoogleTvHome":
        return {"type": "bridge", "action": action}
    if action == "navigateHome":
        return {"type": "bridge", "action": action}
    return None


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".svg": "image/svg+xml",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_response(self, code, message=None):
        self._response_code = code
        super().send_response(code, message)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        path = public_path(self.path) or ""
        if getattr(self, "_response_code", 0) in (200, 304):
            if path.startswith("/assets/"):
                self.send_header("Cache-Control", "public, max-age=3600")
            elif path.endswith((".html", ".css", ".js")) or path == "/":
                self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def redirect(self, target: str, code=302):
        self.send_response(code)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
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

    def send_bytes(self, code, body: bytes, content_type: str, cache_control="private, max-age=120"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
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

    def serve_gallery_list(self):
        if not self.pin_ok():
            self.send_json(401, {"error": "pin"})
            return
        full = self.headers.get("X-Slate-Full", "") == "1"
        self.send_json(200, gallery_list_payload(full))

    def serve_gallery_image(self, photo_id: str):
        if not self.pin_ok():
            self.send_json(401, {"error": "pin"})
            return
        path = GALLERY_DIR / f"{photo_id}.jpg"
        if not _gallery_path_inside(path) or not path.is_file() or path.is_symlink():
            self.reject()
            return
        try:
            body = path.read_bytes()
        except OSError:
            self.reject()
            return
        self.send_bytes(200, body, "image/jpeg", cache_control="private, no-store")

    def read_upload_body(self, max_len: int) -> bytes | None:
        raw_len = self.headers.get("Content-Length", "")
        if not raw_len.isdigit():
            self.close_connection = True
            return None
        length = int(raw_len)
        if length > max_len:
            return None
        if length == 0:
            return b""
        try:
            return self.rfile.read(length)
        except OSError:
            self.close_connection = True
            return None

    def save_gallery_upload(self):
        if not self.settings_write_ok():
            self.close_connection = True
            self.send_json(401, {"error": "pin"})
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self.send_json(415, {"error": "type"})
            return
        raw_len = self.headers.get("Content-Length", "")
        if not raw_len.isdigit():
            self.close_connection = True
            self.send_json(400, {"error": "bad"})
            return
        length = int(raw_len)
        if length > GALLERY_MAX_UPLOAD:
            self.close_connection = True
            self.send_json(413, {"error": "large"})
            return
        if length == 0:
            self.send_json(400, {"error": "bad"})
            return
        body = self.read_upload_body(GALLERY_MAX_UPLOAD)
        if body is None:
            self.send_json(400, {"error": "bad"})
            return
        if len(body) != length:
            self.send_json(400, {"error": "bad"})
            return
        parse_kind, file_data = parse_multipart_file(body, ctype)
        if parse_kind == "many":
            self.send_json(400, {"error": "bad"})
            return
        if parse_kind != "ok" or not file_data:
            self.send_json(400, {"error": "bad"})
            return
        kind = sniff_media(file_data)
        if kind is None or kind not in {"jpeg", "png", "gif", "webp", "heif"}:
            self.send_json(415, {"error": "type"})
            return
        src_temp = gallery_temp_path()
        out_temp = gallery_temp_path()
        try:
            src_temp.write_bytes(file_data)
            cleaned, width, height = gallery_convert(src_temp, file_data, kind)
        except GalleryError:
            gallery_delete_temps(src_temp, out_temp)
            self.send_json(415, {"error": "type"})
            return
        finally:
            gallery_delete_temps(src_temp)
        photo_id = secrets.token_hex(16)
        final_path = GALLERY_DIR / f"{photo_id}.jpg"
        try:
            out_temp.write_bytes(cleaned)
        except OSError:
            gallery_delete_temps(out_temp)
            self.send_json(415, {"error": "type"})
            return
        gallery_ensure_dir()
        with GALLERY_LOCK:
            count, total = gallery_usage()
            if count >= GALLERY_MAX_COUNT or total + len(cleaned) > GALLERY_MAX_TOTAL:
                gallery_delete_temps(out_temp)
                self.send_json(507, {"error": "full"})
                return
            if not _gallery_path_inside(final_path):
                gallery_delete_temps(out_temp)
                self.send_json(415, {"error": "type"})
                return
            try:
                os.replace(out_temp, final_path)
                os.chmod(final_path, 0o600)
            except OSError:
                gallery_delete_temps(out_temp)
                self.send_json(415, {"error": "type"})
                return
        payload = {
            "ok": True,
            "id": photo_id,
            "w": width,
            "h": height,
            "src": f"/gallery/{photo_id}.jpg",
        }
        self.send_json(201, payload)

    def serve_settings_get(self):
        with PUBLISH_LOCK:
            publish_settings()
            body = dict(SETTINGS_STATE)
        body["pinConfigured"] = pin_configured()
        self.send_json(200, body)

    def serve_headlines(self):
        self.send_json(200, headlines_payload())

    def serve_calendar(self):
        params = parse_qs(urlsplit(self.path).query)
        now = datetime.now(timezone.utc)
        start = params.get("start", [(now - timedelta(days=1)).isoformat()])[0]
        end = params.get("end", [(now + timedelta(days=45)).isoformat()])[0]
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if start_dt.tzinfo is None or end_dt.tzinfo is None or end_dt <= start_dt or end_dt - start_dt > timedelta(days=62):
                raise ValueError
        except (TypeError, ValueError):
            self.send_json(400, {"error": "range"})
            return
        full = self.headers.get("X-Slate-Full", "") == "1"
        if full and not self.pin_ok():
            self.send_json(401, {"error": "pin"})
            return
        payload = calendar_payload(start_dt.isoformat(), end_dt.isoformat())
        self.send_json(200, payload if full else guest_calendar(payload))

    def radar_bbox(self, zoom: str) -> tuple[float, float, float, float, float, float]:
        with PUBLISH_LOCK:
            location = dict(SETTINGS_STATE.get("location", DEFAULT_LOCATION))
        lat, lon = float(location["lat"]), float(location["lon"])
        span = 1.45 if zoom == "near" else 3.5
        return lat, lon, span, lon - span, lat - span * 0.58, lon + span, lat + span * 0.58

    def serve_radar(self):
        params = parse_qs(urlsplit(self.path).query)
        zoom = params.get("zoom", ["near"])[0]
        layer = params.get("layer", ["reflectivity"])[0]
        try:
            frame = int(params.get("frame", ["0"])[0])
        except ValueError:
            frame = -1
        if zoom not in {"near", "wide"}:
            self.send_json(400, {"error": "bad"})
            return
        lat, lon, span, west, south, east, north = self.radar_bbox(zoom)
        if layer == "basemap":
            key = ("basemap", round(lat, 2), round(lon, 2), zoom)
            with RADAR_LOCK:
                cached = MAP_CACHE.get(key)
                if cached and time.monotonic() - cached[0] < 86400:
                    self.send_bytes(200, cached[1], "image/png")
                    return
            bbox = f"{west},{south},{east},{north}"
            query = urlencode({
                "bbox": bbox, "bboxSR": "4326", "imageSR": "4326", "size": "960,540",
                "format": "png", "f": "image",
            })
            request = Request(
                "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/export?"
                + query,
                headers={"User-Agent": NOMINATIM_UA, "Accept": "image/png"},
            )
            try:
                with urlopen(request, timeout=20) as response:
                    body = response.read(4 * 1024 * 1024)
                if not body.startswith(b"\x89PNG"):
                    raise OSError("basemap unavailable")
            except (OSError, HTTPError):
                self.send_json(502, {"error": "map"})
                return
            with RADAR_LOCK:
                MAP_CACHE[key] = (time.monotonic(), body)
            self.send_bytes(200, body, "image/png")
            return
        if frame < 0 or frame > 5:
            self.send_json(400, {"error": "bad"})
            return
        stamp = int(time.time() // 600 * 600) - frame * 600
        key = (round(lat, 2), round(lon, 2), zoom, stamp)
        with RADAR_LOCK:
            cached = RADAR_CACHE.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                self.send_bytes(200, cached[1], "image/png")
                return
        bbox = f"{west},{south},{east},{north}"
        query = urlencode({
            "bbox": bbox, "bboxSR": "4326", "imageSR": "4326", "size": "960,540",
            "format": "png32", "transparent": "true", "f": "image",
            "time": str(stamp * 1000),
        })
        request = Request(
            "https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity_time/ImageServer/exportImage?" + query,
            headers={"User-Agent": NOMINATIM_UA, "Accept": "image/png"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                body = response.read(4 * 1024 * 1024)
                content_type = response.headers.get_content_type()
            if not body.startswith(b"\x89PNG"):
                raise OSError("radar image unavailable")
        except (OSError, HTTPError):
            self.send_json(502, {"error": "radar"})
            return
        with RADAR_LOCK:
            RADAR_CACHE[key] = (time.monotonic(), body)
            if len(RADAR_CACHE) > 16:
                oldest = min(RADAR_CACHE, key=lambda item: RADAR_CACHE[item][0])
                RADAR_CACHE.pop(oldest, None)
        self.send_bytes(200, body, content_type if content_type.startswith("image/") else "image/png")

    def serve_calendar_status(self):
        self.send_json(200, calendar_connection_status())

    def serve_calendar_list(self):
        if not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        try:
            items = list_google_calendars()
        except (OSError, HTTPError, json.JSONDecodeError, ValueError):
            self.send_json(502, {"error": "google"})
            return
        self.send_json(200, {"calendars": items})

    def serve_oauth_start(self):
        if not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        client_id = keychain_value("client-id")
        if not client_id:
            self.send_json(400, {"error": "client"})
            return
        state = secrets.token_urlsafe(24)
        with OAUTH_LOCK:
            OAUTH_PENDING[state] = time.monotonic() + 600
        params = urlencode({
            "client_id": client_id,
            "redirect_uri": OAUTH_REDIRECT,
            "response_type": "code",
            "scope": GOOGLE_CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        self.redirect("https://accounts.google.com/o/oauth2/v2/auth?" + params)

    def serve_oauth_callback(self):
        if not request_is_localhost(self):
            self.reject(403)
            return
        params = parse_qs(urlsplit(self.path).query)
        state = params.get("state", [""])[0]
        code = params.get("code", [""])[0]
        with OAUTH_LOCK:
            expires = OAUTH_PENDING.pop(state, 0.0)
        if not code or time.monotonic() > expires:
            self.redirect("/settings-schedule.html?error=oauth")
            return
        try:
            payload = oauth_exchange_code(code)
            refresh = payload.get("refresh_token") if isinstance(payload, dict) else ""
            if not isinstance(refresh, str) or not refresh.strip():
                self.redirect("/settings-schedule.html?error=token")
                return
            if not keychain_set("refresh-token", refresh.strip()):
                self.redirect("/settings-schedule.html?error=keychain")
                return
        except (OSError, HTTPError, json.JSONDecodeError, ValueError):
            self.redirect("/settings-schedule.html?error=oauth")
            return
        refresh_calendar_store(force=True)
        self.redirect("/settings-schedule.html?connected=1")

    def save_pin(self, obj):
        if obj is None or set(obj.keys()) != {"pin", "confirm"}:
            self.send_json(400, {"error": "bad"})
            return
        pin = obj.get("pin") if isinstance(obj.get("pin"), str) else ""
        confirm = obj.get("confirm") if isinstance(obj.get("confirm"), str) else ""
        if pin != confirm or not PIN_RE.fullmatch(pin):
            self.send_json(400, {"error": "format"})
            return
        if getattr(self.server, "require_pin", False):
            if not self.settings_write_ok():
                self.send_json(401, {"error": "pin"})
                return
        elif not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        keep = self.cookie("slate") if session_ok(self.cookie("slate")) else ""
        set_pin_value(pin, keep)
        self.send_json(200, {"ok": True, "pinConfigured": True})

    def save_calendar_credentials(self, obj):
        if not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        if obj is None:
            self.send_json(400, {"error": "bad"})
            return
        client_id = obj.get("clientId") if isinstance(obj.get("clientId"), str) else ""
        client_secret = obj.get("clientSecret") if isinstance(obj.get("clientSecret"), str) else ""
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id or not client_secret:
            self.send_json(400, {"error": "bad"})
            return
        if not keychain_set("client-id", client_id) or not keychain_set("client-secret", client_secret):
            self.send_json(500, {"error": "keychain"})
            return
        self.send_json(200, {"ok": True, "hasClient": True})

    def save_calendar_selection(self, obj):
        if not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        if obj is None or set(obj.keys()) != {"calendarId"}:
            self.send_json(400, {"error": "bad"})
            return
        calendar_id = obj.get("calendarId") if isinstance(obj.get("calendarId"), str) else ""
        calendar_id = calendar_id.strip()
        if not calendar_id:
            self.send_json(400, {"error": "bad"})
            return
        with PUBLISH_LOCK:
            current = dict(SETTINGS_STATE)
            current["calendarId"] = calendar_id
            write_settings_local(current)
            publish_settings()
        refresh_calendar_store(force=True)
        self.send_json(200, calendar_connection_status())

    def disconnect_calendar(self):
        if not request_is_localhost(self):
            self.send_json(403, {"error": "host"})
            return
        keychain_delete("refresh-token")
        with PUBLISH_LOCK:
            current = dict(SETTINGS_STATE)
            current["calendarId"] = ""
            write_settings_local(current)
            publish_settings()
        global CALENDAR_CACHE
        with CALENDAR_LOCK:
            CALENDAR_CACHE = None
        self.send_json(200, calendar_connection_status())

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
        if not allowed or not allowed.issubset({
            "homeApps",
            "ambientPreset",
            "location",
            "hidePointer",
            "showCredit",
            "tileSize",
            "hdmiInput",
            "tvAppearance",
            "tvBackdrop",
            "tvMotion",
            "tvIntensity",
            "tvAquaPalette",
            "tvFlurryPalette",
            "remoteEnabled",
            "headlines",
        }):
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
            if "hidePointer" in obj:
                current["hidePointer"] = obj.get("hidePointer") is True
            if "showCredit" in obj:
                current["showCredit"] = obj.get("showCredit") is not False
            if "tileSize" in obj:
                current["tileSize"] = normalize_tile_size(obj.get("tileSize"))
            if "hdmiInput" in obj:
                current["hdmiInput"] = normalize_hdmi_input(obj.get("hdmiInput"))
            if "remoteEnabled" in obj:
                current["remoteEnabled"] = obj.get("remoteEnabled") is not False
            headlines_changed = False
            if "headlines" in obj:
                current["headlines"] = normalize_headlines(obj.get("headlines"))
                headlines_changed = True
            current.update(normalize_tv_appearance({**current, **{
                key: value for key, value in obj.items() if key.startswith("tv")
            }}))
            write_settings_local(current)
            publish_settings()
            body = dict(SETTINGS_STATE)
        if headlines_changed:
            refresh_headlines_store()
        self.send_json(200, body)

    def remote_api_ok(self) -> bool:
        if not remote_lan_ok(self.server):
            return False
        if not remote_enabled():
            return False
        return True

    def remote_paired(self) -> bool:
        return remote_session_ok(self.cookie(REMOTE_COOKIE))

    def serve_remote_status(self):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        self.send_json(200, remote_status_payload(self.remote_paired()))

    def serve_remote_events(self):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        params = parse_qs(urlsplit(self.path).query)
        try:
            since = int(params.get("since", ["0"])[0])
        except ValueError:
            since = 0
        with REMOTE_EVENTS_LOCK:
            latest = REMOTE_SEQ
            events = [ev for ev in REMOTE_EVENTS if ev.get("seq", 0) > since]
        self.send_json(200, {"events": events, "latest": latest})

    def remote_pairing_code(self):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        prune_remote_pairings()
        code = f"{secrets.randbelow(900000) + 100000}"
        with REMOTE_PAIR_LOCK:
            REMOTE_PAIRINGS[code] = time.time() + REMOTE_PHONE_TTL
        self.send_json(200, {"code": code, "expiresIn": REMOTE_PHONE_TTL})

    def remote_pair(self, obj):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        if obj is None or set(obj.keys()) != {"code"}:
            self.send_json(400, {"error": "bad"})
            return
        offered = obj.get("code") if isinstance(obj.get("code"), str) else ""
        prune_remote_pairings()
        with REMOTE_PAIR_LOCK:
            expires = REMOTE_PAIRINGS.get(offered)
        if not expires or expires <= time.time():
            self.send_json(401, {"error": "code"})
            return
        with REMOTE_PAIR_LOCK:
            REMOTE_PAIRINGS.pop(offered, None)
        token = secrets.token_urlsafe(32)
        remember_remote_session(token)
        self.send_json(200, {"ok": True}, (("Set-Cookie", remote_cookie_header(token, REMOTE_PHONE_TTL)),))

    def remote_unpair(self):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        forget_remote_session(self.cookie(REMOTE_COOKIE))
        self.send_json(200, {"ok": True}, (("Set-Cookie", remote_cookie_header("", 0)),))

    def remote_heartbeat(self, obj):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        if not remote_client_is_tv(self, obj):
            self.send_json(200, {"ok": True, "ignored": True})
            return
        global REMOTE_TV_PAGE, REMOTE_TV_LAST
        page = obj.get("page") if isinstance(obj.get("page"), str) else ""
        REMOTE_TV_PAGE = page[:120]
        REMOTE_TV_LAST = time.time()
        client_ip = self.client_address[0]
        atv_remote.get_service(remote_enabled).note_tv_host(client_ip)
        self.send_json(200, {"ok": True})

    def remote_command(self, obj):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        if not self.remote_paired():
            self.send_json(401, {"error": "remote"})
            return
        if obj is None:
            self.send_json(400, {"error": "bad"})
            return
        svc = atv_remote.get_service(remote_enabled)
        kind = obj.get("type")
        if kind == "key":
            key = obj.get("key")
            if not isinstance(key, str):
                self.send_json(400, {"error": "bad"})
                return
            if key in atv_remote.VOLUME_KEYS:
                if not svc.ready():
                    self.send_json(409, {"error": "tv"})
                    return
            if key == "Home" and not svc.ready():
                queue_remote_event(remote_bridge_action("navigateHome"))
                self.send_json(200, {"ok": True, "path": "page"})
                return
            if key in atv_remote.PAGE_KEYS or key in atv_remote.VOLUME_KEYS or key == "Home":
                if svc.ready() and key in atv_remote.KEY_MAP:
                    if svc.inject_key(key):
                        self.send_json(200, {"ok": True, "path": "tv"})
                        return
                if key in atv_remote.VOLUME_KEYS:
                    self.send_json(409, {"error": "tv"})
                    return
                if key in atv_remote.PAGE_KEYS:
                    queue_remote_event({"type": "key", "key": key})
                    self.send_json(200, {"ok": True, "path": "page"})
                    return
            self.send_json(400, {"error": "bad"})
            return
        if kind == "bridge":
            action = obj.get("action")
            if not isinstance(action, str):
                self.send_json(400, {"error": "bad"})
                return
            payload = remote_bridge_action(action)
            if not payload:
                self.send_json(400, {"error": "bad"})
                return
            queue_remote_event(payload)
            self.send_json(200, {"ok": True, "path": "page"})
            return
        self.send_json(400, {"error": "bad"})

    def remote_tv_pair(self, obj):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        host = None
        if obj and isinstance(obj.get("host"), str) and obj.get("host").strip():
            host = obj.get("host").strip()
        client_ip = self.client_address[0]
        code, payload = atv_remote.get_service(remote_enabled).begin_tv_pair(host, client_ip)
        self.send_json(code, payload)

    def remote_tv_code(self, obj):
        if not self.remote_api_ok():
            self.send_json(403, {"error": "lan"})
            return
        if obj is None or set(obj.keys()) != {"code"} or not isinstance(obj.get("code"), str):
            self.send_json(400, {"error": "bad"})
            return
        code, payload = atv_remote.get_service(remote_enabled).submit_tv_code(obj["code"])
        self.send_json(code, payload)

    def save_schedule(self, obj):
        if obj is None or set(obj.keys()) != {"today", "deadlines", "money"}:
            self.send_json(400, {"error": "bad"})
            return
        if not isinstance(obj.get("today"), list) or not isinstance(obj.get("deadlines"), list):
            self.send_json(400, {"error": "bad"})
            return
        if not isinstance(obj.get("money"), dict):
            self.send_json(400, {"error": "bad"})
            return
        payload = normalize_schedule(obj)
        with PUBLISH_LOCK:
            write_schedule_local(payload)
            publish_data()
            body = dict(FULL_PAYLOAD) if isinstance(FULL_PAYLOAD, dict) else payload
        self.send_json(200, body)

    def do_GET(self):
        path = public_path(self.path)
        if path is None:
            self.reject()
            return
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "slate"})
            return
        if path == "/remote/v1/status.json":
            self.serve_remote_status()
            return
        if path == "/remote/v1/events.json":
            self.serve_remote_events()
            return
        if path == "/network.json":
            query = parse_qs(urlsplit(self.path).query)
            scan = query.get("scan", [""])[0] == "1"
            if scan and not getattr(self.server, "lan_enabled", False):
                self.send_json(403, {"error": "lan"})
                return
            self.send_json(200, network_snapshot(scan))
            return
        if path == "/calendar.json":
            self.serve_calendar()
            return
        if path == "/calendar/status.json":
            self.serve_calendar_status()
            return
        if path == "/calendar/list.json":
            self.serve_calendar_list()
            return
        if path == "/oauth/start":
            self.serve_oauth_start()
            return
        if path == "/oauth/callback":
            self.serve_oauth_callback()
            return
        if path == "/headlines.json":
            self.serve_headlines()
            return
        if path == "/gallery.json":
            self.serve_gallery_list()
            return
        image_match = GALLERY_IMAGE_RE.match(path or "")
        if image_match:
            self.serve_gallery_image(image_match.group(1))
            return
        if path == "/radar.png":
            self.serve_radar()
            return
        if path == "/traffic.json":
            query = parse_qs(urlsplit(self.path).query)
            self.send_json(200, traffic_payload(parse_traffic_center(query)))
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
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "slate"})
            return
        if path == "/calendar.json":
            self.serve_calendar()
            return
        if path == "/headlines.json":
            self.serve_headlines()
            return
        if path == "/gallery.json":
            self.serve_gallery_list()
            return
        image_match = GALLERY_IMAGE_RE.match(path or "")
        if image_match:
            self.serve_gallery_image(image_match.group(1))
            return
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
        if path == "/remote/v1/pairing.json":
            self.remote_pairing_code()
            return
        if path == "/remote/v1/pair.json":
            obj = self.read_object(max_len=128)
            self.remote_pair(obj)
            return
        if path == "/remote/v1/unpair.json":
            self.remote_unpair()
            return
        if path == "/remote/v1/command.json":
            obj = self.read_object()
            self.remote_command(obj)
            return
        if path == "/remote/v1/heartbeat.json":
            obj = self.read_object(max_len=256)
            self.remote_heartbeat(obj if isinstance(obj, dict) else {})
            return
        if path == "/remote/v1/tv-pair.json":
            obj = self.read_object(max_len=256)
            self.remote_tv_pair(obj if isinstance(obj, dict) else {})
            return
        if path == "/remote/v1/tv-code.json":
            obj = self.read_object(max_len=128)
            self.remote_tv_code(obj)
            return
        if path == "/gallery":
            self.save_gallery_upload()
            return
        if path == "/pin.json":
            obj = self.read_object(max_len=128)
            self.save_pin(obj)
            return
        if path == "/calendar/credentials.json":
            obj = self.read_object()
            self.save_calendar_credentials(obj)
            return
        if path == "/calendar/select.json":
            obj = self.read_object()
            self.save_calendar_selection(obj)
            return
        if path == "/calendar/disconnect.json":
            self.disconnect_calendar()
            return
        if path == "/settings.json":
            if not self.settings_write_ok():
                self.close_connection = True
                self.send_json(401, {"error": "pin"})
                return
            obj = self.read_object()
            self.save_settings(obj)
            return
        if path == "/schedule.json":
            if not self.settings_write_ok():
                self.close_connection = True
                self.send_json(401, {"error": "pin"})
                return
            obj = self.read_object()
            self.save_schedule(obj)
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


def lan_network() -> tuple[str, str, ipaddress.IPv4Network] | None:
    address = lan_address()
    if not address:
        return None
    try:
        result = subprocess.run(
            ["ifconfig", "en0"], capture_output=True, text=True, timeout=2, check=False
        )
        match = re.search(r"\bnetmask\s+0x([0-9a-fA-F]{8})", result.stdout)
        prefix = ipaddress.IPv4Address(int(match.group(1), 16)) if match else None
        interface = ipaddress.IPv4Interface(f"{address}/{prefix or '24'}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        interface = ipaddress.IPv4Interface(f"{address}/24")
    if not interface.ip.is_private:
        return None
    return "en0", address, interface.network


def arp_devices(network: ipaddress.IPv4Network, local_ip: str) -> list[dict]:
    found: dict[str, dict] = {}
    try:
        result = subprocess.run(
            ["arp", "-an"], capture_output=True, text=True, timeout=3, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            match = re.search(r"^\s*(.*?)\s+\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+([^\s]+)", line)
            if not match:
                continue
            name, address, hardware = match.groups()
            try:
                ip = ipaddress.IPv4Address(address)
            except ipaddress.AddressValueError:
                continue
            if ip not in network or hardware.lower() == "(incomplete)":
                continue
            found[address] = {
                "ip": address,
                "name": "" if name.strip() in {"", "?"} else name.strip().rstrip("."),
                "local": address == local_ip,
            }
    found.setdefault(local_ip, {"ip": local_ip, "name": "This Mac", "local": True})
    return sorted(found.values(), key=lambda item: int(ipaddress.IPv4Address(item["ip"])))


def network_snapshot(scan: bool) -> dict:
    global NETWORK_SCAN_CACHE, NETWORK_SCAN_AT
    info = lan_network()
    if not info:
        return {"ok": False, "error": "No private Wi-Fi address found.", "devices": []}
    interface, local_ip, network = info
    if scan:
        with NETWORK_SCAN_LOCK:
            now = time.monotonic()
            if NETWORK_SCAN_CACHE and now - NETWORK_SCAN_AT < 30:
                return dict(NETWORK_SCAN_CACHE, cached=True)
            hosts = list(network.hosts())
            if len(hosts) > 1022:
                return {
                    "ok": False,
                    "error": "This Wi-Fi subnet is too large for a safe scan.",
                    "interface": interface,
                    "address": local_ip,
                    "network": str(network),
                    "devices": arp_devices(network, local_ip),
                }
            ping = shutil.which("ping") or "/sbin/ping"

            def probe(host: ipaddress.IPv4Address) -> bool:
                if str(host) == local_ip:
                    return True
                try:
                    result = subprocess.run(
                        [ping, "-n", "-c", "1", "-W", "350", str(host)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.5,
                        check=False,
                    )
                    return result.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    return False

            with ThreadPoolExecutor(max_workers=48) as pool:
                list(as_completed([pool.submit(probe, host) for host in hosts]))
            snapshot = {
                "ok": True,
                "interface": interface,
                "address": local_ip,
                "network": str(network),
                "devices": arp_devices(network, local_ip),
                "scannedAt": int(time.time()),
                "cached": False,
            }
            NETWORK_SCAN_CACHE = snapshot
            NETWORK_SCAN_AT = time.monotonic()
            return snapshot
    return {
        "ok": True,
        "interface": interface,
        "address": local_ip,
        "network": str(network),
        "devices": arp_devices(network, local_ip),
        "scannedAt": None,
        "cached": False,
    }


def serve_discovery(stop_event: threading.Event) -> None:
    """Answer a nonce challenge from a same-LAN client when --lan is active."""
    request_prefix = "SLATE_DISCOVER_V1 "
    response_prefix = "SLATE_FOUND_V1 "
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
        sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                raw, address = sock.recvfrom(128)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                message = raw.decode("ascii").strip()
                prefix, nonce = message.split(" ", 1)
                if prefix != request_prefix.strip() or not re.fullmatch(r"[0-9a-f]{32}", nonce):
                    continue
                if not ipaddress.ip_address(address[0]).is_private:
                    continue
            except (UnicodeDecodeError, ValueError):
                continue
            try:
                sock.sendto(f"{response_prefix}{nonce} {PORT}".encode("ascii"), address)
            except OSError:
                continue
    except OSError as exc:
        sys.stderr.write(f"Could not start Slate discovery on UDP {DISCOVERY_PORT}: {exc}\n")
    finally:
        sock.close()


def listen(host, require_pin, lan_enabled):
    try:
        server = Server((host, PORT), Handler)
    except OSError as exc:
        print(f"Could not listen on {host}:{PORT}: {exc}", file=sys.stderr)
        return None
    server.require_pin = require_pin
    server.lan_enabled = lan_enabled
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
    ensure_local_files()
    publish_settings()
    publish_data()
    atv_remote.get_service(remote_enabled).start_background()

    local = listen("127.0.0.1", False, lan)
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
            remote = listen(ip, True, lan)
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
    discovery_stop = threading.Event()
    headlines_stop = threading.Event()
    headlines_thread = threading.Thread(
        target=headlines_refresh_loop,
        args=(headlines_stop,),
        name="slate-headlines",
        daemon=True,
    )
    headlines_thread.start()
    threads.append(headlines_thread)
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    if lan and len(servers) > 1:
        discovery = threading.Thread(
            target=serve_discovery,
            args=(discovery_stop,),
            name="slate-discovery",
            daemon=True,
        )
        discovery.start()
        threads.append(discovery)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        discovery_stop.set()
        headlines_stop.set()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            if thread.name == "slate-discovery":
                thread.join(timeout=1)


if __name__ == "__main__":
    main()
