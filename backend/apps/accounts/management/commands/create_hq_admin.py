import getpass
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, RoleAssignment, User
from apps.accounts.serializers import check_password_strength
from apps.audit.services import record
from apps.organization.models import OrganizationalUnit


class Command(BaseCommand):
    help = "Create the first headquarters administrator. Password is prompted (or ARMYHQ_ADMIN_PASSWORD)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--full-name", required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        hq = OrganizationalUnit.objects.filter(level="headquarters").first()
        role = Role.objects.filter(code="hq_admin").first()
        if not hq or not role:
            raise CommandError("Run `manage.py seed_reference_data` first.")
        username = opts["username"].lower()
        if User.objects.filter(username=username).exists():
            raise CommandError("That username already exists.")
        password = os.environ.get("ARMYHQ_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        try:
            check_password_strength(password)
        except Exception as exc:  # DRF ValidationError or Django one
            raise CommandError(f"Weak password: {exc}")
        user = User.objects.create_user(username, password=password, full_name=opts["full_name"],
                                        must_change_password=True)
        RoleAssignment.objects.create(user=user, role=role, org_unit=hq)
        record("user.bootstrap_admin", actor=user, entity_type="user", entity_id=user.pk,
               metadata={"via": "management_command"})
        self.stdout.write(self.style.SUCCESS(
            f"Created {username}. First login requires a password change and MFA enrolment."))
