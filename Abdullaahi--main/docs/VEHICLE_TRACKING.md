# Police vehicle tracking

Tracking has its own page, **Vehicle tracking** (every vehicle in your scope: map, silent vehicles, zones, daily movement report,
trackers), and a **Vehicle positions** section on each vehicle's page. Both use the same Puntland map (see VEHICLE_MAP.md).

## Three ways a position arrives
1. **Typed in** by an officer (latitude, longitude, optional place and note).
2. **From a phone**: "Use my phone's location", or "Share live location" (about once a minute while the page stays open).
3. **From a fitted GPS tracker**, usually through a Traccar server forwarding to `/api/v1/tracker/feed/`.

## Linking a tracker (needs `vehicles.edit`)
Open the vehicle (or the Tracking tab), enter the tracker's device ID (IMEI) and choose *Link tracker*. The forwarding address with its
key is shown **once**; only a hash is kept. Switch the link off at any time; a switched-off key stops working immediately.
The key can only add positions for its own vehicle. One active link per device.

## Permissions
- `vehicles.view` reads positions (narrowed to your units). `vehicles.position` reports or voids positions (granted to the transport officer).
- Positions are never deleted: a wrong one is voided with a reason. Every report, void, link and failed tracker key is audited.

## Setting
`THROTTLE_TRACKER` (default `600/min` per address). Repeated wrong keys from one address are refused for ten minutes.

## Vehicles not reporting (`GET /api/v1/vehicle-tracking/silent/?hours=24`)
Lists vehicles in your scope with no usable position for `hours` (1 to 720, default 24) or none ever, and active GPS trackers that
have gone quiet for as long. Vehicles that are in the workshop (under maintenance or repair, out of service, awaiting inspection) or
decommissioned are left out, because silence is expected there. The Vehicle positions page shows this as a panel at the top.

## Route and distance (`GET /api/v1/vehicle-tracking/trail/?vehicle=...&from=...&to=...`)
Returns one vehicle's positions oldest first (at most the newest 500, with `truncated` set when there are more) and the distance
travelled. Distance adds up straight lines between points and ignores moves under 25 m, so a parked vehicle's GPS drift does not
add up. It is an estimate for planning, not an odometer. The page draws the route as a plain SVG line, with no map service.

## Rotating a tracker key (`POST /api/v1/vehicle-tracking/<id>/trackers/rotate/`, needs `vehicles.edit`)
Makes a new key for an active tracker and stops the old one at once. Use it when a key may have leaked or the Traccar server is
replaced. The link, history and last-seen time are kept; the new key is shown once. Audited as `vehicle.tracker_rotate`.

## Privacy
Phone locations are personal data as well as operational data. Who sees them: only roles with `vehicles.view`, narrowed to their
units. Every read of latest, history, trail and silent lists is written to the audit log. A phone sends its position only while the
Vehicle positions page is open and sharing is on; nothing is sent in the background. The page shows this notice next to the location
buttons. Share a phone's location only on official duty.

## Zones (geofences)
A zone is a circle: a centre, a radius (50 m to 100 km) and what to record (entering, leaving or both). Anyone who can see vehicles sees the
zones; creating, changing or switching one off needs `vehicles.edit`. Zones are switched off, never deleted, because past events point at them.
- `GET vehicle-tracking/geofences/` lists zones. `POST vehicle-tracking/geofences/add/` makes one. `POST vehicle-tracking/<id>/geofences/update/`
  changes one (send the current `version`; `active: false` switches it off).
- `GET vehicle-tracking/geofence-events/?vehicle=&geofence=&from=&to=&limit=` lists crossings, newest first, narrowed to the caller's units.

How a crossing is decided (code: `apps/vehicles/geofences.py`):
1. Every new position (typed, phone or tracker) is compared with every active zone; inside means within the radius of the centre.
2. A fix whose accuracy is worse than the zone's radius is skipped for that zone: it says nothing reliable about the edge.
3. The first usable fix of a vehicle for a zone only sets the starting point. No event. After that, outside to inside is an ENTER and inside to
   outside is an EXIT. A zone set to record one direction still tracks both, so it never misses the next one.
4. A fix older than the newest one already used (a tracker resending late) is ignored, so events follow time order.
5. Changing a zone's place or size, or switching it off and on again, clears its starting points: the next fix sets a new one (no event).
6. Events are written in the same transaction as the position and never changed or deleted. Voiding a position later does not remove the event it
   caused. An event keeps its own copy of the place and time, so retiring old positions (`docs/POSITION_ARCHIVE.md`) never touches events.

## Daily movement report
`GET vehicle-tracking/daily-report/?date=YYYY-MM-DD` (default today; future days are refused). `GET vehicle-tracking/daily-report/export/` is the
same as a CSV file: it needs a fresh authenticator check, and the file's SHA-256 is written to the audit log (`vehicle.export_daily_report`).
Both are narrowed to the caller's units. The day runs midnight to midnight in `REPORT_TIME_ZONE` (an IANA name such as `Africa/Mogadishu`;
default UTC, so set it).
Per vehicle that reported: number of positions, first and last position, distance travelled, and for each zone the minutes inside and the number of
entries and exits. Vehicles with no position that day are listed as not reporting (and appear in the CSV with 0 positions).
- Distance adds straight lines between points and ignores moves under 25 m (the same rule as the route trail).
- Minutes inside count the time between two fixes only when the earlier one was inside and the gap is at most 30 minutes; a longer silence is not
  counted either way. These are estimates from reported points, not an odometer or a time sheet.
- Voided positions and decommissioned vehicles are left out.

## Retention
Positions are never deleted in normal running: the database refuses it. Old positions can be retired only through a signed archive
and a controlled purge: see `docs/POSITION_ARCHIVE.md`.
