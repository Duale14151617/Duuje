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

Not carried over from the Police system: traffic and tax features, and trip-linking of positions.
