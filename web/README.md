# Duale BuildLink web (company dashboard + platform admin)

React 18 + TypeScript + Vite. One app, two areas: `/companies/...` for company staff and `/admin/...` for platform staff
(shown only to users with platform permissions; the API enforces them regardless).

```
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://localhost:8080
npm run build    # type-check + production bundle in dist/
```
In production serve `dist/` and the API behind one HTTPS reverse proxy, with the API under `/api`.

Covers: sign in (with authenticator code), register, password recovery, MFA setup, companies, branches (with staff assignment),
staff, customers and locations (with service area), technician invitations, jobs with explainable candidate list and explicit
offers, notifications, and for platform staff: company verification queue, technician document review (documents open through
short-lived signed links), catalog and service areas, MFA reset support.

Not built yet: reports, finance, job execution (Phases 3-5). Not type-checked or run in the environment that produced it; run `npm run build` first.


## Technician registration
On the sign-up form choose **I'm a technician** (name, phone, email, password). The account is created, the technician profile is created (`POST /technicians/me`) and you land on `/technician`, where you claim skills, pick service areas, upload documents and accept company invitations. Existing users can use **Become a technician** in the menu to add a profile to their account.

**Invite link:** when a company invites an email that has no technician profile, it gets a copyable link (`/login?role=technician&email=...`) that opens the technician sign-up with the email filled in. The technician page also shows a 5-step progress checklist.

## More features
- **Technician workspace** (`/technician`): Profile, Jobs (accept/decline, status steps, evidence, scope changes, work report, job history), Availability, Earnings. Mirrors the mobile app and uses the same API.
- **Language:** English / Somali switch (top of sign-in, sidebar). Strings live in `src/i18n.tsx`; untranslated text falls back to English. Have a Somali speaker review the wording.
- **Company:** import technicians from CSV (`email` or `email,Employed` per line).
- **Platform admin:** select several pending documents or skills and approve or reject them together.
- **Reminders (API):** besides skill expiry, technicians are now reminded of expiring documents, and technicians plus the company's relationship managers of agreements about to end (`Reminders:SkillExpiryDays`, `Reminders:RelationshipDays`, default 14).

## Ratings and verification
- **Ratings:** after a job is approved, a reviewer can rate the technician 1-5 stars (once per job) from the company Jobs page. Technicians see their average and recent comments on their profile; companies see average and count next to each technician. Whether ratings from other companies should be visible to a company is a business decision.
- **Verification:** email (Security page) and phone (technician profile) are confirmed with a 6-digit code. Codes can only be delivered once an email/SMS provider is registered; see `docs/ops/migration-ratings-verification.md`. Verification is informational: it does not yet block invitations or jobs.
