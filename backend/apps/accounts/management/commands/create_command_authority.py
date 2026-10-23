"""Create an account holding the command_authority role (the President / Commander-in-Chief or the Commander of the
Puntland Defense Forces). Access is by role, not by rank. Read-only, HQ-wide, Army and Police, never CID.

  python manage.py create_command_authority --username president --full-name "Name"

The password is prompted (or ARMYHQ_ADMIN_PASSWORD); the first login forces a password change and MFA enrolment.
Run once per person: do not share one account between the two appointments.
"""
import getpass
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, RoleAssignment, User
from apps.accounts.serializers import check_password_strength
from apps.audit.services import record
from apps.organization.models import OrganizationalUnit


class Command(BaseCommand):
    help = "Create a command_authority account (run seed_reference_data first)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--full-name", required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        hq = OrganizationalUnit.objects.filter(level="headquarters").first()
        role = Role.objects.filter(code="command_authority").first()
        if not hq or not role:
            raise CommandError("Run `manage.py seed_reference_data` first.")
        username = opts["username"].lower()
        if User.objects.filter(username=username).exists():
            raise CommandError("That username already exists.")
        password = os.environ.get("ARMYHQ_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        try:
            check_password_strength(password)
        except Exception as exc:
            raise CommandError(f"Weak password: {exc}")
        user = User.objects.create_user(username, password=password, full_name=opts["full_name"], must_change_password=True)
        RoleAssignment.objects.create(user=user, role=role, org_unit=hq)
        record("user.create_command_authority", actor=user, entity_type="user", entity_id=user.pk,
               metadata={"via": "management_command"})
        self.stdout.write(self.style.SUCCESS(f"Created {username} with the command_authority role. First login needs a password change and MFA."))
