# Pilot and user acceptance

A running app is not evidence of readiness. Run these with **representative companies and technicians**, on staging, with real devices and a poor connection. Each script is signed off by the user, not by the developers.

| # | Script | Who | Pass when |
|---|---|---|---|
| 1 | Company onboarding → approval → staff, branches | company owner, verification officer | company approved; staff roles correct; nothing visible to other companies |
| 2 | Technician onboarding → documents → skill verification → relationship | technician, verifier, company | eligible in candidates only after verification and acceptance |
| 3 | Create job → candidates (explained) → offer → accept | dispatcher, technician | recommendation never assigns by itself; two overlapping jobs cannot both be confirmed |
| 4 | Field execution on a phone: status, photos, scope change, report | technician, supervisor | works on a 2G/flaky link; airplane-mode steps replay in order exactly once; customer details visible only after acceptance |
| 5 | Review: approve and return-for-correction paths | supervisor | returned work needs new evidence and a new report version |
| 6 | Company-paid settlement end to end | dispatcher, owner, finance ×2 | terms approved by a second person; payout confirmed by a second; reconciled by a third; technician sees it |
| 7 | Customer-paid (direct) settlement | technician, finance | self-reported flag shown; reconciliation required; no company ledger entry |
| 8 | Refund and dispute | finance, owner, technician | approval by another person; payout blocked during dispute |
| 9 | Reports match source records | owner, finance | every figure traceable to listed records; currencies separate |
| 10 | Notifications and reminders | all | in-app copy always; external channels only once a provider exists |

Record defects with severity; **release-blocking** = wrong money, data exposure, cross-company visibility, lost work, inability to complete a core workflow. Sign-off table: scenario, date, participants, result, defects, approver.
