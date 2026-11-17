# Police Fleet Management (Police Vehicles)

The fleet module is the vehicle register in `apps/vehicles`. In the Police deployment (`ARMYHQ_PROFILE=police`) the command
`apply_police_fleet --apply` runs at every start and creates the Police vehicle types under the main category **Police Vehicles**.
It only creates what is missing and never overwrites an edit. Somali names are working labels to confirm with the Police.

| Type | Code | Purpose |
|---|---|---|
| Police Transport Vehicles | `police_transport` | Transporting officers and personnel |
| Police Pickup Trucks | `police_pickup` | Patrols, operational duties, carrying equipment |
| Police Tactical Vehicles | `police_tactical` | Specialized units on high-risk operations |
| Police Armored Vehicles | `police_armored` | Operations needing enhanced vehicle protection |
| Police Motorcycles | `police_motorcycle` | Traffic enforcement and patrols |
| Police Prisoner Transport Vehicles | `police_prisoner_transport` | Taking arrested or detained persons to stations, detention facilities or other authorized places |

Military-only categories from the shared reference data (tank, armoured personnel carrier, military trucks, and the Army
armored truck, Hilux 4x4 and motorcycle categories) are switched off **only while no vehicle uses them**. HQ can switch any back on
under the vehicle categories.

## What each record holds
- **Unique vehicle ID** (system-generated, never reused) and **registration number** (plate, unique; state plates start `GD`).
- **Category** (one of the types above, or any category HQ adds), make, model, year, condition, specifications, photographs.
- **Assigned unit or station** (a normal organization unit, so Garowe stations and Kooxo work as soon as they exist).
- **Driver** and **responsible officer** (stored as the vehicle's custodian). One driver can drive one vehicle at a time.
- **Operational status** (operational, under maintenance, under repair, awaiting inspection, out of service, decommissioned; HQ can add more).
- **Maintenance records** (service, repair, inspection; open or completed; next due date; workshop; cost visible only with `vehicles.cost`).
- Documents (registration, service reports, receipts), location, and a permanent history of every change.

## Access control (existing roles)
| Role | Rights |
|---|---|
| Transport officer | View, register, edit, assign, transfer, propose disposal, see costs, for the units in the assignment (MFA) |
| Vehicle disposal approver | View and approve or reject a disposal proposed by someone else |
| HQ administrator | Everything above in scope, plus add and edit vehicle categories (`vehicles.configure`) |
| Regional chief, branch admin, unit commander | View vehicles in their scope |

Everything is limited to the user's unit scope. Every view, change, assignment, status change and maintenance entry is written to the
audit log, and the vehicle's own history (`VehicleEvent`) is append-only. Vehicles are never deleted: they are decommissioned
through a two-person disposal.

## Not included
- No trip log, fuel log, GPS tracking or booking of vehicles for a journey.
- No prisoner records: the prisoner transport type only classifies the vehicle.
- No dispatch or radio integration.
Say if you want any of these added.
