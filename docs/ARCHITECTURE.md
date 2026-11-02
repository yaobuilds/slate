# How Slate is built

Slate is a small local web app. A Python server (`server.py`, standard library only) serves static HTML, CSS, and JavaScript, and exposes a few JSON endpoints. There is no build step and no package install.

## Pieces

| Piece | Files | Job |
| --- | --- | --- |
| Server | `server.py` | Serves pages, applies the PIN gate, caches weather, radar, map tiles, headlines, and calendar data |
| Pages | `index.html`, `dashboard.html`, `calendar.html`, `weather.html`, `traffic.html`, `gallery.html`, `keel.html`, `network.html`, `settings*.html` | One page per screen, each with its own `.js` and `.css` |
| Look | `tokens.css`, `style.css`, `ambient.*`, `tv-appearance.*` | Shared colors and type, plus the Home backdrop styles |
| TV remote | `remote*.js`, `atv_remote.py` | Phone-to-TV key broker and pairing |
| Tests | `tests/` | Standard-library `unittest` checks for the server, the PIN gate, and the pages |

## Data and privacy

Personal data stays in files that are not committed (see the README table). The schedule exists in two forms:

- `data.local.json` holds real titles and stays on the host.
- `data.json` is generated on every start with titles replaced by "Busy". Guest pages read only this copy.

The calendar secrets go to the macOS Keychain, never to a file in the project folder.

## Requests

1. The server normalizes each URL path and rejects anything with `..`, backslashes, or null bytes.
2. Only files on an allow-list are served. Local files such as `pin.local` and `gallery.local/` are never served by path.
3. Private endpoints check the host, the PIN session, or both before answering.
4. Outbound calls (weather, radar, headlines, map tiles, place search) are made by the server and cached, so the browser never sees API keys.

## Why plain files

Slate runs on a TV browser and a tablet, so the pages stay light: no framework, no bundler, transforms and opacity for motion, and a still mode for reduced motion.
