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
- **Settings:** home apps, appearance, location, PIN, calendar connect, and optional credit link.

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

**Settings → Appearance** offers **Sculptural Light** (deep ink and luminous forms), **Aqua** (flowing ribbons), and **Flurry** (colored light streaks around a bright core). All three show on Home for the TV, Mac, and phone. The TV keeps its frame. Aqua and Flurry on the TV use a six-app dock. The Mac keeps the fluid grid. The phone keeps the stacked layout. Still, Drift, and Reactive stay, with Soft, Balanced, and Vivid intensity and a live thumbnail. Drift and Reactive lean the background as focus or the pointer moves, and a press flashes briefly. Still and reduced motion stop that. Select weather on Home to open the forecast page.

## TV (optional)

A separate Android TV WebView app can show Slate as Home. If the server is unreachable, wake the host and run `python3 server.py --lan`, then retry from the TV.

**Screensaver:** the TV app can register a Slate dream that shows clock, weather, and the next **Busy** calendar line. Choose it once in Android screensaver settings, or run:

```bash
adb shell settings put secure screensaver_components dev.slate.home/.SlateDream
```

Install and verify the TV app on your own network.

## Wi‑Fi session

With `--lan`, unlocking **Show all** sets a cookie on that device. **Settings → Sign out on Wi‑Fi** clears it so the PIN is asked again.
