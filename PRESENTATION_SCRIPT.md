# ARMY HQ: 10-minute presentation script

**Before you start (15 minutes ahead):** open the site once so the Render instance wakes up. Log in as `superadmin` and `hqadmin` in two different browsers (or one normal and one private window), and finish MFA on both. All sample accounts share the sample password set in `ARMYHQ_SAMPLE_PASSWORD`.

## 1. The picture (2 min), `superadmin`
- **Dashboard:** strength, attendance, logistics, fleet and protective-equipment panels in one view.
- **Organization / Unit tree:** Headquarters, regions, branch commands and units. Everything a user sees is limited to the part of the tree they are responsible for.

## 2. People (1 min), `superadmin`
- **Personnel:** open a sample person. Show rank, unit, and the history of changes with the Army order recorded.

## 3. Logistics and equipment (3 min), `superadmin`
- **Logistics:** stock per unit and registered assets.
- **Protective equipment:** helmets and body armour in stock, and which soldier holds what (Sample Person 01 and 02). Open **Manage** to show how an item is issued, returned, replaced or inspected.
- **Weapon register / Ammunition accountability:** serial numbers, custody, and the rule that rounds are never counted twice.
- **Military vehicles:** the fleet with maintenance status.

## 4. The key point: approvals (3 min), `hqadmin` then `superadmin`
This shows that the administrator works every day but cannot take authority.
1. As `hqadmin`, open a sample person. Note there is no direct transfer, rank or status button, only **Raise a change request**.
2. Raise a **rank change** (Change requests, New request): pick Sample Person 03, a new rank, the Army order reference, the issuing officer and date.
3. Show the request as **pending** and the person's rank **unchanged**.
4. Switch to `superadmin`, open **Change requests**, **approve** it, then open the person: the rank changed and the history shows the order.
5. Optional: as `hqadmin` try to approve your own request. It is refused.

## 5. Accountability (1 min), `auditor` or `superadmin`
- **Audit log:** every approval, change and access is recorded with who and when.

## Likely questions
- **Who can see what?** Roles and the unit tree decide it; people only see their own area.
- **What if the HQ admin is compromised?** They cannot approve, move money, confirm deaths, or give anyone more authority than they hold themselves. Their requests wait for the super administrator.
- **Is it real data?** No, the sample data is synthetic.
- **Where is it hosted?** Render (backend and frontend in one service) with a managed database.

## If something fails during the sample
Stay calm, move to the next section, and note the screen. A server error never loses data: refresh and continue.
