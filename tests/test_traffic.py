#!/usr/bin/env python3
"""Traffic region and cache checks. No live network."""

import sys
import unittest
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


class TrafficRegionTests(unittest.TestCase):
    def setUp(self):
        self._saved_cache = server.TRAFFIC_CACHE
        server.TRAFFIC_CACHE = {}

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
