# Deployment checklist: Police module on the shared system

One repository, one database. Tick each step in order. Stop and roll back if a step fails.

## A. Before touching Render
- [ ] Tag the Army-only commit: `git tag -a army-only-fallback-v2.1.2 -m "Army-only state" <commit>` then `git push origin army-only-fallback-v2.1.2`.
- [ ] Work on a branch (`police-module`); do not merge to main yet.
- [ ] Run the tests (`cd backend && python manage.py test`, then `cd frontend && npm test && npm run typecheck && npm run lint`) and `python manage.py makemigrations --check`. Fix anything red. These have NOT been run on this code yet.
- [ ] Confirm `FIELD_ENCRYPTION_KEY` is saved somewhere safe (losing it makes encrypted records unreadable).
- [ ] Back up the database (`ops/backup.sh`); check the backup restores (`ops/restore_test.sh`).

## B. Deploy with the module OFF
- [ ] Merge/deploy the branch. Leave `POLICE_MODULE_ENABLED` unset or 0.
- [ ] Watch the logs: `migrate` applies personnel 0004 and organization 0006 without errors.
- [ ] Sign in as an Army admin and check as before: personnel list, a person's page, reports, no Police data anywhere.
- [ ] Sign in as `super_admin`: confirm no Police data shows (module off hides it for everyone).

## C. Prepare
- [ ] Run `python manage.py report_duplicate_identities`. Resolve any Army/Police duplicates it lists (ids only).
- [ ] Create the command-authority accounts: `python manage.py create_command_authority --username <name> --full-name "<name>"` (one per person).
- [ ] Keep `super_admin` to one or two trusted people (it sees everything, including CID).
- [ ] Decide who gets disciplinary/document access (default: branch_admin, cid_officer, super_admin).

## D. Switch the module ON
- [ ] Render dashboard: `POLICE_MODULE_ENABLED=1`. Redeploy.
- [ ] Check Ranks page: 15 draft Police ranks, none approved.
- [ ] Check Organization: Police departments exist under each regional Police command; CID is restricted.
- [ ] Optional demo: set `ARMYHQ_TEST_PERSONNEL=150` and (demo only) `ARMYHQ_TEST_POLICE_DRAFT_RANKS=1`. Redeploy. Never leave test people in a live system.
- [ ] Test with accounts: Police branch admin (no CID), CID officer (CID only), Army admin (no Police), command authority (both, no CID, combined report works).
- [ ] Try the new screens: add a disciplinary entry and a correction; upload, download and withdraw a document; create a station; try a duplicate (should be blocked).
- [ ] Open the Audit log: the actions you just did appear (`disciplinary.*`, `document.*`, `report.combined_view`).

## E. After the Police meeting
- [ ] Make all rank edits first, then approve once (`approve_police_ranks --by <admin> --confirm-reviewed`, `--dry-run` first), because editing an approved rank sends it back to draft.
- [ ] Fix department/station names in Organization.
- [ ] Remove demo people: unset `ARMYHQ_TEST_PERSONNEL` (or 0) and redeploy.

## Rollback
- Quick: set `POLICE_MODULE_ENABLED=0` (hides all Police data; new tables stay).
- Full: redeploy tag `army-only-fallback-v2.1.2` AND restore the pre-deploy database backup (the old code does not know the new tables).
