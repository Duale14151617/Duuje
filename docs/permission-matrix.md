# Role and permission matrix

Generated from `src/Duale.Api/Data/Seed.cs` (re-generate when it changes). **These assignments are a starting point; the business must confirm them.**
Authorization is enforced on the server for every request: membership, active account, company status, role permission, and the company id in the URL. Hiding a button is not authorization.

| Permission | What it allows | `platform_admin` | `platform_finance` | `verification_officer` | `company_owner` | `dispatcher` | `supervisor` | `company_finance` | `auditor` |
|---|---|---|---|---|---|---|---|---|---|
| `company.read` | View company profile |  |  |  | ✔ | ✔ | ✔ | ✔ | ✔ |
| `company.manage` | Edit company profile |  |  |  | ✔ |  |  |  |  |
| `staff.manage` | Add/remove staff and roles |  |  |  | ✔ |  |  |  |  |
| `company.verify` | Decide company verification (platform) | ✔ |  | ✔ |  |  |  |  |  |
| `technician.verify` | Review technician documents and skills (platform) | ✔ |  | ✔ |  |  |  |  |  |
| `catalog.manage` | Manage trades/skills/service areas (platform) | ✔ |  |  |  |  |  |  |  |
| `audit.read` | Read the company audit trail |  |  |  | ✔ |  |  |  | ✔ |
| `relationship.read` | View technician relationships |  |  |  | ✔ | ✔ | ✔ |  | ✔ |
| `relationship.manage` | Invite, suspend, end technician relationships |  |  |  | ✔ |  |  |  |  |
| `customer.manage` | Manage customers and locations |  |  |  | ✔ | ✔ |  |  |  |
| `job.read` | View jobs, evidence and execution |  |  |  | ✔ | ✔ | ✔ | ✔ | ✔ |
| `job.manage` | Create, edit, cancel, reschedule jobs |  |  |  | ✔ | ✔ |  |  |  |
| `job.dispatch` | Offer, withdraw, reassign |  |  |  | ✔ | ✔ |  |  |  |
| `branch.manage` | Manage branches |  |  |  | ✔ |  |  |  |  |
| `user.support` | Reset another user's MFA (platform) | ✔ |  |  |  |  |  |  |  |
| `job.review` | Approve/return work, decide scope changes |  |  |  | ✔ |  | ✔ |  |  |
| `finance.read` | Read invoices, payables, payments, ledger, finance report |  |  |  | ✔ |  |  | ✔ | ✔ |
| `finance.terms` | Propose financial terms |  |  |  | ✔ | ✔ |  |  |  |
| `finance.terms.approve` | Approve financial terms |  |  |  | ✔ |  |  |  |  |
| `finance.invoice` | Issue invoices |  |  |  | ✔ |  |  | ✔ |  |
| `finance.payment` | Approve payables; initiate/confirm/fail payments |  |  |  | ✔ |  |  | ✔ |  |
| `finance.reconcile` | Reconcile confirmed payments |  |  |  | ✔ |  |  | ✔ |  |
| `finance.refund.request` | Request refunds |  |  |  | ✔ |  |  | ✔ |  |
| `finance.refund.approve` | Approve/reject refunds |  |  |  | ✔ |  |  |  |  |
| `finance.adjust` | Void invoices, reverse payments, cancel payables, decide disputes |  |  |  | ✔ |  |  |  |  |
| `report.read` | Operational reports |  |  |  | ✔ | ✔ | ✔ | ✔ | ✔ |
| `platform.finance` | Platform fees and subscription records (platform) |  | ✔ |  |  |  |  |  |  |
| `platform.oversight` | Platform overview, delivery queue, outbox queue, integrity check (platform) | ✔ | ✔ |  |  |  |  |  |  |
| `integration.manage` | Register integration accounts (metadata and secret names only) (platform) | ✔ |  |  |  |  |  |  |  |

Scope: `platform_admin` = platform, `platform_finance` = platform, `verification_officer` = platform, `company_owner` = company, `dispatcher` = company, `supervisor` = company, `company_finance` = company, `auditor` = company. Technicians are not a role: they act only on their own assignments, payables and profile.

## Separation of duties enforced in code
- Company verification / technician documents: nobody reviews their own company or documents.
- Work review: nobody reviews their own work.
- Financial terms: approver ≠ proposer.
- Payments: initiator ≠ confirmer; confirmer ≠ reconciler; reversal ≠ confirmer.
- Refunds: approver ≠ requester. Disputes: decider ≠ raiser.
- Exception: amounts ≤ `Finance:SelfApprovalLimit` (default 0 = no exceptions).
- Optional second factor per permission: `Security:MfaRequiredPermissions`.
