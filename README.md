# TV Dashboard

A 1920×1080 living-room screen. Plain HTML, CSS, and JavaScript. No build step and no accounts.

## Run

```bash
python3 server.py
```

Open http://127.0.0.1:8000. The terminal also prints an address for other devices on this Wi-Fi. Do not forward port 8000 on the router.

- Home is the clock, the New York weather, and the app tiles. The first tile is Dashboard. Arrow keys move between the tiles. Enter opens Dashboard. The other tiles do not open anything yet.
- The other tiles come from `apps.json`, at most five. Names and icons come from `apps-catalog.json`. To change a tile, use an id from the catalog. An entry can also set its own name, icon, or url.
- Dashboard is http://127.0.0.1:8000/dashboard.html. It opens in guest mode, with Deadlines and Money empty. Press G to show them. Press G again to clear them. After 30 minutes with no key press, they clear again. From midnight to 6 AM the screen dims to about 60% brightness. Esc or Backspace goes Home.
- Soft colored light moves behind both pages. Aurora is the default. The other choices live in `ambient.json` under `preset`: Ember, Lagoon, Bloom, the four still versions, and Off. Change `preset`, then reload. `lights` stays empty. The page does not talk to a lamp.

Keep private data in `data.local.json`. That file is gitignored. When it exists, the server copies it to `data.json`. When it is missing, the server writes a placeholder. `data.json` is generated and gitignored. Do not commit it.

```json
{
  "updated": "2026-10-24T09:00:00-04:00",
  "today": [{ "time": "9:00", "title": "Morning notes" }],
  "deadlines": [{ "title": "Draft the outline", "due": "Friday" }],
  "money": { "note": "No bills due this week" }
}
```
