# Vehicle map (self-hosted Puntland tiles)

The map in **Vehicles → Tracking** (and on each vehicle's page) is drawn in the browser with MapLibre from **one file on this server**:
`backend/mapdata/puntland.pmtiles` (OpenStreetMap data for Puntland cut by BBBike, 52 MB, zoom 0–14, OpenMapTiles layout).
The browser reads it with HTTP Range requests from `/api/v1/map/puntland.pmtiles`. **No request goes to any other website** (no tile
server, no fonts, no map service). Place names are drawn from the tile data itself.

## What is on the map
- Latest position of each vehicle in your scope (grey when the position is old). Click one for place, time and age.
- The route trail of the vehicle chosen in "History of vehicle" (green start, gold end), with the distance travelled.
- Zones: circles and polygons. Gold = active, grey dashed = switched off. Click a zone for its name.
- Drawing a zone (needs `vehicles.edit`): in the zone form choose **Circle** or **Polygon**, press **Place on the map**, then click the map.
  Circle: one click sets the centre (drag the "+" to adjust; the radius is typed). Polygon: click each corner in turn (3 to 50), drag a
  numbered corner to move it, "Remove last corner" to undo. Corners must not cross each other. Save with **Add zone**.

Polygon zones work like circle zones: entering or leaving records an event, they appear in the daily report, and they are switched off,
never deleted. A polygon's corners can be changed later through the API (`geofences/update` with `points`).

## Access
Signed-in users with `vehicles.view` only (the file is public OpenStreetMap data, but it is not served to the open internet).
If the file is missing, the page falls back to the plain plot and typing coordinates still works.

## Settings
- `MAP_TILES_FILE` (optional): full path to a different `.pmtiles` file, for example on a Render disk. Default `backend/mapdata/puntland.pmtiles`.
- To refresh or widen the map, cut a new extract (https://extract.bbbike.org, format *pmtiles-basic*) and replace the file. Keep the
  attribution: "© OpenStreetMap contributors" is shown on the map.

## Notes
- GitHub warns about files over 50 MB (limit 100 MB). The tile file is 52 MB: it uploads normally; use Git LFS if you prefer.
- "Offline" here means no internet is needed: the tiles come from your own server, so the map works on an internal network. The browser
  also keeps recently viewed tiles for a day. A fully offline device without access to the server would need the PWA cache extended.
- Zone edges are straight lines between corners in latitude/longitude, accurate for areas up to a town. A fix less accurate than the
  zone's reach (centre to farthest corner) is ignored for that zone, as with circles.
