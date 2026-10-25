# TV Dashboard

A 1920×1080 living-room screen. Plain HTML, CSS, and JavaScript. No build step and no accounts.

## Run

On this Mac only:

```bash
python3 server.py
```

Open http://127.0.0.1:8000.

On an iPhone, use the same Wi-Fi and do not forward port 8000 on the router:

```bash
python3 server.py --lan
```

The terminal prints the phone address. The shape is `http://<mac-ip>:8000`, for example `http://the-host:8000`. Dashboard is `http://<mac-ip>:8000/dashboard.html`.

Find the Mac's Wi-Fi address in System Settings → Network → Wi-Fi → Details, on the IP address line. Or in Terminal, `ipconfig getifaddr en0` (Wi-Fi is usually `en0`). If the printed address does not open on the phone, turn a VPN off and start the server again.

The phone can see the clock, the weather, and the app names without a PIN. The schedule asks for a PIN. The first time, the terminal prints that PIN and saves it in `pin.local` on this Mac. That file is not served and not committed. To choose the PIN yourself, set `SLATE_PIN` to 4–8 digits before you start the server. Five wrong PINs pause new tries for a minute. The session lasts at most 7 days. POST `/lock` on that same address forgets this phone until the PIN is entered again. The PIN over http is a convenience lock, not security. On the iPhone, open the address in Safari, tap Share, then Add to Home Screen. Leave the Mac awake. If it sleeps, the page stops. Deadlines and Money stay hidden until Show all. In guest mode the day says Busy, not the event title. Home does not show the schedule.

- Home is the clock, the New York weather, and the app tiles. The first tile is Dashboard. Arrow keys move between the tiles. Enter opens Dashboard. The other tiles do not open anything yet.
- The other tiles come from `apps.json`, at most five. Names and icons come from `apps-catalog.json`. To change a tile, use an id from the catalog. An entry can also set its own name, icon, or url.
- Dashboard is http://127.0.0.1:8000/dashboard.html on this Mac. It opens in guest mode, with Deadlines and Money empty. Press G to show them, or tap Show all on a phone or a Mac window. Press G again, or tap Guest mode, to clear them. After 30 minutes with no key press, they clear again. A tap on Show all counts the same as G. From midnight to 6 AM the screen dims to about 60% brightness. Esc or Backspace goes Home.
- Soft colored light moves behind both pages. It is a screen effect only. No real light and no Home Assistant is connected. Aurora is the default. The other choices live in `ambient.json` under `preset`: Ember, Lagoon, Bloom, the four still versions, and Off. Change `preset`, then reload. `lights` stays empty.

Keep private data in `data.local.json`. That file is gitignored. The server reads it into memory. The `data.json` file it writes is the guest copy: titles say Busy, and deadlines and money are empty. Show all is what loads the real titles. On Wi-Fi that ask needs the PIN. When `data.local.json` is missing, the server uses a placeholder. `data.json` is generated and gitignored. Do not commit it.

```json
{
  "updated": "2026-10-24T09:00:00-04:00",
  "today": [{ "time": "9:00", "title": "Morning notes" }],
  "deadlines": [{ "title": "Draft the outline", "due": "Friday" }],
  "money": { "note": "No bills due this week" }
}
```
