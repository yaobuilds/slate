#!/usr/bin/env python3
"""Traffic region and cache checks. No live network."""

import io
import json
import os
import socket
import sys
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

    def test_region_for_dmv_cities(self):
        self.assertEqual(server.region_for(DC_LAT, DC_LON), "dmv")
        self.assertEqual(server.region_for(38.9847, -77.0947), "dmv")
        self.assertEqual(server.region_for(38.8816, -77.0910), "dmv")

    def test_region_for_box_edges(self):
        self.assertEqual(server.region_for(38.60, -77.60), "dmv")
        self.assertEqual(server.region_for(39.35, -76.70), "dmv")
        self.assertEqual(server.region_for(38.59, -77.00), "ny")
        self.assertEqual(server.region_for(39.36, -77.00), "ny")
        self.assertEqual(server.region_for("nope", DC_LON), "ny")
        self.assertEqual(server.region_for(True, DC_LON), "ny")
        self.assertEqual(server.region_for(float("nan"), DC_LON), "ny")

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
            ["I-95 OUTER LOOP", "Georgia Ave", "I-495"],
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
                self.assertNotIn("tomtomCredit", expired)
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


if __name__ == "__main__":
    unittest.main()
