from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.security import clear_second_factors
from apps.accounts.services import revoke_user_sessions
from apps.audit.services import record


class Command(BaseCommand):
    help = ("Remove the authenticator, backup codes and passkeys of one account, for the day the only administrator has lost their phone. "
            "Run it on the server (Render shell, docker exec): having that access is the proof of ownership. "
            "The password is NOT changed; at the next sign-in the person enrols a new authenticator.")

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        user = User.objects.filter(username=opts["username"].strip().lower()).first()
        if user is None:
            raise CommandError("No account with that username.")
        user.mfa_enabled = False
        user.mfa_secret_enc = ""
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["mfa_enabled", "mfa_secret_enc", "failed_login_count", "locked_until", "updated_at"])
        clear_second_factors(user)
        revoke_user_sessions(user)
        record("user.reset_mfa", actor=None, entity_type="user", entity_id=user.pk, metadata={"via": "management command"})
        self.stdout.write(self.style.SUCCESS(
            f"Authenticator, backup codes and passkeys removed for {user.username}. Sign in with your password and enrol a new authenticator."))
