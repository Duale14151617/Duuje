# Ratings and verification: database changes without running migrations

This change adds two tables (`JobRatings`, `VerificationCodes`) and two columns (`Users.EmailVerifiedAt`, `Technicians.PhoneVerifiedAt`).

**You do not need to run any migration.** `src/Duale.Api/Data/SchemaPatches.cs` runs at startup on PostgreSQL, right after the EF migrations,
and creates anything missing (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). Deploy normally; check the Render log for errors on the first start.
- New or disposable database: the migrations create everything, the patches do nothing.
- Existing database: the patches add the new tables and columns.

Later model changes: add a statement to `SchemaPatches.cs` the same way. If you later commit real migrations, generate the baseline from the current model; the
patches then stay harmless.

## Verification codes need a provider
`/me/verify/email/request` and `/me/verify/phone/request` reply 503 until an email or SMS provider is registered (`INotificationProvider`, channel `email` or `sms`).
In Development the code is written to the log.

## Verified phone is required before an invitation
A company cannot invite a technician until that technician has verified their phone number (the API answers 409 with a message the dashboard shows). Changing the number clears the verification.

This needs an SMS provider (`INotificationProvider`, channel `sms`) so technicians can receive codes. Until one is registered, no technician can verify and every invitation is refused.
To pause the rule meanwhile, set `Verification__RequirePhoneForInvites=false` on the service; remove it (or set `true`) once SMS works.
