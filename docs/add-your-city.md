# Add a traffic region

Slate picks a traffic region from the saved place. A region is a box on the map and the feeds that fill it. The street map is the same everywhere. The incident list changes with the region.

## What a region is

`region_for` in `server.py` reads the place. Inside the box for DC, Maryland, and Northern Virginia it returns `dmv`. Inside the New York rectangle it returns `ny`. Everywhere else it snaps the place to a half-degree cell and returns a key such as `grid:33.5,-84.5`. Places in the same cell share one cache entry. The request sends that cell, not the exact place.

The `dmv` box runs from latitude 38.60 to 39.35 and from longitude -77.60 to -76.70. A point on the edge is inside.

The New York rectangle runs from latitude 40.49 to 45.12 and from longitude -79.76 to -71.85. It is a little wider than the state line, so a few places just outside New York stay on the New York feeds. A place outside both boxes uses the grid.

## How to add one

There is no settings file for a region. Another city in the US does not need a new box. With a TomTom key, the grid already asks for that cell. Edit `server.py` only to add a keyless feed, the way Maryland CHART is added for the DMV.

1. Pick a short name and a latitude and longitude box. Check that box in `region_for` before the grid.
2. Store that region's rows in their own cache entry. Leave the other entries alone.
3. Write a reader that returns the row shape below.
4. Call the reader from `traffic_incidents_for` when the place is in the new box.
5. On a failed read, keep the last good list.

## Write a reader

Each row the page can show has these fields:

| Field | Meaning |
| --- | --- |
| `road` | A short road name |
| `description` | One line about the incident |
| `time` | When it started, as a date string |
| `lat`, `lon` | A point |
| `feed` | A short id for the source, such as `md-chart` |

Skip a row with no point or no time. The page keeps up to eight rows within about 160 km. Ordinary events older than 36 hours are dropped.

## New York

The New York reader tries the 511NY JSON feed, then the 511NJ RSS feed. A good read is stored on the `ny` cache part for 3 minutes. The feed id, `511ny-json` or `511nj-transcom-rss`, is stored on that part. The rows themselves have road, description, time, latitude, and longitude.

Live speeds are a separate 4-minute clock. They color roads in New York City only.

## The DMV

The DMV reader uses two feeds.

Maryland CHART needs no key. Slate reads the events JSON and the closures JSON together, every 4 minutes, and tags those rows `md-chart`.

TomTom Incident Details covers DC and Northern Virginia when a key is set. The request sends the fixed DMV box. It does not send the saved place or the current map view. Those rows are tagged `tomtom` and kept for 5 minutes. Slate makes at most 80 TomTom calls per UTC day, and the grid uses that same stop. After that stop, the last list is used for 30 minutes, and then TomTom is left out until the next day. A rate-limit response pauses the feed for 15 minutes and keeps the last list. When CHART and TomTom both report the same incident, the CHART row is the one that stays.

Outside New York and the DMV, the same TomTom request covers one half-degree cell. The cell is fixed. The saved place and the map view stay out of the URL. With no key, that list stays empty and Slate does not call TomTom.

The free Incident Details allowance is about 2,500 calls a month. The five-minute cache and the daily stop keep a home screen inside that allowance.

## Where keys go

The CARTO key for street tiles is `carto.local` or `SLATE_CARTO_KEY`. The README Traffic map section shows how to save it.

The TomTom key is `SLATE_TOMTOM_KEY`, or the first non-empty line of `tomtom.local`. The environment variable wins. Save the file the same way as the map key:

```bash
umask 077
printf '%s\n' 'paste-the-key-here' > tomtom.local
```

Start Slate again after saving it. The server calls TomTom. The page never receives the key. Do not share the key, and do not commit the file.

## Colored roads

New York City speed lines need no key. They color roads in the city on their own clock.

With a TomTom key, Slate also fetches flow tiles for the map on screen. Those tiles color roads outside New York City. While a city speed line is on screen, the flow tiles stay off, so a road is not colored twice. Panning until the city lines leave the map shows the tiles for the area around the city. The footer names TomTom when a flow tile is on screen, even if the incident list is empty. The tiles use their own counter: about 4 minutes, and at most 4,000 tiles per UTC day.

## Clocks

Each feed has its own timer, kept in memory. A fresh read waits until the timer ends. A failed read keeps the previous list.

| Feed | Fresh read |
| --- | --- |
| New York incidents | Every 3 minutes |
| Maryland CHART | Every 4 minutes |
| TomTom incidents | Every 5 minutes, and at most 80 calls per UTC day, shared by the DMV and the grid |
| TomTom flow tiles | Every 4 minutes, and at most 4,000 tiles per UTC day |
| TomTom caption | Once a day, and only when a TomTom row or a flow tile is shown |
| New York speeds | Every 4 minutes |

## When the footer names a feed

The footer always credits OpenStreetMap and CARTO for the tiles.

It adds Maryland CHART when a shown row has feed `md-chart`, with a link to [chart.maryland.gov](https://chart.maryland.gov/). It adds the TomTom line when a shown row has feed `tomtom`. Those words come from TomTom's caption, or `© TomTom` when the caption is missing. The link is TomTom's [third-party product terms](https://www.tomtom.com/en_gb/thirdpartyproductterms/).

A New York response has no `sources` list, so the footer stays OpenStreetMap and CARTO until a flow tile is on screen. A grid response adds the TomTom line only when a shown row has feed `tomtom`. A flow tile on screen adds that same line even when no incident row was shown. A feed that is configured but did not contribute a shown row, and is not on screen as a flow tile, is left off the line.
