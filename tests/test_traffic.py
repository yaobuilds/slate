#!/usr/bin/env python3
"""Traffic region and cache checks. No live network."""

import http.client
import io
import json
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import isolate  # noqa: E402
import server  # noqa: E402

# Pin, settings, and keys stay out of this checkout.
isolate.install(server)

NY_LAT = 40.7128
NY_LON = -74.0060
DC_LAT = 38.9072
DC_LON = -77.0369
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class JsonResponse:
    """A small urlopen result. The body is a string the test controls."""

    def __init__(self, text, content_type="application/json"):
        self._body = text.encode("utf-8")
        self.headers = self
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type

    def read(self, _limit):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def chart_body(name, now):
    """Fixture JSON with relative ages turned into epoch milliseconds."""
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    for row in payload["data"]:
        slot = row.pop("_age", None)
        if slot == "now":
            row["startDateTime"] = int(now.timestamp() * 1000)
        elif slot == "old":
            row["startDateTime"] = int((now - timedelta(hours=37)).timestamp() * 1000)
        elif slot == "closure-old":
            row["startDateTime"] = int((now - timedelta(days=10)).timestamp() * 1000)
            row["lastCachedDataUpdateTime"] = int((now - timedelta(hours=48)).timestamp() * 1000)
    return json.dumps(payload)


def tomtom_body(now=None):
    """Fixture JSON with NOW markers turned into a current UTC timestamp."""
    payload = json.loads((FIXTURES / "tomtom_incidents.json").read_text(encoding="utf-8"))
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for feature in payload["incidents"]:
        props = feature.get("properties") or {}
        if props.get("startTime") == "NOW":
            props["startTime"] = stamp
    return json.dumps(payload)


def tomtom_point_body(lat, lon, road="I-75", now=None):
    """One Incident Details point at the coordinates this test asks for."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "incidents": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": "cell-1",
                "startTime": stamp,
                "roadNumbers": [road],
                "events": [{"description": "Slow traffic"}],
            },
        }]
    }
    return json.dumps(payload)


def move_north(lat, lon, km):
    """A latitude that is about km north of lat. The distance uses the server's own formula."""
    step = km / 110.574
    for _ in range(8):
        dist = server.haversine_km(lat, lon, lat + step, lon)
        if dist <= 0:
            break
        step = step * (km / dist)
    return lat + step


def incident_row(road, when, lat, lon, feed):
    return {
        "road": road,
        "description": "Crash",
        "time": when.isoformat(),
        "lat": lat,
        "lon": lon,
        "feed": feed,
    }


class TrafficRegionTests(unittest.TestCase):
    def setUp(self):
        self._saved_cache = server.TRAFFIC_CACHE
        server.TRAFFIC_CACHE = {}
        self._saved_tomtom_env = os.environ.pop("SLATE_TOMTOM_KEY", None)
        self._saved_quota = (server.TOMTOM_QUOTA["day"], server.TOMTOM_QUOTA["count"])
        self._saved_pause = server.TOMTOM_PAUSE["until"]
        self._saved_log = server.TOMTOM_LOG["at"]
        self._saved_caption = (server.TOMTOM_CAPTION["at"], server.TOMTOM_CAPTION["text"])
        server.TOMTOM_QUOTA["day"] = ""
        server.TOMTOM_QUOTA["count"] = 0
        server.TOMTOM_PAUSE["until"] = 0.0
        server.TOMTOM_LOG["at"] = 0.0
        server.TOMTOM_CAPTION["at"] = 0.0
        server.TOMTOM_CAPTION["text"] = ""
        checkout_key = (server.ROOT / "tomtom.local").resolve()
        if server.TOMTOM_KEY_PATH.resolve() != checkout_key:
            server.TOMTOM_KEY_PATH.unlink(missing_ok=True)
        # CHART and TomTom must not open a socket from these tests.
        self._urlopen = mock.patch.object(
            server, "urlopen", side_effect=urllib.error.URLError("blocked")
        )
        self.urlopen_mock = self._urlopen.start()

    def tearDown(self):
        self._urlopen.stop()
        server.TRAFFIC_CACHE = self._saved_cache
        server.TOMTOM_QUOTA["day"], server.TOMTOM_QUOTA["count"] = self._saved_quota
        server.TOMTOM_PAUSE["until"] = self._saved_pause
        server.TOMTOM_LOG["at"] = self._saved_log
        server.TOMTOM_CAPTION["at"], server.TOMTOM_CAPTION["text"] = self._saved_caption
        if self._saved_tomtom_env is None:
            os.environ.pop("SLATE_TOMTOM_KEY", None)
        else:
            os.environ["SLATE_TOMTOM_KEY"] = self._saved_tomtom_env
        checkout_key = (server.ROOT / "tomtom.local").resolve()
        if server.TOMTOM_KEY_PATH.resolve() != checkout_key:
            server.TOMTOM_KEY_PATH.unlink(missing_ok=True)

    def test_region_for_new_york(self):
        self.assertEqual(server.region_for(NY_LAT, NY_LON), "ny")
        self.assertEqual(server.region_for(40.74, -74.17), "ny")
        self.assertEqual(server.region_for(40.48, -74.00), "grid:40.0,-74.0")

    def test_region_for_dmv_cities(self):
        self.assertEqual(server.region_for(DC_LAT, DC_LON), "dmv")
        self.assertEqual(server.region_for(38.9847, -77.0947), "dmv")
        self.assertEqual(server.region_for(38.8816, -77.0910), "dmv")

    def test_region_for_box_edges(self):
        self.assertEqual(server.region_for(38.60, -77.60), "dmv")
        self.assertEqual(server.region_for(39.35, -76.70), "dmv")
        self.assertEqual(server.region_for(38.59, -77.00), "grid:38.5,-77.0")
        self.assertEqual(server.region_for(39.36, -77.00), "grid:39.0,-77.0")
        self.assertEqual(server.region_for("nope", DC_LON), "ny")
        self.assertEqual(server.region_for(True, DC_LON), "ny")
        self.assertEqual(server.region_for(float("nan"), DC_LON), "ny")

    def test_region_for_other_us_cities(self):
        self.assertEqual(server.region_for(33.749, -84.388), "grid:33.5,-84.5")
        self.assertEqual(server.region_for(33.60, -84.10), "grid:33.5,-84.5")
        self.assertEqual(server.region_for(33.60, -84.00), "grid:33.5,-84.0")
        self.assertEqual(server.region_for(41.8781, -87.6298), "grid:41.5,-88.0")
        self.assertEqual(server.region_for(34.0522, -118.2437), "grid:34.0,-118.5")

    def test_dmv_does_not_touch_ny_cache(self):
        stamp = 50.0
        rows = [{"road": "NY", "description": "kept", "time": "t", "lat": NY_LAT, "lon": NY_LON}]
        server.TRAFFIC_CACHE = {
            "ny": {"parts": {"ny": {"at": stamp, "rows": rows, "feed": "511ny-json"}}},
        }
        got = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertEqual(got, ([], False, ""))
        part = server.TRAFFIC_CACHE["ny"]["parts"]["ny"]
        self.assertEqual(part["at"], stamp)
        self.assertIs(part["rows"], rows)
        self.assertNotIn("dmv", server.TRAFFIC_CACHE)

    def test_ny_filters_unchanged(self):
        now = datetime.now(timezone.utc)
        fresh = {
            "road": "FDR",
            "description": "Crash",
            "time": now.isoformat(),
            "lat": NY_LAT,
            "lon": NY_LON,
        }
        old = {
            "road": "Old",
            "description": "Stale",
            "time": (now - timedelta(hours=37)).isoformat(),
            "lat": NY_LAT,
            "lon": NY_LON,
        }
        far = {
            "road": "Far",
            "description": "Away",
            "time": now.isoformat(),
            "lat": NY_LAT + 2.0,
            "lon": NY_LON,
        }
        missing_time = {
            "road": "Blank",
            "description": "No time",
            "time": "",
            "lat": NY_LAT,
            "lon": NY_LON,
        }
        with mock.patch.object(
            server,
            "load_ny_incidents",
            return_value=([fresh, old, far, missing_time], "511ny-json"),
        ) as loader:
            rows, available, feed = server.traffic_incidents_for(NY_LAT, NY_LON)
        loader.assert_called_once()
        self.assertTrue(available)
        self.assertEqual(feed, "511ny-json")
        self.assertEqual([row["road"] for row in rows], ["FDR"])
        self.assertNotIn("feed", rows[0])
        self.assertGreater(server.haversine_km(NY_LAT, NY_LON, far["lat"], far["lon"]), 160)

    def test_ny_failure_keeps_part(self):
        stamp = 1000.0
        now = datetime.now(timezone.utc)
        row = {
            "road": "Kept",
            "description": "Still here",
            "time": now.isoformat(),
            "lat": NY_LAT,
            "lon": NY_LON,
        }
        rows = [row]
        server.TRAFFIC_CACHE = {
            "ny": {"parts": {"ny": {"at": stamp, "rows": rows, "feed": "511ny-json"}}},
        }
        with mock.patch.object(server, "load_ny_incidents", return_value=([], "")) as loader:
            with mock.patch.object(server.time, "monotonic", return_value=stamp + server.TRAFFIC_CACHE_TTL + 5):
                got_rows, available, feed = server.traffic_incidents_for(NY_LAT, NY_LON)
        loader.assert_called_once()
        part = server.TRAFFIC_CACHE["ny"]["parts"]["ny"]
        self.assertEqual(part["at"], stamp)
        self.assertIs(part["rows"], rows)
        self.assertEqual(part["feed"], "511ny-json")
        self.assertTrue(available)
        self.assertEqual(feed, "511ny-json")
        self.assertEqual([item["road"] for item in got_rows], ["Kept"])
        self.assertNotIn("dmv", server.TRAFFIC_CACHE)

    def test_chart_parses_events_and_closures(self):
        now = datetime.now(timezone.utc)
        events = chart_body("chart_events.json", now)
        closures = chart_body("chart_closures.json", now)

        def fake_open(request, timeout=8):
            if request.full_url == server.CHART_EVENTS_URL:
                return JsonResponse(events)
            if request.full_url == server.CHART_CLOSURES_URL:
                return JsonResponse(closures)
            raise urllib.error.URLError("unexpected")

        with mock.patch.object(server, "urlopen", fake_open):
            rows, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
            payload = server.traffic_payload((DC_LAT, DC_LON))
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual(
            [row["road"] for row in rows],
            ["I-95 OUTER LOOP", "Local Name Without Marker", "I-495"],
        )
        self.assertEqual(rows[0]["description"], "Crash Right lane blocked")
        self.assertEqual(rows[1]["description"], "Disabled vehicle Shoulder")
        self.assertEqual(rows[2]["description"], "Closure Two lanes closed")
        self.assertNotIn("ignore", rows[2]["description"])
        for row in rows:
            self.assertEqual(row["feed"], "md-chart")
            self.assertNotIn("closure", row)
            self.assertNotIn("_id", row)
        cached = server.TRAFFIC_CACHE["dmv"]["parts"]["chart-events"]["rows"]
        cached_roads = [row["road"] for row in cached]
        self.assertIn("OLD EVENT", cached_roads)
        self.assertNotIn("SIGNAL RD", cached_roads)
        self.assertNotIn("CLOSED RD", cached_roads)
        self.assertNotIn("OUTSIDE RD", cached_roads)
        self.assertEqual(payload["feed"], "dmv")
        self.assertEqual(payload["sources"], ["md-chart"])
        self.assertNotIn("tomtom", payload)
        self.assertTrue(payload["incidentsAvailable"])

    def test_chart_failure_keeps_part(self):
        stamp = 1000.0
        now = datetime.now(timezone.utc)
        row = {
            "road": "Kept",
            "description": "Still here",
            "time": now.isoformat(),
            "lat": DC_LAT,
            "lon": DC_LON,
            "feed": "md-chart",
        }
        rows = [row]
        server.TRAFFIC_CACHE = {
            "dmv": {"parts": {"chart-events": {"at": stamp, "rows": rows, "feed": "md-chart"}}},
        }
        with mock.patch.object(server.time, "monotonic", return_value=stamp + server.CHART_CACHE_TTL + 5):
            got, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        part = server.TRAFFIC_CACHE["dmv"]["parts"]["chart-events"]
        self.assertEqual(part["at"], stamp)
        self.assertIs(part["rows"], rows)
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual([item["road"] for item in got], ["Kept"])
        self.assertNotIn("chart-closures", server.TRAFFIC_CACHE["dmv"]["parts"])

    def test_chart_bad_json_is_failure(self):
        stamp = 1000.0
        now = datetime.now(timezone.utc)
        rows = [{
            "road": "Kept",
            "description": "Still here",
            "time": now.isoformat(),
            "lat": DC_LAT,
            "lon": DC_LON,
            "feed": "md-chart",
        }]
        server.TRAFFIC_CACHE = {
            "dmv": {"parts": {"chart-events": {"at": stamp, "rows": rows, "feed": "md-chart"}}},
        }

        def fake_open(request, timeout=8):
            return JsonResponse('{"success": false, "data": []}')

        with mock.patch.object(server.time, "monotonic", return_value=stamp + server.CHART_CACHE_TTL + 5):
            with mock.patch.object(server, "urlopen", fake_open):
                server.traffic_incidents_for(DC_LAT, DC_LON)
        part = server.TRAFFIC_CACHE["dmv"]["parts"]["chart-events"]
        self.assertEqual(part["at"], stamp)
        self.assertIs(part["rows"], rows)
        self.assertNotEqual(part["rows"], [])

    def test_chart_empty_success_is_cached(self):
        calls = []

        def fake_open(request, timeout=8):
            calls.append(request.full_url)
            return JsonResponse('{"success": true, "data": []}')

        with mock.patch.object(server, "urlopen", fake_open):
            first = server.traffic_incidents_for(DC_LAT, DC_LON)
            second = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertEqual(first, ([], True, "dmv"))
        self.assertEqual(second, ([], True, "dmv"))
        self.assertEqual(len(calls), 2)
        for name in ("chart-events", "chart-closures"):
            part = server.TRAFFIC_CACHE["dmv"]["parts"][name]
            self.assertEqual(part["feed"], "md-chart")
            self.assertEqual(part["rows"], [])

    def test_chart_one_endpoint_can_fail(self):
        now = datetime.now(timezone.utc)
        closure = {
            "success": True,
            "data": [{
                "id": 7,
                "type": 1,
                "description": "Closure on the beltway",
                "name": "I-495",
                "incidentType": "Closure",
                "lanesClosed": "Two lanes closed",
                "lat": 38.95,
                "lon": -77.1,
                "startDateTime": int((now - timedelta(days=10)).timestamp() * 1000),
                "lastCachedDataUpdateTime": int((now - timedelta(hours=48)).timestamp() * 1000),
            }],
        }

        def fake_open(request, timeout=8):
            if request.full_url == server.CHART_EVENTS_URL:
                raise urllib.error.URLError("down")
            return JsonResponse(json.dumps(closure))

        with mock.patch.object(server, "urlopen", fake_open):
            rows, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual([row["road"] for row in rows], ["I-495"])
        self.assertNotIn("chart-events", server.TRAFFIC_CACHE["dmv"]["parts"])
        self.assertEqual(
            server.TRAFFIC_CACHE["dmv"]["parts"]["chart-closures"]["feed"],
            "md-chart",
        )

    def test_chart_ranks_events_and_closures(self):
        now = datetime.now(timezone.utc)
        events = []
        for index in range(10):
            events.append({
                "road": f"E{index}",
                "description": "d",
                "time": (now - timedelta(hours=index)).isoformat(),
                "lat": DC_LAT,
                "lon": DC_LON,
                "feed": "md-chart",
            })
        closures = [{
            "road": "C",
            "description": "d",
            "time": (now - timedelta(minutes=15)).isoformat(),
            "lat": DC_LAT,
            "lon": DC_LON,
            "feed": "md-chart",
            "closure": True,
        }]
        stamp = 5000.0
        server.TRAFFIC_CACHE = {
            "dmv": {"parts": {
                "chart-events": {"at": stamp, "rows": events, "feed": "md-chart"},
                "chart-closures": {"at": stamp, "rows": closures, "feed": "md-chart"},
            }},
        }
        with mock.patch.object(server.time, "monotonic", return_value=stamp + 1):
            rows, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual(
            [row["road"] for row in rows],
            ["E0", "C", "E1", "E2", "E3", "E4", "E5", "E6"],
        )
        self.assertNotIn("closure", rows[1])
        self.assertEqual(self.urlopen_mock.call_count, 0)

    def test_chart_time_and_clip(self):
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
        future_ms = int((now + timedelta(minutes=30)).timestamp() * 1000)
        future = server.normalize_chart_item({
            "type": 1,
            "description": "Incident @ I-95 AT EXIT 1",
            "name": "Name",
            "lat": 38.9,
            "lon": -77.0,
            "startDateTime": start_ms,
            "lastCachedDataUpdateTime": future_ms,
            "incidentType": "Work",
            "lanesClosed": "Shoulder",
        }, True)
        self.assertEqual(future["time"], server.chart_epoch_iso(start_ms))
        long_row = server.normalize_chart_item({
            "type": 1,
            "description": "Incident @ " + ("R" * 200) + " AT END",
            "name": "Name",
            "lat": 38.9,
            "lon": -77.0,
            "startDateTime": start_ms,
            "incidentType": "Crash",
            "lanesStatus": "x" * 400,
        }, False)
        self.assertLessEqual(len(long_row["road"]), 120)
        self.assertLessEqual(len(long_row["description"]), 220)
        self.assertTrue(long_row["description"].startswith("Crash "))

    def test_chart_road_cuts_between(self):
        road = server.chart_road(
            "Planned Closure @ MD 191 EAST/WEST BETWEEN HOWELL RD AND MAPLE",
            "Fallback Name",
        )
        self.assertEqual(road, "MD 191 EAST/WEST")
        plain = server.chart_road("Closure @ US 1", "Fallback Name")
        self.assertEqual(plain, "US 1")
        named = server.chart_road("Closure on the beltway", "I-495")
        self.assertEqual(named, "I-495")

    def test_tomtom_maps_point_and_line(self):
        now = datetime.now(timezone.utc)
        payload = json.loads(tomtom_body(now))
        point = server.normalize_tomtom_incident(payload["incidents"][0])
        line = server.normalize_tomtom_incident(payload["incidents"][1])
        self.assertEqual(point["lon"], -77.05)
        self.assertEqual(point["lat"], 38.9)
        self.assertEqual(point["road"], "US-50")
        self.assertEqual(point["description"], "Slow traffic")
        self.assertEqual(point["feed"], "tomtom")
        self.assertNotIn("id", point)
        self.assertEqual(line["lon"], -77.1)
        self.assertEqual(line["lat"], 38.9)
        self.assertEqual(line["road"], "Cedar Avenue")
        self.assertEqual(line["description"], "Roadworks; Lane closed")
        self.assertEqual(line["feed"], "tomtom")
        parsed = server.parse_tomtom_body(tomtom_body(now), "application/json")
        self.assertEqual([row["road"] for row in parsed], ["US-50", "Cedar Avenue"])
        shifted = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-77.04, 38.92], [-80.0, 30.0], [-79.0, 31.0]],
            },
            "properties": {
                "startTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "from": "Oak Lane",
                "events": [{"description": "Crash"}],
            },
        }
        moved = server.normalize_tomtom_incident(shifted)
        self.assertEqual(moved["lat"], 38.92)
        self.assertEqual(moved["lon"], -77.04)
        outside = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-80.0, 30.0], [-79.0, 31.0]]},
            "properties": {
                "startTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "from": "Far Road",
                "events": [{"description": "Crash"}],
            },
        }
        self.assertIsNone(server.normalize_tomtom_incident(outside))

    def test_tomtom_drops_row_without_start(self):
        payload = json.loads(tomtom_body())
        feature = payload["incidents"][0]
        feature["properties"].pop("startTime")
        self.assertIsNone(server.normalize_tomtom_incident(feature))

    def test_near_duplicate_keeps_chart(self):
        now = datetime.now(timezone.utc)
        chart = incident_row("I-95", now, DC_LAT, DC_LON, "md-chart")
        chart["_id"] = "c1"
        tom_lat = move_north(DC_LAT, DC_LON, 0.20)
        dist = server.haversine_km(DC_LAT, DC_LON, tom_lat, DC_LON)
        self.assertGreater(dist, 0.15)
        self.assertLessEqual(dist, 0.40)
        tom = incident_row("I 95", now - timedelta(minutes=10), tom_lat, DC_LON, "tomtom")
        merged = server.merge_dmv_incidents([chart], [], [tom])
        self.assertEqual([row["feed"] for row in merged], ["md-chart"])
        self.assertEqual(merged[0]["road"], "I-95")
        other = incident_row("Georgia Ave", now, move_north(DC_LAT, DC_LON, 0.10), DC_LON, "md-chart")
        other["_id"] = "c2"
        both = server.merge_dmv_incidents([chart, other], [], [])
        self.assertEqual([row["road"] for row in both], ["I-95", "Georgia Ave"])

    def test_near_duplicate_keeps_both_when_time_or_road_differs(self):
        now = datetime.now(timezone.utc)
        chart = incident_row("I-95", now, DC_LAT, DC_LON, "md-chart")
        far_time = incident_row(
            "I 95",
            now - timedelta(hours=2),
            move_north(DC_LAT, DC_LON, 0.20),
            DC_LON,
            "tomtom",
        )
        kept = server.merge_dmv_incidents([chart], [], [far_time])
        self.assertEqual([row["feed"] for row in kept], ["md-chart", "tomtom"])
        unrelated = incident_row(
            "Cedar Avenue",
            now - timedelta(minutes=5),
            move_north(DC_LAT, DC_LON, 0.30),
            DC_LON,
            "tomtom",
        )
        dist = server.haversine_km(DC_LAT, DC_LON, unrelated["lat"], DC_LON)
        self.assertGreater(dist, 0.15)
        self.assertLessEqual(dist, 0.40)
        both = server.merge_dmv_incidents([chart], [], [unrelated])
        self.assertEqual([row["feed"] for row in both], ["md-chart", "tomtom"])
        close = incident_row(
            "Maple Street",
            now - timedelta(minutes=5),
            move_north(DC_LAT, DC_LON, 0.10),
            DC_LON,
            "tomtom",
        )
        close_dist = server.haversine_km(DC_LAT, DC_LON, close["lat"], DC_LON)
        self.assertLessEqual(close_dist, 0.15)
        dropped = server.merge_dmv_incidents([chart], [], [close])
        self.assertEqual([row["feed"] for row in dropped], ["md-chart"])

    def test_tomtom_skipped_without_key(self):
        now = datetime.now(timezone.utc)
        events = {
            "success": True,
            "data": [{
                "id": 1,
                "type": 1,
                "description": "Incident @ Georgia Ave AT PINE",
                "name": "Georgia Ave",
                "incidentType": "Crash",
                "lanesStatus": "Right lane",
                "lat": DC_LAT,
                "lon": DC_LON,
                "startDateTime": int(now.timestamp() * 1000),
            }],
        }
        seen = []

        def fake_open(request, timeout=8):
            seen.append(request.full_url)
            if request.full_url == server.CHART_EVENTS_URL:
                return JsonResponse(json.dumps(events))
            if request.full_url == server.CHART_CLOSURES_URL:
                return JsonResponse('{"success": true, "data": []}')
            raise urllib.error.URLError("unexpected")

        with mock.patch.object(server, "urlopen", fake_open):
            rows, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual([row["road"] for row in rows], ["Georgia Ave"])
        self.assertTrue(seen)
        self.assertFalse(any("api.tomtom.com" in url for url in seen))

    def test_tomtom_env_overrides_file(self):
        env_key = "SLATEKEYENV1234"
        file_key = "SLATEKEYFILE1234"
        os.environ["SLATE_TOMTOM_KEY"] = env_key
        server.TOMTOM_KEY_PATH.write_text(file_key + "\n", encoding="utf-8")
        seen = []

        def fake_open(request, timeout=8):
            url = request.full_url
            seen.append(url)
            if "incidentDetails" in url or "caption.json" in url:
                if "incidentDetails" in url:
                    return JsonResponse(tomtom_body())
                return JsonResponse('{"copyrightsCaption":"©TomTom"}')
            if url in (server.CHART_EVENTS_URL, server.CHART_CLOSURES_URL):
                return JsonResponse('{"success": true, "data": []}')
            raise urllib.error.URLError("unexpected")

        notes = io.StringIO()
        with mock.patch.object(server.sys, "stderr", notes):
            with mock.patch.object(server, "urlopen", fake_open):
                payload = server.traffic_payload((DC_LAT, DC_LON))
        incident_urls = [url for url in seen if "incidentDetails" in url]
        self.assertEqual(len(incident_urls), 1)
        query = parse_qs(urlsplit(incident_urls[0]).query)
        self.assertEqual(query["key"], [env_key])
        self.assertNotIn("t", query)
        self.assertEqual(query["bbox"], ["-77.60,38.60,-76.70,39.35"])
        self.assertEqual(query["language"], ["en-US"])
        self.assertEqual(query["timeValidityFilter"], ["present"])
        self.assertIn("roadNumbers", query["fields"][0])
        self.assertNotIn(file_key, incident_urls[0])
        body = json.dumps(payload)
        logged = notes.getvalue()
        self.assertNotIn(env_key, body)
        self.assertNotIn(file_key, body)
        self.assertNotIn(env_key, logged)
        self.assertNotIn(file_key, logged)
        self.assertEqual(payload["sources"], ["tomtom"])
        self.assertEqual(payload["tomtomCredit"], "©TomTom")
        for row in payload["incidents"]:
            self.assertNotIn("id", row)

    def test_tomtom_not_refetched_inside_ttl(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        calls = []

        def fake_open(request, timeout=8):
            url = request.full_url
            if "incidentDetails" in url:
                calls.append("incident")
                return JsonResponse(tomtom_body())
            if url in (server.CHART_EVENTS_URL, server.CHART_CLOSURES_URL):
                return JsonResponse('{"success": true, "data": []}')
            raise urllib.error.URLError("unexpected")

        with mock.patch.object(server, "urlopen", fake_open):
            first, first_ok, _feed = server.traffic_incidents_for(DC_LAT, DC_LON)
            second, second_ok, _feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertEqual(calls, ["incident"])
        self.assertTrue(first_ok and second_ok)
        self.assertEqual([row["road"] for row in first], ["US-50", "Cedar Avenue"])
        self.assertEqual([row["road"] for row in second], [row["road"] for row in first])

    def test_tomtom_daily_cap(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        calls = []

        def fake_open(request, timeout=8):
            url = request.full_url
            if "incidentDetails" in url:
                calls.append("incident")
                return JsonResponse(tomtom_body())
            if "caption.json" in url:
                calls.append("caption")
                return JsonResponse('{"copyrightsCaption":"©TomTom"}')
            if url in (server.CHART_EVENTS_URL, server.CHART_CLOSURES_URL):
                calls.append("chart")
                return JsonResponse('{"success": true, "data": []}')
            raise urllib.error.URLError("unexpected")

        base = 10000.0
        step = server.TOMTOM_CACHE_TTL + 1
        with mock.patch.object(server, "tomtom_utc_day", return_value="2026-11-05"):
            with mock.patch.object(server, "urlopen", fake_open):
                for index in range(server.TOMTOM_DAILY_CAP):
                    moment = base + index * step
                    with mock.patch.object(server.time, "monotonic", return_value=moment):
                        server.ensure_tomtom_part(moment)
                self.assertEqual(calls, ["incident"] * server.TOMTOM_DAILY_CAP)
                last = base + (server.TOMTOM_DAILY_CAP - 1) * step
                within = last + step
                with server.TRAFFIC_LOCK:
                    server.store_traffic_part("dmv", "chart-events", [], "md-chart", within)
                    server.store_traffic_part("dmv", "chart-closures", [], "md-chart", within)
                server.TOMTOM_CAPTION["at"] = within
                server.TOMTOM_CAPTION["text"] = "©TomTom"
                with mock.patch.object(server.time, "monotonic", return_value=within):
                    payload = server.traffic_payload((DC_LAT, DC_LON))
                self.assertEqual(calls, ["incident"] * server.TOMTOM_DAILY_CAP)
                self.assertIn("tomtom", payload["sources"])
                self.assertTrue(any(row["feed"] == "tomtom" for row in payload["incidents"]))
                later = last + server.TOMTOM_GRACE_S + 5
                with server.TRAFFIC_LOCK:
                    server.store_traffic_part("dmv", "chart-events", [], "md-chart", later)
                    server.store_traffic_part("dmv", "chart-closures", [], "md-chart", later)
                with mock.patch.object(server.time, "monotonic", return_value=later):
                    expired = server.traffic_payload((DC_LAT, DC_LON))
                self.assertEqual(calls, ["incident"] * server.TOMTOM_DAILY_CAP)
                self.assertNotIn("tomtom", expired.get("sources", []))
                self.assertEqual(expired["segments"], [])
                self.assertEqual(expired["tomtomCredit"], "©TomTom")
                self.assertTrue(expired["flowReady"])
                self.assertFalse(any(row.get("feed") == "tomtom" for row in expired["incidents"]))

    def test_tomtom_failure_keeps_part(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        stamp = 1000.0
        now = datetime.now(timezone.utc)
        row = incident_row("Kept", now, DC_LAT, DC_LON, "tomtom")
        rows = [row]
        server.TRAFFIC_CACHE = {
            "dmv": {"parts": {"tomtom": {"at": stamp, "rows": rows, "feed": "tomtom"}}},
        }

        def fake_open(request, timeout=8):
            raise socket.timeout("timed out")

        with mock.patch.object(server.time, "monotonic", return_value=stamp + server.TOMTOM_CACHE_TTL + 5):
            with mock.patch.object(server, "urlopen", fake_open):
                got, available, feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        part = server.TRAFFIC_CACHE["dmv"]["parts"]["tomtom"]
        self.assertEqual(part["at"], stamp)
        self.assertIs(part["rows"], rows)
        self.assertTrue(available)
        self.assertEqual(feed, "dmv")
        self.assertEqual([item["road"] for item in got], ["Kept"])
        self.assertEqual(server.TOMTOM_QUOTA["count"], 1)

    def test_tomtom_pause_on_429(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        stamp = 2000.0
        now = datetime.now(timezone.utc)
        row = incident_row("Kept", now, DC_LAT, DC_LON, "tomtom")
        server.TRAFFIC_CACHE = {
            "dmv": {"parts": {"tomtom": {"at": stamp, "rows": [row], "feed": "tomtom"}}},
        }
        incident_calls = []

        def fake_open(request, timeout=8):
            url = request.full_url
            if "incidentDetails" in url:
                incident_calls.append("incident")
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

        moment = stamp + server.TOMTOM_CACHE_TTL + 5
        with mock.patch.object(server.time, "monotonic", return_value=moment):
            with mock.patch.object(server, "urlopen", fake_open):
                server.traffic_incidents_for(DC_LAT, DC_LON)
        part = server.TRAFFIC_CACHE["dmv"]["parts"]["tomtom"]
        self.assertEqual(part["at"], stamp)
        self.assertEqual(incident_calls, ["incident"])
        self.assertGreaterEqual(server.TOMTOM_PAUSE["until"], moment + server.TOMTOM_PAUSE_S)
        later = moment + 10
        with mock.patch.object(server.time, "monotonic", return_value=later):
            with mock.patch.object(server, "urlopen", fake_open):
                got, available, _feed = server.traffic_incidents_for(DC_LAT, DC_LON)
        self.assertEqual(incident_calls, ["incident"])
        self.assertTrue(available)
        self.assertEqual([item["road"] for item in got], ["Kept"])

    def test_grid_without_key_does_not_call(self):
        self.assertNotIn("SLATE_TOMTOM_KEY", os.environ)
        rows, available, feed = server.traffic_incidents_for(33.749, -84.388)
        self.assertEqual((rows, available, feed), ([], False, ""))
        self.urlopen_mock.assert_not_called()
        payload = server.traffic_payload((33.749, -84.388))
        self.assertFalse(payload["incidentsAvailable"])
        self.assertNotIn("sources", payload)
        self.assertNotIn("tomtomCredit", payload)
        self.assertNotIn("feed", payload)

    def test_grid_cell_is_cached_and_isolated(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        calls = []

        def fake_open(request, timeout=8):
            url = request.full_url
            if "incidentDetails" in url:
                bbox = parse_qs(urlsplit(url).query)["bbox"][0]
                calls.append(bbox)
                west, south, east, north = [float(part) for part in bbox.split(",")]
                return JsonResponse(tomtom_point_body((south + north) / 2, (west + east) / 2))
            if "caption.json" in url:
                return JsonResponse('{"copyrightsCaption":"©TomTom"}')
            raise urllib.error.URLError("unexpected")

        with mock.patch.object(server, "urlopen", fake_open):
            first, ok1, feed1 = server.traffic_incidents_for(33.749, -84.388)
            second, ok2, feed2 = server.traffic_incidents_for(33.60, -84.10)
            third, ok3, feed3 = server.traffic_incidents_for(33.60, -84.00)
            payload = server.traffic_payload((33.749, -84.388))
        self.assertEqual(calls, ["-84.5,33.5,-84.0,34.0", "-84.0,33.5,-83.5,34.0"])
        self.assertNotIn("33.749", "".join(calls))
        self.assertTrue(ok1 and ok2 and ok3)
        self.assertEqual(feed1, "grid:33.5,-84.5")
        self.assertEqual(feed2, feed1)
        self.assertEqual(feed3, "grid:33.5,-84.0")
        self.assertEqual(first[0]["road"], "I-75")
        self.assertEqual(first[0]["feed"], "tomtom")
        self.assertEqual(second[0]["road"], "I-75")
        self.assertEqual(third[0]["road"], "I-75")
        self.assertEqual(set(server.TRAFFIC_CACHE), {"grid:33.5,-84.5", "grid:33.5,-84.0"})
        self.assertNotIn("dmv", server.TRAFFIC_CACHE)
        self.assertEqual(payload["sources"], ["tomtom"])
        self.assertEqual(payload["tomtomCredit"], "©TomTom")
        self.assertEqual(payload["feed"], "grid:33.5,-84.5")
        self.assertNotIn("SLATEKEYENV1234", json.dumps(payload))

    def test_grid_drops_points_outside_the_cell(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        seen = []

        def fake_open(request, timeout=8):
            url = request.full_url
            seen.append(url)
            if "incidentDetails" in url:
                return JsonResponse(tomtom_body())
            raise urllib.error.URLError("unexpected")

        with mock.patch.object(server, "urlopen", fake_open):
            payload = server.traffic_payload((33.749, -84.388))
        self.assertEqual(payload["incidents"], [])
        self.assertTrue(payload["incidentsAvailable"])
        self.assertEqual(payload["feed"], "grid:33.5,-84.5")
        self.assertNotIn("sources", payload)
        self.assertEqual(payload["segments"], [])
        self.assertTrue(payload["flowReady"])
        self.assertEqual(payload["tomtomCredit"], server.TOMTOM_CREDIT_FALLBACK)
        self.assertNotIn("SLATEKEYENV1234", json.dumps(payload))

    def test_grid_shares_the_daily_cap(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        calls = []

        def fake_open(request, timeout=8):
            url = request.full_url
            if "incidentDetails" in url:
                calls.append(parse_qs(urlsplit(url).query)["bbox"][0])
                return JsonResponse(tomtom_body())
            if url in (server.CHART_EVENTS_URL, server.CHART_CLOSURES_URL):
                return JsonResponse('{"success": true, "data": []}')
            raise urllib.error.URLError("unexpected")

        moment = 50000.0
        with mock.patch.object(server, "tomtom_utc_day", return_value="2026-11-05"):
            with mock.patch.object(server, "urlopen", fake_open):
                with mock.patch.object(server.time, "monotonic", return_value=moment):
                    server.traffic_incidents_for(33.749, -84.388)
                    server.traffic_incidents_for(DC_LAT, DC_LON)
                self.assertEqual(server.TOMTOM_QUOTA["count"], 2)
                self.assertEqual(calls, ["-84.5,33.5,-84.0,34.0", "-77.60,38.60,-76.70,39.35"])
                server.TOMTOM_QUOTA["count"] = server.TOMTOM_DAILY_CAP
                blocked = moment + server.TOMTOM_CACHE_TTL + 5
                with mock.patch.object(server.time, "monotonic", return_value=blocked):
                    rows, available, feed = server.traffic_incidents_for(34.0522, -118.2437)
                self.assertEqual(calls, ["-84.5,33.5,-84.0,34.0", "-77.60,38.60,-76.70,39.35"])
                self.assertEqual((rows, available, feed), ([], False, ""))


class TrafficDocsTests(unittest.TestCase):
    def test_readme_links_the_city_guide(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide_path = ROOT / "docs" / "add-your-city.md"
        guide = guide_path.read_text(encoding="utf-8")
        self.assertTrue(guide_path.is_file())
        self.assertIn("docs/add-your-city.md", readme)
        self.assertIn("`tomtom.local`", readme)
        self.assertIn("grid:33.5,-84.5", guide)
        self.assertIn("flow tile", readme.lower())
        self.assertIn("flow tile", guide.lower())
        self.assertNotIn("Queens", readme)
        self.assertNotIn("Queens", guide)


PNG = b"\x89PNG\r\n\x1a\nflow"


class FlowTileTests(unittest.TestCase):
    def setUp(self):
        self._saved_cache = dict(server.FLOW_TILE_CACHE)
        self._saved_quota = (server.FLOW_QUOTA["day"], server.FLOW_QUOTA["count"])
        self._saved_pause = server.FLOW_PAUSE["until"]
        self._saved_incidents = (server.TOMTOM_QUOTA["day"], server.TOMTOM_QUOTA["count"])
        self._saved_caption = (server.TOMTOM_CAPTION["at"], server.TOMTOM_CAPTION["text"])
        self._saved_tomtom_env = os.environ.pop("SLATE_TOMTOM_KEY", None)
        server.FLOW_TILE_CACHE.clear()
        server.FLOW_QUOTA["day"] = ""
        server.FLOW_QUOTA["count"] = 0
        server.FLOW_PAUSE["until"] = 0.0
        server.TOMTOM_CAPTION["at"] = 0.0
        server.TOMTOM_CAPTION["text"] = ""
        self.logs = []
        self._log = server.Handler.log_message

        def capture(handler, fmt, *args):
            self.logs.append(fmt % args)

        server.Handler.log_message = capture
        self.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.Handler.log_message = self._log
        server.FLOW_TILE_CACHE.clear()
        server.FLOW_TILE_CACHE.update(self._saved_cache)
        server.FLOW_QUOTA["day"], server.FLOW_QUOTA["count"] = self._saved_quota
        server.FLOW_PAUSE["until"] = self._saved_pause
        server.TOMTOM_QUOTA["day"], server.TOMTOM_QUOTA["count"] = self._saved_incidents
        server.TOMTOM_CAPTION["at"], server.TOMTOM_CAPTION["text"] = self._saved_caption
        if self._saved_tomtom_env is None:
            os.environ.pop("SLATE_TOMTOM_KEY", None)
        else:
            os.environ["SLATE_TOMTOM_KEY"] = self._saved_tomtom_env

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.getheaders()}
        finally:
            conn.close()

    def test_flow_ready_follows_the_key(self):
        with mock.patch.object(server, "slate_settings_place", return_value=None):
            quiet = server.traffic_payload()
        self.assertFalse(quiet["flowReady"])
        self.assertNotIn("tomtomCredit", quiet)
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        with mock.patch.object(server, "slate_settings_place", return_value=None):
            ready = server.traffic_payload()
        self.assertTrue(ready["flowReady"])
        self.assertNotIn("tomtomCredit", ready)

    def test_flow_credit_when_speed_lines_are_absent(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        server.TOMTOM_CAPTION["at"] = time.monotonic()
        server.TOMTOM_CAPTION["text"] = "©TomTom"
        with mock.patch.object(server, "traffic_incidents_for", return_value=([], False, "")):
            payload = server.traffic_payload((DC_LAT, DC_LON))
        self.assertTrue(payload["flowReady"])
        self.assertEqual(payload["segments"], [])
        self.assertEqual(payload["tomtomCredit"], "©TomTom")
        segment = {"level": "red", "points": [[40.75, -73.99], [40.76, -73.98]]}
        with mock.patch.object(server, "traffic_incidents_for", return_value=([], False, "")):
            with mock.patch.object(server, "traffic_speed_segments_for", return_value=([segment], True, True)):
                city = server.traffic_payload((NY_LAT, NY_LON))
        self.assertTrue(city["flowReady"])
        self.assertEqual(city["segments"], [segment])
        self.assertNotIn("tomtomCredit", city)
        self.assertNotIn("sources", city)

    def test_flow_tile_proxies_without_leaking_the_key(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        seen = []

        class Resp:
            def __init__(self, url):
                self._url = url

            def geturl(self):
                return self._url

            def read(self, _limit):
                return PNG

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_open(request, timeout=8):
            seen.append((request.full_url, timeout))
            return Resp(request.full_url)

        with mock.patch.object(server, "tomtom_utc_day", return_value="2026-11-05"):
            with mock.patch.object(server, "urlopen", fake_open):
                status, body, headers = self._get("/flow/12/1171/1566.png?b=1")
                again, again_body, _headers = self._get("/flow/12/1171/1566.png?b=1")
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(again, 200)
        self.assertEqual(again_body, PNG)
        self.assertEqual(headers["content-type"], "image/png")
        self.assertEqual(headers["cache-control"], "private, max-age=180")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], 8)
        url = seen[0][0]
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["key"], ["SLATEKEYENV1234"])
        self.assertEqual(query["tileSize"], ["256"])
        self.assertIn("/flow/relative0-dark/12/1171/1566.png", url)
        self.assertEqual(urlsplit(url).hostname, "api.tomtom.com")
        self.assertNotIn(b"SLATEKEYENV1234", body)
        self.assertNotIn("SLATEKEYENV1234", " ".join(self.logs))
        self.assertEqual(server.FLOW_QUOTA["count"], 1)
        self.assertEqual(server.TOMTOM_QUOTA["count"], self._saved_incidents[1])

    def test_flow_tile_needs_a_key_and_a_real_tile(self):
        status, body, _headers = self._get("/flow/12/1/2.png")
        self.assertEqual(status, 503)
        self.assertIn("key", body.decode())
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        with mock.patch.object(server, "urlopen", side_effect=urllib.error.URLError("blocked")):
            missing, payload, _headers = self._get("/flow/21/0/0.png")
            wide, _wide_body, _headers = self._get("/flow/12/4096/0.png")
            failed, failed_body, _headers = self._get("/flow/12/1/2.png")
        self.assertEqual(missing, 404)
        self.assertEqual(wide, 404)
        self.assertEqual(failed, 502)
        self.assertIn("tile", failed_body.decode())
        self.assertNotIn("SLATEKEYENV1234", failed_body.decode())
        self.assertNotIn("SLATEKEYENV1234", payload.decode())
        self.assertFalse(any("api.tomtom.com" in line for line in self.logs))

        class Foreign:
            def geturl(self):
                return "https://evil.example/tile.png"

            def read(self, _limit):
                return PNG

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with mock.patch.object(server, "urlopen", lambda request, timeout=8: Foreign()):
            foreign, foreign_body, _headers = self._get("/flow/12/8/8.png")
        self.assertEqual(foreign, 502)
        self.assertNotIn(b"SLATEKEYENV1234", foreign_body)
        self.assertNotIn((12, 8, 8), server.FLOW_TILE_CACHE)

    def test_flow_tile_cache_cap_and_pause(self):
        os.environ["SLATE_TOMTOM_KEY"] = "SLATEKEYENV1234"
        calls = []

        class Resp:
            def __init__(self, url):
                self._url = url

            def geturl(self):
                return self._url

            def read(self, _limit):
                return PNG

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_open(request, timeout=8):
            calls.append(request.full_url)
            if len(calls) == 2:
                raise urllib.error.HTTPError(
                    "https://api.tomtom.com/traffic/map/4/tile/flow/paused.png",
                    429,
                    "Too Many Requests",
                    None,
                    None,
                )
            return Resp(request.full_url)

        moment = 8000.0
        with mock.patch.object(server, "tomtom_utc_day", return_value="2026-11-05"):
            with mock.patch.object(server, "urlopen", fake_open):
                with mock.patch.object(server.time, "monotonic", return_value=moment):
                    status, body, _headers = self._get("/flow/12/3/4.png")
                self.assertEqual(status, 200)
                self.assertEqual(body, PNG)
                self.assertEqual(len(calls), 1)
                stale = moment + server.FLOW_TILE_TTL + 1
                with mock.patch.object(server.time, "monotonic", return_value=stale):
                    paused, paused_body, _headers = self._get("/flow/12/3/4.png")
                self.assertEqual(paused, 200)
                self.assertEqual(paused_body, PNG)
                self.assertEqual(server.FLOW_TILE_CACHE[(12, 3, 4)][0], moment)
                self.assertGreaterEqual(server.FLOW_PAUSE["until"], stale + server.TOMTOM_PAUSE_S)
                with mock.patch.object(server.time, "monotonic", return_value=stale + 10):
                    held, held_body, _headers = self._get("/flow/12/3/4.png")
                self.assertEqual(held, 200)
                self.assertEqual(held_body, PNG)
                self.assertEqual(len(calls), 2)
                server.FLOW_PAUSE["until"] = 0.0
                server.FLOW_QUOTA["count"] = server.FLOW_DAILY_CAP
                server.FLOW_QUOTA["day"] = "2026-11-05"
                within = moment + 1000
                with mock.patch.object(server.time, "monotonic", return_value=within):
                    capped, capped_body, _headers = self._get("/flow/12/3/4.png")
                    other, other_body, _headers = self._get("/flow/12/9/9.png")
                self.assertEqual(capped, 200)
                self.assertEqual(capped_body, PNG)
                self.assertEqual(other, 502)
                self.assertEqual(len(calls), 2)
                expired = moment + server.TOMTOM_GRACE_S + 5
                with mock.patch.object(server.time, "monotonic", return_value=expired):
                    dropped, _dropped_body, _headers = self._get("/flow/12/3/4.png")
                self.assertEqual(dropped, 502)
                self.assertEqual(len(calls), 2)
                self.assertIn((12, 3, 4), server.FLOW_TILE_CACHE)
                self.assertEqual(server.TOMTOM_QUOTA["count"], self._saved_incidents[1])

    def test_flow_layer_follows_the_street_tiles(self):
        html = (ROOT / "traffic.html").read_text(encoding="utf-8")
        css = (ROOT / "traffic.css").read_text(encoding="utf-8")
        script = (ROOT / "traffic.js").read_text(encoding="utf-8")
        self.assertLess(html.index('id="traffic-tiles"'), html.index('id="traffic-flow"'))
        self.assertLess(html.index('id="traffic-flow"'), html.index('id="traffic-center"'))
        self.assertLess(html.index('id="traffic-flow"'), html.index('id="traffic-markers"'))
        self.assertLess(html.index('id="traffic-flow"'), html.index('id="traffic-speeds"'))
        self.assertIn(".traffic-flow", css)
        self.assertIn("/flow/${zoom}/${x}/${y}.png?b=${bucket}", script)
        self.assertIn("240000", script)
        self.assertIn("flowReady", script)


if __name__ == "__main__":
    unittest.main()
