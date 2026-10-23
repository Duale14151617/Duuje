# Police law (Law No. 2 of 23 Dec 1972) and the system

Source: the supplied copy "Organisation of the Police Force, Somalia, 1972" (pages 99-109 of the compilation). It is a 1972
national law and a **baseline**, not proof of current Puntland Police rules. A handwritten note on its first page appears to say the
force was reformed in 1993 and Puntland's police established in 2010 (hard to read in the scan: please confirm).

## Items 7 and 8: ranks
**Article 23 (Order of Precedence), page 107** lists: General Officers; Senior officers (Colonel, Lt. Colonel, Major); Junior officers
(Captain, Lieutenant, Second Lieutenant); Inspectors (Chief Inspector, Inspector, Sub-Inspector); NCOs (1st Sergeant, Sergeant, Cadet
Officers); Askaris (1st Askari, Askari, Recruit).

* **Item 7 (approve the 15 ranks):** the seeded catalogue matches Article 23 exactly (checked by `test_police_law.py`). Approval is
  still a human decision against *current* rules. Either use the Ranks page, or have the named administrator run
  `python manage.py approve_police_ranks --by <username> --confirm-reviewed` (add `--dry-run` first). That records who approved, when,
  and cites Article 23 in the audit trail; ranks that were renamed are left as draft.
* **Item 8 (General Officers):** the law names the class but lists **no individual ranks** in it, and Article 3 only says the
  Commandant may be chosen "among the generals and colonels". The law therefore cannot supply the titles, and none were added.
  Send the official list (for example the Puntland Police rank decree under Article 24) and they go in as drafts in one step.
* **Two points to settle at approval:** (a) Article 1 defines NCOs as Sergeant up to 1st Sergeant, yet Article 23 lists "Cadet
  Officers" under NCOs: kept where Article 23 puts it. (b) The law's spelling "Lt. Colonel / 1st Sergeant / 1st Askari" is stored as
  Lieutenant Colonel / First Sergeant / First Askari. Both are editable on the Ranks page.
* Article 24: badges of rank are fixed by decree; Article 4: rank carries rights and duties, and members are either in effective
  service or retired in reserve (matches the `retired` status).

## Structure (Article 18) and item 10
| Law | System today |
|---|---|
| Police Headquarters | Headquarters / Police branch |
| Divisional (Regional) Commands | Regional Police command (`BARI-POLICE`...) |
| Group Commands, Sub-Divisional Commands | Not modelled (add as units if the institution uses them) |
| Station Commands | **Station** level (new), under a regional Police command |
| Police Posts | Not modelled (a station is a leaf; tell me if posts must sit under stations) |
| Mobile Group (Darawishta Poliska), Riot unit (Birmadka Poliska) | Not seeded |
| Criminal Investigation Division | CID (restricted) |
| Traffic Division; Training unit | Traffic and Safety; Training |
| Tributary Division; Communication Unit | Not seeded |
| Services: Gadaidka Poliska, Central Stores, Health Service | Not seeded (partly Finance and Logistics) |

The seeded departments (Personnel, Operations, Training, Finance and Logistics, CID, Public Relations, Traffic and Safety) come from
the Puntland Police website, not from this law. **Nothing was renamed.** Decide with the Police authorities which list is right,
then edit in Organization (or tell me and I will change the seed for new deployments).

## Other articles the system already follows
* Art. 22, personal file for every member with all documents and career matters: disciplinary history and service documents.
* Art. 26, regulations on rewards, commendations and disciplinary sanctions: category lists are drafts to align with those regulations.
* Art. 16, duty of confidentiality about office secrets: encrypted records, audited access, restricted CID.
* Art. 2, the Police sit under the Commander-in-Chief (Head of State): supports giving the President read-only oversight.
* Art. 3, the Commandant of Police is a separate appointment from the Head of State. `command_authority` (HQ-wide, Army and Police,
  read-only, no CID) fits the President and the Commander of the Puntland Defense Forces; **decide whether the Commandant of the
  Police needs it too, or a Police-only role.**

## Item 9: Somali wording
The law gives only these Somali terms (read from a scan, OCR may be off): *Poliska* (the Police), *Darawishta Poliska* (mobile
group), *Birmadka Poliska* (riot unit), *Gadaidka Poliska* (a Police service). It gives **no Somali rank titles**, so rank names
remain English in both fields. Every Somali string I wrote for the new screens is a draft: have a Somali speaker review the
`dis.*`, `doc.*`, `comb.*`, `level.station` and new `err.*` keys in `frontend/src/i18n/so.ts`, plus the role names in `seed_reference_data.py`.

## Item 11: command_authority accounts
Create each with `python manage.py create_command_authority --username <name> --full-name "<name>"` (password prompted; first login
forces a password change and MFA). One account per person.

## Item 14: tag the Army-only fallback (before merging this work)
```bash
git tag -a army-only-fallback-v2.1.2 -m "Army-only state before the Police module" <commit-before-police>
git push origin army-only-fallback-v2.1.2
```
Roll back with `git checkout army-only-fallback-v2.1.2`. Turning the module off (`POLICE_MODULE_ENABLED=0`) also hides all Police data
without a code change, but the new migrations stay applied.

## Item 16: Render variables
Set `POLICE_MODULE_ENABLED=1` and `ARMYHQ_TEST_PERSONNEL=150` in the Render dashboard (they are declared in `render.yaml` with
`sync: false`, so the dashboard owns them). Redeploy: the start command seeds and creates the sample people.
