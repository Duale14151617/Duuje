# Station detention units

Every police station has a jail center *record*. A record is not proof that a lock-up exists: it starts **not verified** and cannot hold anyone until an authorised person verifies it on site.

## Who can do what
| Action | Permission | Roles |
|---|---|---|
| Read register, dashboards | `detention.view` | station/district commanders (by unit scope), regional commander, custody officer, HQ admin |
| Book in, events, review, release, transfer, receive, cells | `detention.manage` | station commander (own station), custody officer, HQ admin |
| Verify / suspend / close a facility, hierarchy findings | `detention.verify` | regional commander (own region), HQ admin |

## Workflow
Book in (ID duplicate check, optional cell) -> welfare / medical / visit / property / statement / **custody review** -> release (no charge, bail, court order, sentence served), hand to court, hand to a prison, or **transfer to another station** (sender closes; receiver receives once). Nothing is deleted; wrong entries are voided with a reason. Every action stores user, time, outcome and an audit event.

## Court, charge, incidents, reports, printing
* **Court dates and remand:** record what the court or prosecutor ordered; the system flags remand ended, court date passed and court soon. It sets no legal limit.
* **Charge and case file:** recorded when it exists; Occurrence Book entries linked to the person are listed on the record.
* **Incidents (death, injury, use of force):** reported by the station, read by every commander whose area covers it, reviewed by `detention.incident_review` (not by the reporter). A death closes the register row.
* **Cell warnings:** women only / juveniles only / adult men only, and men with women. Warn only, never block.
* **Reports:** period report by station, district and region, CSV or PDF. **Printing:** custody record, property receipt, release/transfer note; every print is audited.

## Settings
* `DETENTION_REVIEW_HOURS` (default 48): review alert interval chosen by the administration. It is not a legal limit.
* `DETENTION_COURT_REMINDER_DAYS` (default 2): how many days ahead a court date is flagged.
* `DETENTION_JUVENILE_UNDER_AGE` (empty by default): age below which a person counts as a juvenile for cell warnings. Set only what your institution decides.
* `DETENTION_REQUIRE_OPERATIONAL_FACILITY=1`: refuse bookings at stations without an operational jail center.

## Commands (all safe to rerun)
* `python manage.py apply_custody_facilities`: adds missing jail and generic prison records (not verified); never edits existing ones.
* `python manage.py verify_station_hierarchy [--strict] [--json]`: read-only check of every active station.

## Not decided by the system
Districts, real jails, prison names/locations and legal detention limits are never invented: stations without a district are listed as a note, prisons are placeholders until confirmed.
