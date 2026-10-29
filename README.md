# Slate (TV dashboard)

A local dashboard for Mac and iPad: clock, New York weather, schedule, home tiles, and settings. Plain HTML, CSS, and JavaScript. No build step and no accounts.

## Run

On this Mac only:

```bash
python3 server.py
```

Open http://127.0.0.1:8000.

On an iPhone or iPad on the same Wi-Fi (do not forward port 8000 on the router):

```bash
python3 server.py --lan
```

The terminal prints the Wi-Fi address, for example `http://the-host:8000`.

On Wi-Fi, use **Settings → Sign out on Wi-Fi** to clear the unlock cookie so Dashboard **Show all** asks for the PIN again.

Leave this Mac awake while you use Slate. If it sleeps, the page stops.

## What you get (v1: tablet and Mac)

- **Home:** minute clock, weather, Dashboard plus selected apps from the catalog. Tiles auto-fit the screen; TV Settings can choose Auto fit or Large tiles.
- **Tiles:** on Mac and iPad, streaming links open in a **new browser tab** so Home stays open. In the TV WebView, supported apps launch natively; if one is unavailable, choose its web version or return to Home. Dashboard opens in the same tab.
- **Settings** (footer link): pick home apps, appearance, location, and read **Schedule** setup notes. **Hide mouse pointer** keeps the cursor off even when the mouse moves. By default the browser may share your location for weather and the clock time zone (Open-Meteo, no key). **Lock location** in Settings → Location to keep a fixed place. TV Home uses the configured location without waiting for device geolocation. Home apps and appearance save to `settings.local.json`. Google Calendar credentials stay in Keychain on this Mac. Both files stay on this Mac and are gitignored where noted.
- **Time and weather** are live: the clock updates every minute; weather refreshes about every 10 minutes. Arrow keys on Home move focus in all four directions (tiles and Settings).
- **Dashboard:** guest mode by default; **Now / Next** and **Upcoming** from Google Calendar. **G** or **Show all** for real titles. On Wi-Fi, that needs the PIN once per session. On this Mac (`127.0.0.1`), no PIN. Open **calendar** for Today, Week, and Month views. Esc or Backspace goes Home.
- **Weather:** select weather on Home to open seven days, hourly detail, a today rain chart, and recent NOAA radar (served by this Mac).

Older manual schedule data may remain in `data.local.json` (gitignored backup). The server still publishes guest `data.json` for that file. Do not commit `data.json`, `settings.local.json`, `calendar-cache.local.json`, or `pin.local`.

The PIN over http is a convenience lock, not security.

## Calendar setup

Create a private Google Calendar for Slate. On this Mac, add `calendarId` to `settings.local.json` and store OAuth values in Keychain (service **Slate Calendar**, accounts `client-id`, `client-secret`, `refresh-token`). **Settings → Schedule** explains the steps. Dashboard and calendar views refresh about every two minutes. Guest mode shows **Busy**; **Show all** reveals titles after the PIN on Wi-Fi.

## TV appearance

**Settings → Appearance** offers **Sculptural Light** (deep ink, luminous forms, clock, forecast, and app grid) and **Aqua** (ribbons and a glass dock of six apps). Still, Drift, and Reactive motion stay, with Soft, Balanced, and Vivid intensity and a live thumbnail. Reactive focus pulls the background. A selection flashes briefly. Reduced motion stops the decoration. Select weather on Home to open the forecast page. Mac and iPad keep their layout.

## TV and server recovery

The TCL 55Q51K runs Slate in the separate WebView home app. If the server cannot be reached, wake the Mac and run `python3 server.py --lan`, then click Retry or press a remote button. Retry checks the saved address and searches the local network if the Mac's address changed.

The WebView app's Home-routing helper returns Home to Slate while leaving Google TV available through its tile. **Settings → TV Home button** can turn routing off or open Android Accessibility settings. The helper observes app-window changes without reading screen contents. The stock launcher may still show sponsored content when opened deliberately.

While away from the TV's Wi-Fi, use `http://127.0.0.1:8000` on the Mac. Its old LAN address cannot follow the Mac between networks.

Scene buttons and Home Assistant stay out until Alex says go.

The Dashboard’s **Wi-Fi / LAN** page shows Slate server and internet status and can scan the Mac’s current private Wi-Fi subnet on request. Devices that block ping may not appear.
