"""Access review: who needs attention (dormant logins, privileged roles without MFA, expired temporary passwords ...).

    python manage.py access_review           # print the review
    python manage.py access_review --email   # also email a summary to the verified user administrators

Run it on a schedule (monthly is a sensible start). Read-only and free of secrets. It is also available on the Users page."""
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from apps.accounts import access_review as ar
from apps.accounts.services import user_admin_emails
from apps.audit.services import record

TITLES = {
    "leaver_active": "Login still active for someone retired, discharged or deceased",
    "few_admins": "Fewer than two user administrators (a single locked-out admin would stop account management)",
    "privileged_no_mfa": "Privileged or administrator role without MFA",
    "temp_expired": "Temporary password expired unused (reset it or disable the account)",
    "never_signed_in": f"Never signed in after {ar.NEVER_USED_DAYS} days",
    "dormant": f"No sign-in for {ar.DORMANT_DAYS} days",
    "no_role": "Active account with no effective role",
    "ending_soon": f"Role ending within {ar.ENDING_DAYS} days",
    "email_unverified": "Email not verified (cannot use 'Forgot your password?')",
    "locked": "Locked accounts",
    "global_access": "Whole-system access (for information)",
}


def render(data):
    lines = [f"Access review, generated {data['generated_at']}",
             f"Accounts: {data['users']} ({data['active_users']} active). Items needing attention: {data['needs_attention']}", ""]
    for code, title in TITLES.items():
        f = data["findings"][code]
        if not f["count"]:
            continue
        lines.append(f"{title}: {f['count']}")
        lines += [f"  - {i}" for i in f["items"][:25]]
        if f["count"] > 25:
            lines.append(f"  ... and {f['count'] - 25} more (see the Users page, Access review)")
        lines.append("")
    if data["needs_attention"] == 0:
        lines.append("Nothing needs attention.")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Print the access review; with --email also send it to the verified user administrators."

    def add_arguments(self, parser):
        parser.add_argument("--email", action="store_true", help="email the summary to verified whole-system user administrators")

    def handle(self, *args, email=False, **opts):
        data = ar.review()
        text = render(data)
        self.stdout.write(text)
        sent = 0
        if email:
            for address in user_admin_emails():
                try:
                    sent += send_mail("Puntland Defence Forces HQ: access review", text, None, [address], fail_silently=False)
                except Exception as exc:
                    self.stderr.write(f"Could not email {address}: {exc}")
            self.stdout.write(f"Emailed {sent} administrator(s).")
        record("access.review", entity_type="access_review",
               metadata={"findings": {k: v["count"] for k, v in data["findings"].items()}, "via": "management_command", "emailed": sent})
