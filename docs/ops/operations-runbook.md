# Operations runbook

## Permission administration
Roles and permissions: docs/permission-matrix.md. Company staff are managed by the company owner (`staff.manage`); the last owner cannot be removed. Platform roles (`platform_admin`, `verification_officer`, `platform_finance`) are assigned only in the database by the operational owner (two-person rule: one requests, one executes, both recorded in the change log). Review all platform accounts and company owners quarterly; remove leavers the same day (suspend the user, log out everywhere). Require MFA for platform staff and money-approving permissions via `Security__MfaRequiredPermissions`.

## Company and technician verification
Queues: `GET /platform/companies?verification=Pending`, `GET /platform/technician-documents`, `GET /platform/technician-skills` (also on `/platform/overview`). Reviewers see documents only through 120-second signed links (each view is audited). Decisions: approve / reject / request more information, always with a note. Nobody reviews their own company or documents. What evidence is required per business category and trade is a **business decision** that must be written down before launch; expiry dates on skills drive reminders and matching.

## Payment reconciliation (daily)
1. Finance opens Finance → Reconciliation: payments awaiting reconciliation, self-reported (unverified) payments, and payments stuck in *Initiated* for over a day.
2. Compare each confirmed payment with the bank/provider statement. Match → **Reconcile** (a different person from the confirmer). No match → **Reverse** with a reason (owner) and investigate.
3. Direct customer-to-technician payments are self-reported by the technician; reconcile only after the customer or another source confirms. Never present them as verified transfers.
4. Provider callback mismatches appear in the payment's history as `callback_mismatch`; resolve with the provider before confirming manually.
5. End of day: trial balance balanced for every currency; `GET /platform/integrity` clean.

## Failed notifications
Metrics `duale_notification_deliveries_dead`; list `GET /platform/notifications/deliveries?status=Dead` (no message bodies). Causes: provider outage (retry after recovery), recipient has no phone/email (fix the profile; the in-app copy was always delivered), provider rejected credentials. Retry with `POST /platform/notifications/deliveries/{id}/retry`.

## Disputes
A technician or finance user raises a dispute on a payable or payment; payout is blocked while it is open. The decider (not the raiser) records the outcome and a resolution that references any refund/reversal posted separately. Policy for acceptable outcomes and time limits is a **business decision**.

## Data requests (access, correction, deletion)
Policy, legal basis and retention periods are **not decided**. Mechanics: identity and evidence files live in the private files volume referenced by `TechnicianDocuments`/`JobEvidence`; personal data also sits in `Users`, `Technicians`, `Customers`, `ServiceLocations`, notifications and audit rows. Financial and audit history must not be deleted (it is append-only by design); where deletion is owed, anonymise the person-identifying columns instead and record the request, decision and executor. Every such action is done by two people and logged.

## Release rollback
See release.md.
