#!/usr/bin/env python3
"""Traffic region and cache checks. No live network."""

import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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


class TrafficRegionTests(unittest.TestCase):
    def setUp(self):
        self._saved_cache = server.TRAFFIC_CACHE
        server.TRAFFIC_CACHE = {}
        # CHART must not open a socket from these tests.
        self._urlopen = mock.patch.object(
            server, "urlopen", side_effect=urllib.error.URLError("blocked")
        )
        self.urlopen_mock = self._urlopen.start()

    def tearDown(self):
        self._urlopen.stop()
        server.TRAFFIC_CACHE = self._saved_cache

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


if __name__ == "__main__":
    unittest.main()
