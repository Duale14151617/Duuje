# Military vehicle tracking

Tracking is part of the Vehicles feature, not a separate area: **Vehicles → Tracking** tab (all vehicles in your scope) and a
**Vehicle positions** section on each vehicle's page. There is no separate menu item.

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

## Retention
Positions are never deleted in normal running: the database refuses it. Old positions can be retired only through a signed archive
and a controlled purge: see `docs/POSITION_ARCHIVE.md`.
