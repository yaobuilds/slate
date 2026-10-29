# Slate

A local dashboard for a Mac, tablet, or TV: clock, weather, calendar, app tiles, and settings. Plain HTML, CSS, and JavaScript. Python 3 serves the files. No build step.

## Run

On the computer that hosts Slate:

```bash
python3 server.py
```

Open http://127.0.0.1:8000.

To use a phone or tablet on the same Wi‑Fi (do not forward port 8000 on your router):

```bash
python3 server.py --lan
```

The terminal prints a local address you can open on other devices.

Leave the host computer awake while Slate is in use. If it sleeps, the page stops.

## What you get

- **Home:** clock, weather, Dashboard, and apps you pick from the catalog.
- **Dashboard:** guest mode by default. **Now / Next** and **Upcoming** come from Google Calendar when connected. **G** or **Show all** reveals real titles. On Wi‑Fi, that needs your PIN once per session. On the host (`127.0.0.1`), no PIN is required.
- **Calendar:** Today, Week, and Month views from the same Google Calendar feed.
- **Weather:** open weather from Home for seven days, hourly detail, a today rain chart, and recent radar (fetched by the server).
- **Traffic:** open **Traffic** from Home for a map centered on your saved place and nearby live incidents when a public feed covers that area.
- **Settings:** home apps, appearance, location, PIN, calendar connect, and optional credit link.

## Wi-Fi remote

With `python3 server.py --lan`, open **Settings → TV remote** or `http://<mac-ip>:8000/remote.html` on a phone (not on the TV itself).

1. **Pair the phone** — Generate a six-digit code on the Mac, enter it on the phone. That sets a session cookie for the remote API.
2. **Pair the TV** — Tap **Show code on TV**. The TV displays a six-character hex code (no physical remote). Enter that code on the phone or in Settings.

Until the TV code is accepted, arrow keys from the phone move focus inside Slate in the browser. Volume waits for TV pairing. After pairing, keys inject into whatever app is on screen on the Google TV. `index.html?remote=1` uses the Home screen as the remote and is hidden on the TV. Same Wi-Fi only; do not forward port 8000 on the router.

TV credentials live in `atv.local` on this Mac (gitignored). Turn the broker off with **Wi-Fi remote enabled** in Settings without erasing that file.

Weather uses [Open-Meteo](https://open-meteo.com/) (no API key). By default the browser may share location for weather and the clock time zone until you **lock location** in Settings → Location.

## Private files (never commit)

| File | Purpose |
|------|---------|
| `settings.local.json` | Home apps, appearance, location, toggles |
| `pin.local` | Wi‑Fi unlock PIN (mode 600) |
| `data.local.json` | Legacy manual schedule backup (optional) |
| `calendar-cache.local.json` | Last good Google Calendar fetch |
| `data.json` | Generated guest copy of manual schedule (if used) |

Google Calendar **client id**, **client secret**, and **refresh token** live in the macOS Keychain (service **Slate Calendar**), not in the repo. Set them up in **Settings → Calendar** on the host.

If you forget the PIN, edit or delete `pin.local` on the computer running Slate, then set a new PIN in Settings.

The PIN over HTTP is a convenience lock, not strong security.

## Calendar

Create a Google Calendar for Slate (or use an existing one). On the host, open **Settings → Calendar**, enter your OAuth client id and secret, connect with Google, and choose the calendar. Dashboard and calendar views refresh about every two minutes. Edit events in Google Calendar or any tool that writes to that calendar.

In Google Cloud, create a **Desktop** or **Web** OAuth client with redirect URI:

`http://127.0.0.1:8000/oauth/callback`

Enable the Google Calendar API for the project.

## Home appearance

**Settings → Appearance** offers **Sculptural Light** (deep ink and luminous forms), **Aqua** (flowing ribbons), and **Flurry** (colored light streaks around a bright core). Panels, text, and focus rings stay on the shared Slate palette on every page; only the decorative backdrop changes with the look. **Aqua** and **Flurry** each have six color sets (defaults **Tide** and **Spectrum**): Aqua — Tide, Glacier, Lagoon, Dusk, Moss, Ember; Flurry — Spectrum, Ice, Aurora, Ember, Lagoon, Bloom. Sculptural Light can follow any of nine ambient presets. All three show on Home for the TV, Mac, and phone. The TV keeps its frame. Aqua and Flurry on the TV use a six-app dock. The Mac keeps the fluid grid. The phone keeps the stacked layout. Still, Drift, and Reactive stay, with Soft, Balanced, and Vivid intensity and a live preview. Drift and Reactive lean the background as focus or the pointer moves, and a press flashes briefly. Still and reduced motion stop that. Select weather on Home to open the forecast page.

## TV (optional)

A separate Android TV WebView app can show Slate as Home. If the server is unreachable, wake the host and run `python3 server.py --lan`, then retry from the TV.

**Screensaver:** the TV app can register a Slate dream that shows clock, weather, and the next **Busy** calendar line. Choose it once in Android screensaver settings, or run:

```bash
adb shell settings put secure screensaver_components dev.slate.home/.SlateDream
```

Install and verify the TV app on your own network.

## Wi‑Fi session

With `--lan`, unlocking **Show all** sets a cookie on that device. **Settings → Sign out on Wi‑Fi** clears it so the PIN is asked again.
