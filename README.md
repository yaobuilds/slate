# TV Dashboard

A 1920×1080 living-room screen. Plain HTML, CSS, and JavaScript. No build step and no accounts.

## Run

```bash
python3 server.py
```

Open http://localhost:8000

- Home is the clock.
- Dashboard is http://localhost:8000/dashboard.html. Press G to hide Deadlines and Money. Press G again to show them. Home goes back.

Keep private data in `data.local.json`. That file is gitignored. When it exists, the server copies it to `data.json`. When it is missing, the server writes a placeholder. `data.json` is generated and gitignored. Do not commit it.

```json
{
  "updated": "2026-10-24T09:00:00-04:00",
  "today": [{ "time": "9:00", "title": "Morning notes" }],
  "deadlines": [{ "title": "Draft the outline", "due": "Friday" }],
  "money": { "note": "No bills due this week" }
}
```
