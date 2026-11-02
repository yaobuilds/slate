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

The first start creates the local files that are not in the repository:

- `pin.local` — a new 6-digit PIN, printed once in the terminal. Change it in Settings.
- `settings.local.json` — Home apps from `apps.json`, the default place, and appearance.
- `data.local.json` — an example schedule. Guest pages show Busy in place of those titles.
- `gallery.local/` — an empty folder for photos.
- `data.json` — the guest copy of the schedule, rewritten on each start.

Files that already exist are left as they are. Delete `pin.local` and start again to print a new PIN. `atv.local` is written when a TV is paired. Google Calendar stays optional: the client id, secret, and refresh token go in the macOS Keychain from Settings → Calendar, not into a file in this folder.

Leave the host computer awake while Slate is in use. If it sleeps, the page stops.

## What you get

- **Home:** clock, weather, Dashboard, and apps you pick from the catalog.
- **Dashboard:** guest mode by default. **Now / Next** and **Upcoming** come from Google Calendar when connected. **G** or **Show all** reveals real titles. On Wi‑Fi, that needs your PIN once per session. On the host (`127.0.0.1`), no PIN is required.
- **Calendar:** Today, Week, and Month views from the same Google Calendar feed.
- **Weather:** open weather from Home for seven days, hourly detail, a today rain chart, and recent radar (fetched by the server). Radar playback runs from oldest to newest, then repeats.
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
| `data.json` | Generated guest copy of the schedule |
| `atv.local` | TV remote certificate, created when a TV is paired |
| `gallery.local/` | Photos uploaded from Settings |

Google Calendar **client id**, **client secret**, and **refresh token** live in the macOS Keychain (service **Slate Calendar**), not in the repo. Set them up in **Settings → Calendar** on the host.

If you forget the PIN, delete `pin.local` and start Slate again. The new PIN is printed once. You can also set a different PIN in Settings.

The PIN over HTTP is a convenience lock, not strong security.

## Calendar

Create a Google Calendar for Slate (or use an existing one). On the host, open **Settings → Calendar**, enter your OAuth client id and secret, connect with Google, and choose the calendar. Dashboard and calendar views refresh about every two minutes. Edit events in Google Calendar or any tool that writes to that calendar.

In Google Cloud, create a **Desktop** or **Web** OAuth client with redirect URI:

`http://127.0.0.1:8000/oauth/callback`

Enable the Google Calendar API for the project.

## Home appearance

Choose **Sculptural Light**, **Aqua**, or **Flurry** in **Settings → Appearance**. The look changes the decorative Home backdrop; panels, text, and focus rings keep the shared Slate palette.

- **Sculptural Light:** soft light forms colored by the ambient preset. There are nine ambient choices, including still versions and Off. Off uses the original Home colors while turning off Dashboard ambient light.
- **Aqua:** flowing ribbons. Colors: **Tide** (default), Glacier, Lagoon, Dusk, Moss, Ember.
- **Flurry:** colored streaks around a soft core. Colors: **Spectrum** (default), Ice, Aurora, Ember, Lagoon, Bloom.

The live preview updates before saving. Each look remembers its color choice. **Save and open Home** saves the choices and returns Home. Motion offers **Still**, **Drift**, and **Reactive**; intensity offers **Soft**, **Balanced**, and **Vivid**. Still and reduced motion stop decorative Home movement and press effects.

All three looks work on TV, Mac, and phone. Aqua and Flurry use a six-app paged dock on TV; Mac and phone keep responsive grids. Select weather on Home to open the forecast page.

## TV (optional)

A separate Android TV WebView app can show Slate as Home. If the server is unreachable, wake the host and run `python3 server.py --lan`, then retry from the TV.

**Screensaver:** the TV app can register a Slate dream that shows clock, weather, and the next **Busy** calendar line over a dim version of the selected Home look. Drift and Reactive move the backdrop slowly; Still and reduced motion keep it static. Private calendar titles stay hidden. Choose it once in Android screensaver settings, or run:

```bash
adb shell settings put secure screensaver_components dev.slate.home/.SlateDream
```

Install and verify the TV app on your own network.

## Wi‑Fi session

With `--lan`, unlocking **Show all** sets a cookie on that device. **Settings → Sign out on Wi‑Fi** clears it so the PIN is asked again.

To check the PIN prompt again, open the same Wi‑Fi address, sign out in Settings, then return to Dashboard or Calendar and choose **Show all**. A private browser window also starts without the saved session. The standard Mac-only server skips PIN checks, so clearing its cookies will not make it ask for a PIN; use the Wi‑Fi address printed by `--lan` for this check.
