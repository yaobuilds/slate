"""Browser regressions for calendar layout, Home navigation, and saver motion.

The local fixture serves sample settings and calendar entries without reading or
writing the host's private settings, PIN, calendar cache, or app selection.
"""

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from test_fix import Cdp, chrome_bin, wait_until


class ThemeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary = chrome_bin()
        if not binary:
            raise unittest.SkipTest("Chrome is not installed")

        class FixtureHandler(server.Handler):
            def do_GET(self):
                path = server.public_path(self.path)
                fixture = self.server.fixture
                if path == "/settings.json":
                    self.send_json(200, fixture["settings"])
                elif path == "/apps.json":
                    self.send_json(200, [{"id": value} for value in fixture["settings"]["homeApps"]])
                elif path == "/ambient.json":
                    self.send_json(200, json.loads(server.AMBIENT.read_text()))
                elif path == "/calendar.json":
                    now = datetime.now(timezone.utc)
                    payload = {
                        "configured": True, "stale": False, "syncedAt": now.isoformat(),
                        "events": [{
                            "id": "sample", "title": "Private sample appointment",
                            "start": (now + timedelta(hours=1)).isoformat(),
                            "end": (now + timedelta(hours=2)).isoformat(), "allDay": False,
                        }],
                    }
                    self.send_json(200, payload if self.headers.get("X-Slate-Full") == "1" else server.guest_calendar(payload))
                elif path == "/headlines.json":
                    self.send_json(200, {"updated": "", "items": [{
                        "title": "Sample headline", "source": "Sample", "url": "https://example.org/",
                    }] * (4 if fixture["news"] else 0)})
                else:
                    super().do_GET()

            def log_message(self, *_args):
                pass

        cls.httpd = server.Server(("127.0.0.1", 0), FixtureHandler)
        cls.httpd.require_pin = False
        cls.httpd.lan_enabled = False
        cls.httpd.fixture = {}
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.profile = tempfile.TemporaryDirectory(prefix="slate-theme-browser-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.chrome = subprocess.Popen([
            binary, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
            f"--remote-debugging-port={port}", f"--user-data-dir={cls.profile.name}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for attempt in range(60):
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
                    with urllib.request.urlopen(req, timeout=1) as response:
                        page = json.load(response)
                    break
                except OSError:
                    if attempt == 59:
                        raise
                    time.sleep(0.1)
            cls.cdp = Cdp(page["webSocketDebuggerUrl"])
            cls.cdp.send("Page.enable")
            cls.cdp.send("Network.enable")
            cls.cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            cls.cdp.send("Network.setBlockedURLs", {"urls": ["*open-meteo.com*"]})
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "cdp"):
            cls.cdp.sock.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
            cls.chrome.wait(timeout=5)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.profile.cleanup()

    def setUp(self):
        self.httpd.fixture.update({
            "news": True,
            "settings": {
                "homeApps": ["netflix", "hulu", "hbo", "youtube", "youtube-music"],
                "location": dict(server.DEFAULT_LOCATION, locked=True), "ambientPreset": "aurora",
                "tvAppearance": "sculptural", "tvMotion": "drift", "tvIntensity": "balanced",
                "tvAquaPalette": "tide", "tvFlurryPalette": "spectrum", "remoteEnabled": False,
            },
        })
        self.cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]})

    def surface(self, width, height, tv=False):
        self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 2 if tv else 1, "mobile": False,
        })
        self.cdp.send("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 Android TV" if tv else "Mozilla/5.0 Chrome/130.0.0.0 Safari/537.36"})

    def open(self, page, ready):
        self.cdp.send("Page.navigate", {"url": self.base + "/" + page})
        wait_until(self.cdp, "document.readyState === 'complete' && (" + ready + ")")
        self.cdp.eval("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))")

    def test_calendar_panels_and_news_keep_their_grid(self):
        for width, height, tv in [(960, 540, True), (1366, 768, False)]:
            self.surface(width, height, tv)
            for news in [True, False]:
                with self.subTest(tv=tv, news=news):
                    self.httpd.fixture["news"] = news
                    self.open("dashboard.html", "document.querySelector('#today-list li') && document.getElementById('headlines').hidden === " + str(not news).lower())
                    result = self.cdp.eval("""(() => {
                      const box = s => document.querySelector(s).getBoundingClientRect().toJSON();
                      return { today: box('#panel-today'), upcoming: box('#panel-upcoming'),
                        news: box('#headlines'), foot: box('.dash-foot'), stage: box('.stage'),
                        columns: getComputedStyle(document.querySelector('.stage')).gridTemplateColumns,
                        panelPadding: getComputedStyle(document.querySelector('.panel')).paddingLeft,
                        dateWrap: getComputedStyle(document.querySelector('.dash-date')).whiteSpace,
                        guest: document.body.classList.contains('guest') };
                    })()""")
                    self.assertTrue(result["guest"])
                    self.assertEqual(len(result["columns"].split()), 2, result)
                    self.assertGreater(result["today"]["width"], width * 0.35, result)
                    self.assertAlmostEqual(result["today"]["top"], result["upcoming"]["top"], delta=1)
                    if news:
                        self.assertGreaterEqual(result["news"]["top"], result["today"]["bottom"])
                        self.assertGreaterEqual(result["foot"]["top"], result["news"]["bottom"])
                    if tv:
                        self.assertLessEqual(result["foot"]["bottom"], height - 20, result)
                    else:
                        self.assertEqual(result["stage"]["width"], width)
                        self.assertEqual(result["panelPadding"], "40px")
                        self.assertEqual(result["dateWrap"], "normal")
                    self.cdp.eval("document.getElementById('guest-toggle').click()")
                    wait_until(self.cdp, "!document.body.classList.contains('guest') && document.getElementById('today-list').textContent.includes('Private sample appointment')")
                    self.assertIn("Private sample appointment", self.cdp.eval("document.getElementById('today-list').textContent"))

    def test_home_links_prompt_and_supported_hdmi_choices(self):
        cases = [(w, h, look) for w, h in [(960, 540), (1280, 720), (1920, 1080)] for look in ["aqua", "flurry"]]
        for width, height, look in cases:
            self.surface(width, height, True)
            with self.subTest(look=look, width=width):
                self.httpd.fixture["settings"].update(tvAppearance=look, tvMotion="still")
                self.open("index.html", "document.querySelectorAll('#tiles .tile').length === 6")
                result = self.cdp.eval("""(() => ({
                  animation: getComputedStyle(document.body).animationName,
                  links: [...document.querySelectorAll('.foot-link, .signature')].map(e => ({
                    text: e.textContent.trim(), ...e.getBoundingClientRect().toJSON()
                  }))
                }))()""")
                self.assertEqual(result["animation"], "none")
                for i, a in enumerate(result["links"]):
                    self.assertGreaterEqual(a["left"], width * 0.05 - 1)
                    self.assertLessEqual(a["right"], width * 0.95 + 1)
                    self.assertGreaterEqual(a["top"], height * 0.05 - 1)
                    self.assertLessEqual(a["bottom"], height * 0.95 + 1)
                    for b in result["links"][i + 1:]:
                        overlap = min(a["right"], b["right"]) > max(a["left"], b["left"]) and min(a["bottom"], b["bottom"]) > max(a["top"], b["top"])
                        self.assertFalse(overlap, (a, b))
                self.cdp.eval("document.querySelector('.home-tools a').focus()")
                self.assertEqual(self.cdp.eval("document.activeElement.textContent"), "Keel")

        self.surface(960, 540, True)
        self.httpd.fixture["settings"]["homeApps"] += ["disney-plus", "prime-video"]
        self.open("index.html", "document.querySelectorAll('#tiles .tile').length === 8")
        self.cdp.eval("document.querySelectorAll('#tiles .tile')[5].focus()")
        self.cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39})
        self.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39})
        wait_until(self.cdp, "document.activeElement === document.querySelectorAll('#tiles .tile')[6] && !document.activeElement.hidden")
        self.assertEqual(self.cdp.eval("document.getElementById('dock-pagination').textContent"), "2 / 2")

        self.httpd.fixture["settings"]["homeApps"] = ["netflix", "hulu", "hbo", "youtube", "youtube-music"]
        self.surface(1366, 768)
        self.open("index.html", "document.querySelectorAll('#tiles .tile').length === 6")
        result = self.cdp.eval("""(() => {
          showPlacePrompt('Sample place', {lat: 42, lon: -71});
          const bar = document.getElementById('place-prompt');
          const before = document.documentElement.scrollHeight;
          const box = bar.getBoundingClientRect().toJSON();
          document.getElementById('place-prompt-later').click();
          return { box, position: getComputedStyle(bar).position, hidden: getComputedStyle(bar).display === 'none',
            scrollBefore: before, scrollAfter: document.documentElement.scrollHeight };
        })()""")
        self.assertEqual(result["position"], "fixed")
        self.assertGreater(result["box"]["top"], 0)
        self.assertLessEqual(result["box"]["bottom"], 768)
        self.assertTrue(result["hidden"])
        self.assertEqual(result["scrollBefore"], result["scrollAfter"])
        self.open("settings-apps.html", "document.getElementById('hdmi-input')")
        self.assertEqual(self.cdp.eval("[...document.getElementById('hdmi-input').options].map(e => e.value)"), ["1", "2", "3"])

        self.surface(390, 844)
        self.open("index.html", "document.querySelectorAll('#tiles .tile').length === 6")
        links = self.cdp.eval("[...document.querySelectorAll('.foot-link, .signature')].map(e => e.getBoundingClientRect().toJSON())")
        for link in links:
            self.assertGreaterEqual(link["left"], 0)
            self.assertLessEqual(link["right"], 390)

    def test_saver_motion_preferences_and_lifecycle(self):
        self.surface(1366, 768)
        for look in ["sculptural", "aqua", "flurry"]:
            for motion in ["still", "drift", "reactive"]:
                with self.subTest(look=look, motion=motion):
                    self.httpd.fixture["settings"].update(tvAppearance=look, tvMotion=motion)
                    self.open("screensaver.html", "document.querySelector('#tv-backdrop > :not(.look-grain)') && document.getElementById('saver-event').textContent.includes('Busy')")
                    animation = self.cdp.eval("getComputedStyle(document.querySelector('#tv-backdrop > :not(.look-grain)')).animationName")
                    self.assertEqual(animation, "none" if motion == "still" else "saver-drift")
                    self.assertNotIn("Private sample appointment", self.cdp.eval("document.body.textContent"))
                    self.cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
                    wait_until(self.cdp, "document.body.dataset.tvMotion === 'still'")
                    self.assertEqual(self.cdp.eval("getComputedStyle(document.querySelector('#tv-backdrop > :not(.look-grain)')).animationName"), "none")
                    self.assertEqual(self.cdp.eval("document.body.dataset.tvAppearance"), look)
                    self.cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]})
                    wait_until(self.cdp, "!matchMedia('(prefers-reduced-motion: reduce)').matches && document.body.dataset.tvMotion === " + json.dumps(motion))
                    if motion != "still":
                        paused = self.cdp.eval("window.dispatchEvent(new Event('blur')); getComputedStyle(document.querySelector('#tv-backdrop > :not(.look-grain)')).animationPlayState")
                        self.assertEqual(paused, "paused")
                    self.cdp.eval("window.dispatchEvent(new Event('focus'))")
                    self.cdp.eval("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true})); window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
                    wait_until(self.cdp, "!!document.querySelector('#tv-backdrop > :not(.look-grain)')")
                    self.assertEqual(self.cdp.eval("document.querySelectorAll('#tv-backdrop canvas').length"), 1 if look == "flurry" else 0)


if __name__ == "__main__":
    unittest.main()
