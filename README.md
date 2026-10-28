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

- **Home:** minute clock, weather, Dashboard plus up to five app tiles, footer **Settings**.
- **Tiles:** streaming links open in a **new browser tab** so Home stays open. Dashboard opens in the same tab.
- **Settings** (footer link): pick home apps, theme, location, and **schedule**. **Hide mouse pointer** keeps the cursor off even when the mouse moves. By default the browser may share your location for weather and the clock time zone (Open-Meteo, no key). **Lock location** in Settings → Location to keep a fixed place. Home apps, theme, and the pointer choice save to `settings.local.json`. Schedule saves to `data.local.json`. Both files stay on this Mac and are gitignored.
- **Time and weather** are live: the clock updates every minute; weather refreshes about every 10 minutes. Arrow keys on Home move focus in all four directions (tiles and Settings).
- **Dashboard:** guest mode by default; **G** or **Show all** for Deadlines and Money. On Wi-Fi, the schedule needs the PIN once per session. On this Mac (`127.0.0.1`), no PIN. Esc or Backspace goes Home.

Private schedule data lives in `data.local.json` (gitignored). The server publishes a guest `data.json` (Busy titles). Do not commit `data.json`, `settings.local.json`, or `pin.local`.

The PIN over http is a convenience lock, not security.

## Later

TV frame (1920 couch layout), remote keys, and native app launch wait until a TV or box is chosen. Scene buttons and Home Assistant stay out until Alex says go.
