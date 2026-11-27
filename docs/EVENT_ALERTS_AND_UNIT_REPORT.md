# Unit report (PDF) and event alert emails

## Unit report
- **Download:** open a unit (Units -> the unit) and press **Unit report (PDF)**. Pick the period (7, 30, 90 or 365 days). It covers the unit and everything below it: strength by rank, leave, weapons, vehicles and fuel.
- **Email it on a timetable:** Scheduled reports -> New schedule -> *What to send* = **Unit report (PDF attached)**. The PDF is attached to the email.
- **Totals only.** No names, service numbers or serial numbers, so a printed copy can go to a commander who has no login.
- **Who sees what.** A section is included only if the person downloading it may see that information for the unit. For an emailed report, only if the schedule's creator AND every recipient may. Fuel cost needs `vehicles.cost`.
- **Gmail through Apps Script:** the script must be the newer version in `docs/APPS_SCRIPT_MAILER.md` (it adds the attachment lines), deployed as a new version. Brevo and the Gmail API need nothing extra.

## Event alerts (email)
Each person turns alerts on for themselves: **Account -> Email alerts**. Only alerts their role allows are listed, and they are sent only to a verified email address, only for units they may see.

| Alert | When | Permission needed over the unit |
|---|---|---|
| A vehicle crosses a zone boundary | a position puts a vehicle inside or outside a zone (each zone's own "alert on" setting decides entering, leaving or both) | `vehicles.view` |
| A weapon is reported lost or missing | a weapon asset is marked lost or missing | `weapons.view` |
| A GPS tracker stops reporting | an active tracker silent for 24 hours (not for vehicles in the workshop or decommissioned) | `vehicles.view` |
| A death is reported for a soldier | a death report is filed (before confirmation) | `personnel.view` |

The emails say what happened, where and when, with no names. Weapons show the serial number and vehicles the ID and plate, because the commander needs them to act.

**Silent trackers need a regular trigger.** The other three alerts fire the moment the event happens. The silent-tracker check runs whenever the outside scheduler calls `POST /api/v1/schedules/run-due/` (header `X-Cron-Token`; needs `SCHEDULES_CRON_TOKEN`, 24 characters or more), or when you run `python manage.py send_scheduled_reports`. Call it every 15 to 60 minutes. Each silent spell is mailed once.

Settings: `EVENT_ALERTS_ENABLED` (default on; `0` stops every alert), `ORG_NAME` (the name at the top of the PDF).
Not included yet: SMS. It needs a sending service and phone numbers on user accounts.
