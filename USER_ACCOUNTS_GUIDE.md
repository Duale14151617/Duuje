# Creating user accounts

1. **Users → Add user.** Type the person's real full name in *Full name*. The username fills in as `firstname.lastname`
   (for example `ali.warsame`). Usernames may contain only lowercase letters, digits, dots, underscores and dashes.
2. **Duplicate names.** If the name is taken, the form offers the next free choice: a middle initial (`ali.h.warsame`)
   or a number (`ali.warsame2`). Pick one of the buttons or type your own.
3. **Temporary password.** Leave the password box blank and the system generates a random one (for example `Kx7mPq-4tWn9d`). It is
   shown **once** on screen, so write it down or hand it over then. (You may type your own, at least 12 characters.) The account is
   created with *Must change password*, so the person must choose their own at first sign-in. An unused temporary password
   **expires after 7 days** (`TEMP_PASSWORD_DAYS`); the user page shows the date. If it expires, use *Reset password* and leave the
   prompt blank to generate a fresh one.
4. **Role and unit.** Open the new user (Users → click the name) and use *Assign role*: choose the role and the unit it
   applies to (and the service branch where the role needs one).
5. **Link the personnel record.** On the same page, under *Personnel record*, search by name or service number and
   press *Link record*. That person now gets the **My record** shortcut. (You can also set it from the person's own
   page under *Reporting line → Account*, or in bulk from the Reporting lines CSV.) One login per person and one
   person per login.
6. **Verify email (done by each user).** After first sign-in each user opens the account icon in the top-right corner,
   enters their email address and the 6-digit code sent to it. Until they do, "Forgot your password?" will not work for them.
   The user page shows a Verified / Not verified badge so you can follow up.

## Creating many accounts at once (CSV)

Users → **Import from CSV**. Download the template and fill one row per person:

| column | needed | meaning |
|---|---|---|
| `full_name` | yes | the person's real full name |
| `role` | yes | role code (the page lists them) |
| `unit` | yes | unit code the role applies to |
| `username` | no | blank = `firstname.lastname`, with a middle initial or number if taken |
| `email`, `branch`, `language` | no | `language` is `so` (default) or `en` |
| `service_number` | no | links the new login to that personnel record (enables *My record*) |

Press **Check file** first: nothing is created, every problem is listed by row. If the file is clean, **Create all accounts** creates
them all or none. The temporary passwords are shown **once** and can be downloaded as a CSV; hand each over privately. Limits: 50 rows
per file (each account needs a slow password hash), so upload large lists in batches. You can only give roles you hold yourself and
link people inside your own scope.

## Email (needed for verification and "Forgot your password?")

These features are **off** until outgoing email works, because without it the codes only print in the server log.

1. Choose a sender. On Render's free plan SMTP is blocked, so use **Brevo**: create a Brevo account, verify a sender address, and create
   an API key. Any normal SMTP provider also works elsewhere.
2. In the Render dashboard set: `BREVO_API_KEY` (or `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`),
   `DEFAULT_FROM_EMAIL` (the verified sender), then `EMAIL_VERIFICATION_ENABLED=1` and `PASSWORD_FORGOT_ENABLED=1`.
3. In the Render shell run `python manage.py check_email` to see what is switched on and what is still missing, and
   `python manage.py check_email you@example.com` to send yourself a test message.
4. Sign in, open the account icon and verify your own address first, to prove the whole path works before asking everyone else.

## Keeping administrator access safe

- **MFA is compulsory for administrators.** Anyone whose role can manage accounts, assign roles or override module switches must enrol an
  authenticator app, even if their role was not marked "privileged".
- **Alert on privileged grants.** Whenever a privileged role (or one that can manage accounts) is given to someone, the grant is written to
  the audit log (`role_assignment.privileged`) and emailed to the *other* whole-system user administrators. Only addresses that were
  verified through the account icon receive it, so each administrator should verify their email. (Needs working email, see above.)
- **At least two administrators.** The system already refuses to remove the last one. The access review also warns when there are fewer than
  two, because one locked-out administrator would stop all account management.

## Access review (monthly)

Users → **Access review** lists the accounts that need a decision: fewer than two administrators, privileged roles without MFA, temporary
passwords that expired unused, accounts that never signed in (14+ days) or have been idle 90 days, active accounts with no role, roles ending
within 30 days, unverified emails, locked accounts, and everyone with whole-system access. Opening it is audited.

To get it by email every month, run `python manage.py access_review --email` on a schedule. It sends the summary to the verified
whole-system administrators and writes an audit event. On Render this needs a **Cron Job** service (a paid feature); on the free plan
run the command by hand in the Render shell, or from any scheduler you control.

## Finding people on the Users page

Filter by status, has a role, email verified, linked to a personnel record (More filters), and never signed in. The columns show role
count, email status, the linked record and last sign-in, so you can see who still needs to verify their email or has no role.

## When someone leaves service

- **Death:** confirming a death record closes the person's login (already the case).
- **Retirement or discharge:** changing the status to Retired or Discharged (directly, or through an approved change request) now also
  disables the linked login and signs out every session, as it already ended their command appointments. The link to the personnel record
  is kept, and an audit event `personnel.account_closed` is written. Other statuses (on leave, suspended, jailed) do **not** close it.
- **Only administrator:** if the login belongs to the only user administrator, it is left on so nobody is locked out of account management.
  The event `personnel.account_close_blocked` is written and the access review lists the person under "Login still active for someone who
  left service". Appoint a second administrator, then disable the account.
- If a person returns to service, an administrator must switch the login back on (Users, then the user, then Enable).
