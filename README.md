# Slate

A local dashboard for a computer, phone, tablet, or TV: clock, weather, calendar, app tiles, and settings. Plain HTML, CSS, and JavaScript. Python serves the files. No build step and no dependencies.

Setup is on this page. [How it is built](docs/ARCHITECTURE.md) and [security notes](docs/SECURITY.md) are in `docs/`.

<!-- SCREENSHOT: add docs/screenshot-home.png here after Alex approves it -->

## What you need

- Python 3.9 or newer. The server uses the standard library only.
- A computer that stays awake while Slate is open. If it sleeps, the page stops.
- The same Wi-Fi as the phone or TV, if you want those screens. Do not forward port 8000 on the router.

Calendar connect stores its secrets in the macOS Keychain, so that step is for a Mac host. Clock, weather, apps, and settings run on any computer with Python 3.9.

## Set it up

```bash
git clone https://github.com/yaobuilds/tv-dashboard.git
cd tv-dashboard
python3 server.py
```

Open http://127.0.0.1:8000.

The first start creates the local files that are not in the repository:

- `pin.local` — a new 6-digit PIN, printed once in the terminal. Change it in Settings.
- `settings.local.json` — Home apps from `apps.json`, the default place, and appearance.
- `data.local.json` — an example schedule. Guest pages show Busy in place of those titles.
- `gallery.local/` — an empty folder for photos.
- `data.json` — the guest copy of the schedule, rewritten on each start.

Files that already exist are left as they are. Delete `pin.local` and start again to print a new PIN.

The default place is New York, NY. Change it in **Settings → Location**. Until you lock the location, the browser may share its place for weather and the clock time zone. On the computer running Slate, the Wi-Fi address continues at 127.0.0.1 so that browser can read location. A phone stays on the Wi-Fi address.

## Phone, tablet, or TV on the same Wi-Fi

```bash
python3 server.py --lan
```

The terminal prints an address such as `http://<host>:8000`. Open that address on the other device. Same Wi-Fi only. Do not forward port 8000.

On the host (`127.0.0.1`) the schedule does not ask for a PIN. On the Wi-Fi address, **Show all** on Dashboard or Calendar asks for the PIN in `pin.local` once per device. **Settings → Sign out on Wi-Fi** clears that device so the PIN is asked again. A private browser window also starts without the saved session.

The PIN over HTTP is a convenience lock, not strong security.

## Pages

- **Home:** clock, weather, Dashboard, and the apps you pick.
- **Dashboard:** guest mode on every load. **Now / Next** and **Upcoming** come from Google Calendar when it is connected. **G** or **Show all** reveals real titles.
- **Calendar:** Today, Week, and Month from the same calendar.
- **Weather:** seven days, hourly detail, a today rain chart, and recent radar fetched by the server. Radar plays from oldest to newest, then repeats. Weather uses [Open-Meteo](https://open-meteo.com/) and needs no key.
- **Traffic:** a street map centered on this device’s location, or the saved place when that location is locked or the screen is the TV. Street tiles need the free key in the next section. Nearby incidents appear when a public feed covers that area.
- **Gallery:** photos you upload. They stay in `gallery.local/`.
- **Keel:** the reading page.
- **Wi-Fi / LAN:** devices seen from the host, linked from the Dashboard footer.
- **Settings:** home apps, appearance, location, news sources, PIN, calendar, the Wi-Fi remote, and the optional credit link.

## Traffic map

Street tiles come from [CARTO](https://carto.com/attributions). Request a free key at [carto.com/basemaps/apikey](https://carto.com/basemaps/apikey/). No account is required. Save the key as the only line of `carto.local` and start Slate again:

```bash
umask 077
printf '%s\n' 'paste-the-key-here' > carto.local
python3 server.py
```

You can set `SLATE_CARTO_KEY` instead of the file. The key stays on this computer. The page asks Slate for tiles, so the key is not sent to the browser. Without a key, the page still centers on the detected place. The streets stay blank until the key is there.

## Wi-Fi remote

With `python3 server.py --lan`, open **Settings → TV remote** on the host, or `http://<host>:8000/remote.html` on a phone. Do not open the remote page on the TV.

1. **Pair the phone.** Generate a six-digit code on the host and enter it on the phone.
2. **Pair the TV.** Tap **Show code on TV**. The TV shows a six-character code. Enter that code on the phone or in Settings.

Until the TV code is accepted, arrow keys from the phone move focus inside Slate. Volume waits for TV pairing. After pairing, keys go to whatever app is on the Google TV screen. `atv.local` is written on the host when a TV is paired. **Wi-Fi remote enabled** in Settings turns the broker off without deleting that file.

## Calendar (optional)

On the Mac that hosts Slate, open **Settings → Calendar**. Create a Google Cloud **Desktop** or **Web** OAuth client with this redirect URI:

`http://127.0.0.1:8000/oauth/callback`

Enable the Google Calendar API. Enter the client id and secret in Settings, connect with Google, and choose the calendar. The client id, client secret, and refresh token stay in the macOS Keychain under the service **Slate Calendar**. They are not written into this folder.

Dashboard and Calendar refresh about every two minutes. Edit events in Google Calendar.

## Home appearance

Choose **Sculptural Light**, **Aqua**, or **Flurry** in **Settings → Appearance**. The look changes the Home backdrop. Panels, text, and the focus ring stay the shared Slate palette.

- **Sculptural Light:** soft light forms. Nine ambient choices, including still versions and Off.
- **Aqua:** flowing ribbons. **Tide** is the default.
- **Flurry:** colored streaks around a soft core. **Spectrum** is the default.

**Save and open Home** stores the choice. Motion is **Still**, **Drift**, or **Reactive**. Intensity is **Soft**, **Balanced**, or **Vivid**. Still and reduced motion stop the decorative movement.

Aqua and Flurry use a six-app dock on a TV. A computer and a phone keep their own layouts.

## TV app (optional)

A separate project, `tv-control`, is an Android TV app that can show this server as the TV home screen. Wake the host, run `python3 server.py --lan`, and open the printed address from the TV. Install and check that app on your own network.

The screensaver can show the clock, weather, and the next **Busy** calendar line. Private titles stay hidden. After the app is installed:

```bash
adb shell settings put secure screensaver_components dev.slate.home/.SlateDream
```

## Files you do not commit

| File | Purpose |
|------|---------|
| `settings.local.json` | Home apps, appearance, location, toggles |
| `pin.local` | Wi-Fi unlock PIN (mode 600) |
| `carto.local` | Free CARTO key for traffic street tiles |
| `data.local.json` | Schedule kept on this computer |
| `calendar-cache.local.json` | Last good Google Calendar fetch |
| `data.json` | Generated guest copy of the schedule |
| `atv.local` | TV remote certificate, created when a TV is paired |
| `gallery.local/` | Uploaded photos |

If you forget the PIN, delete `pin.local` and start Slate again. The new PIN is printed once. You can also set a different one in Settings.

## Run the tests

```bash
python3 -m unittest discover -s tests
```

The tests use only the standard library. Some page tests drive Chrome when it is installed. The gallery tests expect no `gallery.local/` folder, so run them on a fresh checkout.

## License

[MIT](LICENSE).
