# Known limitations, security concerns, next-version prerequisites

## Verification status
See `CHANGE_REPORT_v1.0.md`: the backend test suite and frontend build were **written but not executed** in the
authoring environment (no network, no Django/npm packages). Run them first. Migrations were hand-written; confirm with
`makemigrations --check`.

## Limitations
- Rank catalogue: the Army list is the 16 official ranks supplied in the 1.3.1 addendum (Navy/Police ranks are not seeded).
  The provisional US-style list was retired (see the 1.3.1 notes below).
- Somali UI text is a draft and needs review by a qualified translator and institutional terminology owners.
- Organization units cannot be moved/re-parented after creation (path-based scope). Deleting units is not supported (deactivate).
- Account administration (users, roles) is headquarters-level only; regional delegation is not in 1.0.
- No recovery codes for lost MFA devices (an HQ admin resets MFA after verifying identity). Password recovery uses administrator-issued one-time codes (1.4); no email/SMS is built in.
- Session revocation scans stored sessions (fine for small deployments); the epoch check is what enforces it.
- Audit trigger/immutability needs PostgreSQL; SQLite relies on the application guard only. Audit reads are not themselves audited.
- Login failures for unknown usernames are logged without the attempted name (avoids logging mistyped passwords).
- Throttling uses a DB cache; per-IP behind a proxy requires `TRUST_PROXY_HEADERS` correctly configured.
- Personnel (1.1): duplicate/service-number checks are global (needed for integrity) but only ever answer yes/no,
  never reveal the other record. Transfers between service branches are not supported. Changes cannot be future-dated.
  Edits to history entries are not supported (corrections are new entries). No medical or family data. Import: CSV only,
  max 1,000 rows / 1 MB; previews expire after 1 hour and their rows are wiped on commit (no scheduled purge job yet).
  Export is off by default and needs institutional approval before enabling. Rank approval needs Somali names, so a real
  rollout must supply them before any personnel can be added.

## Security notes
Not independently reviewed. No certification is claimed. Real data requires institutional approval, an independent
security review (Version 1.4), backup/restore test, HTTPS hosting and an incident process.

## Prerequisites for Version 1.1 (Personnel)
Confirm approved personnel fields; approved/verified rank list per branch; unit definitions; hosting; retention policy.

## Version 1.2 notes
- Only the person who prepared an item can edit, submit or amend it (no delegation). A reviewer in scope can decide
  any submitted item they did not prepare; there is no explicit reviewer assignment or multi-step approval chain yet.
- Separation of duties is enforced per report type; disabling it is an institutional policy decision and is flagged in audit.
- Figures are limited to a fixed whitelist of whole-number fields; free-form fields/attachments are not supported.
- Notifications are in-app only (no email/SMS/push). They are created at the time of the event for the reviewers
  in scope at that moment; people who gain scope later are not back-filled.
- Summaries are computed on the fly (capped at 5,000 approved items per request); no snapshots or scheduled reports.
- Rejected items stay rejected (create a new item instead). Approved revisions are never edited in place.
- Report types cannot be deleted, only deactivated.

## Version 1.3 notes
- Only synthetic examples are seeded. No weapon-specific categories, serial numbers or per-person equipment records
  exist or can be created: restricted equipment is a generic restricted category held by units and custodians.
  Whether and how this module may hold sensitive equipment at all needs institutional review before any real use.
- Seeded categories and courses are drafts/placeholders (Somali text is a draft). Categories cannot be deleted, only deactivated.
- Stock lines are created on first transfer into a unit; two simultaneous first transfers into the same new line could
  hit the unique constraint (one would be rejected and must retry).
- Ledger and asset history are append-only in the application; there is no PostgreSQL trigger for them yet (planned in 1.4,
  as done for the audit table). Corrections are new adjusting entries.
- Reconciliation has no second-person sign-off, and stock changes made during a count are handled by comparing against the
  current balance at completion (documented behaviour, not a lock).
- Reports/summaries have no export in 1.3 and are computed on the fly (capped at 10,000 rows per request).
- Training records follow the person's *current* unit for visibility. There is no certificate/attachment handling,
  scores, instructors, rooms, budgets or prerequisites.
- Only active or on-leave personnel can be enrolled; withdrawn/failed records are terminal (enrol again with a new start date).

## Version 1.4 notes
Hardening only (no new product modules). Read `docs/SECURITY.md` for findings, fixes and residual risks.
- Nothing from 1.4 has been executed: the new tests, scripts and CI workflow have not been run, the backup/restore test
  has not been performed, accessibility/Android/performance testing has not been done, and no independent review has occurred.
- Open design risk: an HQ administrator can grant themselves a data role (audited, not blocked). A two-person rule is recommended.
- DB-level append-only triggers exist only on PostgreSQL and can be removed by a database superuser.
- Password reset codes are 40-bit, 60-minute, single-use and rate-limited; their security depends on how the code is handed over.
- Sessions: 30-minute idle and 12-hour absolute limits are defaults chosen by the author; the institution should confirm them.

## Version 1.3.1 notes (Puntland Army ranks and organizational structure addendum)
- **Rank names are used as supplied for both languages.** No translation was invented: `name_so` equals `name_en`
  until the institution supplies verified wording. "Sarreye Guuto (General)" and "Sarreye Guud (Marshall)" are stored
  exactly as written, bracketed equivalents included. Rank codes `PA-01`..`PA-16` are internal identifiers (editable),
  not official codes. The 16 ranks are not split into enlisted/warrant/officer (category `unspecified`).
- **The 16 ranks are seeded as approved** because they were supplied as official. An authorised user can edit or
  re-approve them; editing a name resets a rank to draft (existing rule).
- **People on the old provisional ranks are not re-ranked automatically** (no mapping was supplied). Those ranks are kept
  but inactive so no record is orphaned; `manage.py report_rank_remap` counts who is affected and an authorised user
  re-ranks them with the normal change-rank action. Unused provisional ranks were deleted. The rank migration is not
  reversible; roll back by restoring the pre-upgrade backup.
- **Reference strengths are information, not constraints.** Nothing blocks a unit above or below them, and no
  personnel are ever created to fill vacancies. Actual strength counts personnel still in service (not retired or
  discharged) in the unit and everything below it, and is shown only where the viewer has personnel.view for that unit.
- **"Taliska Guud" is modelled as the regional Army command** (the existing branch-command unit of the Army in each
  region). Existing Army regional commands are tagged automatically; Navy and Police commands are not.
- **Template is checked, never enforced.** Two Gaas per Qayb, parent/child order and the designated Horin Sahan /
  Urur Sahan and Sanco are reported on the Structure page as findings. Only two structural rules are hard errors:
  a type must fit its level (Taliska Guud on a branch command, all others on units) and a child type must be deeper than
  its parent type.
- **Assumption to confirm:** "Each Gaas has a designated Urur Sahan/Sanco" is implemented as two rules (an Urur Sahan and an
  Urur Sanco; one Urur may carry both). The rules are data and can be deactivated or changed on the Structure page.
- Unit types and designations are not branch-specific; any branch could use them. Reference figures and the per-parent
  standard are editable by headquarters administrators.
- Searchable unit picker shows up to 30 matches per search. The Organization list is paginated (50 per page); there is no
  tree view yet.

## Version 2.0 notes
Read `docs/SECURITY_REVIEW_v2.0.md` (risks R1-R9) and `docs/IMPACT_ASSESSMENT_v2.0.md`.
- Nothing from 2.0 has been executed by its author: no Django, PostgreSQL or npm packages were available. The new tests, migrations (hand-written), frontend build and typecheck must be run before use (`makemigrations --check`, `manage.py test apps`, `npm run build`).
- The four top-level categories (HQ, region, branch command, unit) are still fixed; units still cannot be re-parented. Subordinate levels (Qayb…Unug) are configurable only through an approved proposal (`STRUCTURE_APPROVAL.md`). Designation rules, designations and strength exceptions are not behind the gate. Role definitions are not tied to level types.
- Integrations are inbound and read-only, aggregates only. No outbound calls/webhooks, no person-level data, no restricted equipment.
- Small-cell withholding is not differential privacy; repeated date-filtered calls can still reveal small groups to an authorized key holder (`?unit=` is refused for keys by default).
- Integration keys are not re-checked against their creator's current permissions at call time (`integration_report` flags them); `integration_calls` has no purge.
- Offline access is not implemented (no documented need).
- Somali text for the new screens is a draft and needs qualified review.

