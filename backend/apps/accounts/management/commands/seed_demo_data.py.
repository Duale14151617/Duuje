"""Synthetic demo users and units. NEVER use with real data. Explicit demo mode only."""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, RoleAssignment, User
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as personnel_services
from apps.personnel.models import Personnel
from apps.ranks.models import Rank

# username: (full name, role, org unit code, branch code or None)
DEMO_USERS = {
    "demo.hqadmin": ("Demo HQ Administrator", "hq_admin", "HQ", None),
    "demo.hqreports": ("Demo HQ Reporting", "hq_reporting", "HQ", None),
    "demo.auditor": ("Demo Auditor", "auditor", "HQ", None),
    "demo.bari.chief": ("Demo Bari Chief", "regional_chief", "BARI", None),
    "demo.nugaal.chief": ("Demo Nugaal Chief", "regional_chief", "NUGAAL", None),
    "demo.bari.armyadmin": ("Demo Bari Army Admin", "branch_admin", "BARI", "ARMY"),
    "demo.bari.unitadmin": ("Demo Bari Unit Admin", "unit_admin", "BARI-ARMY-DEMO-A", None),
    "demo.bari.reporter": ("Demo Bari Reporting Officer", "reporting_officer", "BARI-ARMY", None),
    "demo.logistics": ("Demo Logistics Custodian", "logistics_custodian", "BARI", None),
    "demo.restricted": ("Demo Restricted Custodian", "restricted_custodian", "BARI-ARMY", None),
    "demo.reviewer": ("Demo Logistics Reviewer", "logistics_reviewer", "HQ", None),
    "demo.trainer": ("Demo Training Administrator", "training_admin", "BARI", None),
    "demo.readonly": ("Demo Read-only", "read_only", "MUDUG", None),
}


class Command(BaseCommand):
    help = "Create synthetic demo accounts. Password from ARMYHQ_DEMO_PASSWORD (min 12 chars)."

    @transaction.atomic
    def handle(self, *args, **opts):
        # Production DEBUG stays off. This separate, explicit flag permits only synthetic demo fixtures
        # on a deliberately configured demo deployment; never enable it for real operational data.
        demo_mode = os.environ.get("ARMYHQ_DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")
        if not settings.DEBUG and not demo_mode:
            raise CommandError("Demo data is disabled. Set ARMYHQ_DEMO_MODE=1 only for a synthetic demo deployment.")
        password = os.environ.get("ARMYHQ_DEMO_PASSWORD", "")
        if len(password) < 12:
            raise CommandError("Set ARMYHQ_DEMO_PASSWORD (12+ characters).")
        army_cmd = OU.objects.filter(code="BARI-ARMY").first()
        if not army_cmd:
            raise CommandError("Run `manage.py seed_reference_data` first.")
        OU.objects.filter(code="BARI-ARMY-DEMO-A").first() or OU.objects.create(
            code="BARI-ARMY-DEMO-A", name_en="Synthetic Unit A", name_so="Cutubka Tijaabada A",
            level=OU.Level.UNIT, parent=army_cmd)
        for username, (full, role_code, unit_code, branch_code) in DEMO_USERS.items():
            user = User.objects.filter(username=username).first()
            if user:
                if os.environ.get("ARMYHQ_DEMO_RESET", "0") == "1":
                    user.set_password(password)
                    user.failed_login_count = 0
                    user.locked_until = None
                    user.mfa_enabled = False
                    user.mfa_secret_enc = ""
                    user.save(update_fields=[
                        "password", "failed_login_count", "locked_until",
                        "mfa_enabled", "mfa_secret_enc", "updated_at",
                    ])
                continue
            user = User.objects.create_user(username, password=password, full_name=full)
            RoleAssignment.objects.create(
                user=user, role=Role.objects.get(code=role_code), org_unit=OU.objects.get(code=unit_code),
                branch=ServiceBranch.objects.get(code=branch_code) if branch_code else None)
        self._demo_personnel(army_cmd)
        self._demo_logistics_training()
        self.stdout.write(self.style.SUCCESS(
            "Synthetic demo users ready. Privileged roles must enrol MFA on first login."))

    def _demo_personnel(self, army_cmd):
        """Add a few clearly fake people (demo only). Ranks are the official approved Army ranks."""
        unit = OU.objects.get(code="BARI-ARMY-DEMO-A")
        if Personnel.objects.filter(org_unit=unit).exists():
            return
        for i in range(1, 9):
            rank = Rank.objects.get(branch=army_cmd.branch, code=("PA-01", "PA-03", "PA-05", "PA-10")[i % 4])
            personnel_services.create_personnel(
                None, full_name=f"Demo Person {i:02d}", phone=f"+25290000{i:04d}", service_number=f"DEMO-{i:04d}",
                org_unit=unit, rank=rank, status="active", effective_date=None, reason="Synthetic demo record")

    def _demo_logistics_training(self):
        """Approve two harmless demo categories directly (DEBUG only) and add synthetic stock and assets."""
        from apps.logistics.models import Asset, InventoryCategory, StockLine
        InventoryCategory.objects.filter(code__in=["general_supplies", "vehicles"]).update(approval_status="approved")
        unit = OU.objects.get(code="BARI-ARMY-DEMO-A")
        supplies = InventoryCategory.objects.get(code="general_supplies")
        vehicles = InventoryCategory.objects.get(code="vehicles")
        StockLine.objects.get_or_create(category=supplies, org_unit=unit, defaults={"quantity": 40, "reorder_level": 50, "uom": "boxes"})
        for i in range(1, 4):
            Asset.objects.get_or_create(category=vehicles, identifier=f"DEMO-VEH-{i:03d}",
                                        defaults={"org_unit": unit, "description": "Synthetic demo vehicle"})
