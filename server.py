#!/usr/bin/env python3
"""Serve the TV dashboard and publish data.local.json as data.json."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

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
CALENDAR_PREFETCH_BACK_DAYS = 1
CALENDAR_PREFETCH_FORWARD_DAYS = 45
RADAR_LOCK = threading.Lock()
RADAR_CACHE = {}
MAP_CACHE = {}
OAUTH_LOCK = threading.Lock()
OAUTH_PENDING: dict[str, float] = {}
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
OAUTH_REDIRECT = "http://127.0.0.1:8000/oauth/callback"
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
    "tvAppearance": "sculptural",
    "tvBackdrop": "ambient",
    "tvMotion": "drift",
    "tvIntensity": "balanced",
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
        SETTINGS_STATE = {
            "homeApps": home,
            "ambientPreset": preset,
            "location": location,
            "hidePointer": hide_pointer,
            "showCredit": show_credit,
            "tileSize": tile_size,
            **normalize_tv_appearance(local),
        }
        publish_apps(home)


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


def pin_matches(offered) -> bool:
    """Constant-time check. The length of a wrong PIN does not skip the compare."""
    if not pin_configured():
        return False
    raw = offered if isinstance(offered, str) else ""
    left = hashlib.sha256(raw.encode("utf-8")).digest()
    right = hashlib.sha256(EXPECTED_PIN.encode("utf-8")).digest()
    same = hmac.compare_digest(left, right)
    return bool(PIN_RE.fullmatch(raw)) and same


ALLOWED_FILES = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/calendar.html",
    "/weather.html",
    "/network.html",
    "/settings.html",
    "/settings-apps.html",
    "/settings-theme.html",
    "/settings-location.html",
    "/settings-schedule.html",
    "/screensaver.html",
    "/screensaver.css",
    "/screensaver.js",
    "/style.css",
    "/settings.css",
    "/network.css",
    "/tokens.css",
    "/main.js",
    "/dashboard.js",
    "/calendar.js",
    "/weather.js",
    "/network.js",
    "/calendar.css",
    "/weather.css",
    "/settings.js",
    "/settings-apps.js",
    "/settings-theme.js",
    "/settings-location.js",
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
    "/slate-surface.js",
    "/assets/wallpapers/alpine.jpg",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/favicon.svg",
    "/assets/shift-a-slate-dim.svg",
}
FONT_FILE = re.compile(r"^/assets/fonts/[a-z0-9][a-z0-9.-]*\.ttf$")
ICON_FILE = re.compile(r"^/assets/icons/[a-z0-9][a-z0-9-]*\.svg$")
APP_ICON = re.compile(r"^/assets/app/[a-z0-9][a-z0-9.-]*\.png$")
BLOCKED_FILES = {"/data.local.json", "/calendar-cache.local.json", "/server.py", "/pin.local"}
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
    print("No PIN yet. Set one in Settings on this Mac before using Show all on Wi-Fi.")
    return ""


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

    def send_bytes(self, code, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=120")
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
        body["pinConfigured"] = pin_configured()
        self.send_json(200, body)

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
        if not allowed or not allowed.issubset({"homeApps", "ambientPreset", "location", "hidePointer", "showCredit", "tileSize", "tvAppearance", "tvBackdrop", "tvMotion", "tvIntensity"}):
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
            current.update(normalize_tv_appearance({**current, **{
                key: value for key, value in obj.items() if key.startswith("tv")
            }}))
            write_settings_local(current)
            publish_settings()
            body = dict(SETTINGS_STATE)
        self.send_json(200, body)

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
        if path == "/radar.png":
            self.serve_radar()
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
    publish_settings()
    publish_data()

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
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            if thread.name == "slate-discovery":
                thread.join(timeout=1)


if __name__ == "__main__":
    main()
