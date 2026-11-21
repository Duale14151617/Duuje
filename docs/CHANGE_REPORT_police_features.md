# Change report: features from the Puntland Police system

**Goal:** add every Police-system feature that Duuje lacked, keeping Duuje's organization, department hierarchy and theme.

## How custody maps onto the Army structure
| Police system | Duuje (Army) |
|---|---|
| Station | **Urur** (battalion), unit type `URUR` (`apps/detention/hierarchy.py`) |
| District | **Guuto** (brigade), unit type `GUUTO` (called "district" in API field names) |
| Region command | Qayb regional command |
No unit types, departments or units were added or changed. A new Urur automatically gets a jail-center record (not verified). A jail center can also be recorded on any other unit by hand.

## Not brought over (Police-specific)
Police stations/districts/Kooxo and their departments, police fleet and vehicle group, police profile (`ARMYHQ_PROFILE=police`), `POLICEHQ_*` variable rename, police emblem/photos/judiciary logo, police sample data seeding, `PoliceStrength`.

## Needs checking before use
1. Run `python manage.py migrate`, `python manage.py test`, `npm run lint`, `npm test`, `tsc` (none were run).
2. Confirm Urur is the right custody unit (change `CUSTODY_UNIT_TYPE` / `CUSTODY_PARENT_TYPE` in `apps/detention/hierarchy.py` otherwise).
3. Verify each real jail center on site (Custody facilities > Set status).
4. Review the Somali text of the new screens.
5. Document reference prefix for ID cards is `PDF` (`ISSUANCE_REF_PREFIX`).

## Custody is switched off
Custody (detention register, facilities, incidents, handover, oversight, offline desk) and the Occurrence Book are off by default: set `CUSTODY_ENABLED=1` on the server to turn them on. While off, their routes answer 404, the menu, "My work", org chart, unit pages and "due soon" show nothing for them, new Ururs get no jail record, and the custody management commands do nothing. No data, code, migrations or permissions were removed.
