# Adding your own city's traffic feed

If you just want traffic in another US city, you don't need to edit any code. Once you paste a free TomTom key into `tomtom.local` (or set `SLATE_TOMTOM_KEY`), I snap your saved place to a fixed half-degree grid cell such as `grid:33.5,-84.5`, pull nearby incidents for that cell, and proxy colored TomTom flow tiles onto the map. You only need to touch `server.py` when your city or state publishes a free public DOT feed, like a 511 JSON endpoint or a WZDx work-zone feed, and you want it working without a key or layered alongside TomTom.

## How I split regions and caches

In `server.py`, `region_for(lat, lon)` picks which traffic region owns a coordinate. Inside `DMV_BOUNDS` (latitude `38.60` to `39.35`, longitude `-77.60` to `-76.70`, edges included) it returns `dmv` for DC, Maryland, and Northern Virginia. Inside `NY_STATE_BOUNDS` (`40.49` to `45.12`, `-79.76` to `-71.85`, a touch wider than the state line so nearby NJ and CT towns stay on the regional feeds) it returns `ny`. Everywhere else it rounds down to a half-degree cell and returns a key like `grid:33.5,-84.5`, so nearby points share one cache entry and your exact coordinates never leave the server.

Each region writes to its own slot in `TRAFFIC_CACHE`. Switching your saved place in Settings never mixes one region's incidents into another's.

## Wiring a public DOT feed

Everything lives in `server.py` using Python's standard library, so there are no packages to install. To add a keyless regional feed, define your bounding-box constants next to `DMV_BOUNDS` and have `region_for` return a short region name before the `grid:` fallback. Next, write a parser that fetches your feed with a short timeout and turns each item into a dictionary with `road` (up to 120 characters), `description` (up to 220 characters), `time` (an ISO-8601 or RFC-2822 timestamp), `lat` and `lon` as floats, and a short `feed` slug such as `md-chart`.

Skip any item missing a valid coordinate or timestamp. On display, Slate keeps up to eight incidents within 160 km and drops ordinary events older than 36 hours, though you can exempt long-running road closures the way I do in `pick_dmv_rows`. Cache good reads in `TRAFFIC_CACHE` for three to five minutes, and when a fetch fails, keep serving the last good list rather than wiping the screen.

## How New York and the DMV work

New York (`ny`) was the first region I built. It tries the 511NY JSON feed first and falls back to the 511NJ TRANSCOM RSS feed on a 3-minute cache, while a separate 4-minute poll reads NYC DOT traffic speeds to color roads inside the five boroughs without needing a key.

For the DMV (`dmv`), I combine two sources. Every 4 minutes I fetch Maryland CHART's keyless incident and active-closure JSON feeds (`md-chart`), which cover Maryland highways and the Maryland side of the Beltway. When a TomTom key is present, I also query TomTom Incident Details for the fixed `DMV_BOUNDS` box every 5 minutes (`tomtom`) to fill in DC streets and Northern Virginia. When CHART and TomTom report the same incident, I keep the CHART entry so highway naming stays consistent.

Outside New York and the DMV, any `grid:` region uses that same 5-minute TomTom incident request for its half-degree cell, or returns an empty list quietly if you haven't set a TomTom key. To keep a dashboard running all day well inside TomTom's free tier (about 2,500 incident calls and 200,000 tile requests a month), I cap incident calls at 80 per UTC day across the DMV and grid combined, cache flow tiles for 4 minutes with a 4,000-tile daily cap, and pause for 15 minutes on a `429` rate limit while holding onto the last good data. Whenever NYC DOT speed lines are visible on the map, I keep the flow tiles hidden so roads aren't colored twice, and turn them on automatically when you pan outside the city.

## Keys and map credits

Both keys stay strictly on the machine running Slate. Paste your CARTO basemap key as the single line in `carto.local` (or set `SLATE_CARTO_KEY`) and your TomTom key as the single line in `tomtom.local` (or set `SLATE_TOMTOM_KEY`), then restart `python3 server.py`. Never share or commit `*.local` files.

At the bottom of the Traffic page, `renderCredits` in `traffic.js` updates the credit line to match what's actually on screen. OpenStreetMap and CARTO are always credited for the street tiles. When a shown incident comes from `md-chart`, I add a link to [Maryland CHART](https://chart.maryland.gov/). When a TomTom incident or flow tile is on screen, I add TomTom's copyright caption (fetched once a day, falling back to `© TomTom`) linked to TomTom's [third-party product terms](https://www.tomtom.com/en_gb/thirdpartyproductterms/). If you add a new public feed, return its slug in `sources` and add its credit link in `renderCredits` so the data source gets proper attribution.
