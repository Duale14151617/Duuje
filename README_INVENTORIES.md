# Weapon inventory: add-on for ARMY HQ

Status: **built but not yet run**: the Django tests and the screen have not been executed. Install it only after your presentation has passed.

## What it is
Western armies make units physically count their sensitive items (weapons, night-vision devices, radios) on a schedule and every time a commander changes: the person responsible checks every serial number against the property record, signs, and any difference is investigated. This is how lost or swapped weapons are caught. This add-on does the same for the **weapon register**.

## How a count works
1. **Start:** a weapons custodian (or anyone with `weapons.manage` for the unit) starts a count for a unit: scheduled, change of command, or spot check. ARMY HQ lists every weapon the register says the unit holds, with the expected holder (a named soldier, or the unit's store). One count per unit at a time.
2. **Check:** for each weapon the counter taps **Verified** (serial read off the item matches), **Missing**, or **Different serial** (and types the serial actually read). An item found that is **not on the list** can be added.
3. **Submit:** only when every weapon has been checked. After this the checks cannot be changed.
4. **Sign off:** a **different person** with `weapons.manage` signs. The sign-off is refused until every shortage or mismatch has an explanation. The signed count is a permanent record (who counted, who signed, when).
Every step is written to the audit log, and viewing a count is logged like the weapon register is.

## Safety rules
- The count **never changes the weapon register**. Marking a weapon lost, returning it or correcting a serial stays in the weapon-register workflow with its own approvals, so a count cannot be used to make a weapon "disappear".
- The counter cannot sign their own count.
- A user sees and counts only the units their permissions cover.

## Install
1. Unzip over the project root. 2. `python apply_inventories.py` (edits settings, API routes, menu, route and translations; safe to run twice). 3. `python manage.py migrate` (adds two tables), then `python manage.py test apps.inventories`.
Page: **Logistics and equipment → Weapon inventory** (English and Somali).

## Not included yet
- Other serial-numbered items (radios, night-vision, vehicles): the counting logic works for any asset, only the list of items is weapons for now.
- Barcode or QR scanning of serial numbers (a natural next step; today the counter reads and confirms by tapping).
- Scheduling and reminders for when a unit's next count is due.
- Printing or exporting the signed count as a document.
