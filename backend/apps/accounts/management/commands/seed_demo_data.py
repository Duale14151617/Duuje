"""Synthetic demo users and units. NEVER use with real data. Explicit demo mode only."""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction

from apps.accounts.models import Role, RoleAssignment, User
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as personnel_services
from apps.personnel.models import Personnel
from apps.ranks.models import Rank

# username: (full name, role, org unit code, branch code or None)
# Usernames have no "demo." prefix. Older deployments that already have "demo.<name>" accounts are renamed in place below.
DEMO_USERS = {
    "hqadmin": ("HQ Administrator", "hq_admin", "HQ", None),
    "superadmin": ("Super Administrator", "super_admin", "HQ", None),
    "hqreports": ("HQ Reporting", "hq_reporting", "HQ", None),
    "auditor": ("Auditor", "auditor", "HQ", None),
    "bari.chief": ("Bari Chief", "regional_chief", "BARI", None),
    "nugaal.chief": ("Nugaal Chief", "regional_chief", "NUGAAL", None),
    "bari.armyadmin": ("Bari Army Admin", "branch_admin", "BARI", "ARMY"),
    "bari.unitadmin": ("Bari Unit Admin", "unit_admin", "BARI-ARMY-DEMO-A", None),
    "bari.reporter": ("Bari Reporting Officer", "reporting_officer", "BARI-ARMY", None),
    "logistics": ("Logistics Custodian", "logistics_custodian", "BARI", None),
    "restricted": ("Restricted Custodian", "restricted_custodian", "BARI-ARMY", None),
    "reviewer": ("Logistics Reviewer", "logistics_reviewer", "HQ", None),
    "trainer": ("Training Administrator", "training_admin", "BARI", None),
    "readonly": ("Read-only", "read_only", "MUDUG", None),
}

DEMO_USERS.setdefault("president", ("President / Commander-in-Chief", "command_authority", "HQ", None))
DEMO_USERS.setdefault("commander", ("Commander of the Puntland Defense Forces", "command_authority", "HQ", None))
if settings.POLICE_MODULE_ENABLED:  # Police pilot demo accounts; each is limited to the POLICE branch
    DEMO_USERS.setdefault("bari.policeadmin", ("Bari Police Admin", "branch_admin", "BARI", "POLICE"))
    DEMO_USERS.setdefault("bari.policepers", ("Bari Police Personnel Admin", "unit_admin", "BARI-POLICE-PERS", "POLICE"))
    DEMO_USERS.setdefault("bari.cid", ("Bari CID Officer", "cid_officer", "BARI-POLICE-CID", "POLICE"))

# The other regions get the same regional set Bari has (chief, branch admin, unit admin, reporter, custodians, trainer).
OTHER_REGIONS = ("Karkaar", "Nugaal", "Mudug")
for _name in OTHER_REGIONS:
    _r, _k = _name.upper(), _name.lower()
    DEMO_USERS.setdefault(f"{_k}.chief", (f"{_name} Chief", "regional_chief", _r, None))
    DEMO_USERS.setdefault(f"{_k}.armyadmin", (f"{_name} Army Admin", "branch_admin", _r, "ARMY"))
    DEMO_USERS.setdefault(f"{_k}.unitadmin", (f"{_name} Unit Admin", "unit_admin", f"{_r}-ARMY-DEMO-A", None))
    DEMO_USERS.setdefault(f"{_k}.reporter", (f"{_name} Reporting Officer", "reporting_officer", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.logistics", (f"{_name} Logistics Custodian", "logistics_custodian", _r, None))
    DEMO_USERS.setdefault(f"{_k}.restricted", (f"{_name} Restricted Custodian", "restricted_custodian", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.trainer", (f"{_name} Training Administrator", "training_admin", _r, None))


if settings.POLICE_MODULE_ENABLED:  # one CID officer per region, limited to that region's CID unit
    for _name in OTHER_REGIONS:
        DEMO_USERS.setdefault(f"{_name.lower()}.cid", (f"{_name} CID Officer", "cid_officer", f"{_name.upper()}-POLICE-CID", "POLICE"))
    # HQ CID officer: one assignment per regional CID unit, so it reaches CID records in every region and nothing else
    # (no other Police units, no Army). A tuple of unit codes means "one assignment per unit".
    DEMO_USERS.setdefault("hq.cid", ("HQ CID Officer", "cid_officer",
                                     tuple(f"{_r.upper()}-POLICE-CID" for _r in ("Bari",) + OTHER_REGIONS), "POLICE"))


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
        for region in OTHER_REGIONS:  # one synthetic unit per region so each region's unit admin has a unit
            region_army = OU.objects.filter(code=f"{region.upper()}-ARMY").first()
            if region_army:
                OU.objects.filter(code=f"{region.upper()}-ARMY-DEMO-A").first() or OU.objects.create(
                    code=f"{region.upper()}-ARMY-DEMO-A", name_en="Synthetic Unit A", name_so="Cutubka Tijaabada A",
                    level=OU.Level.UNIT, parent=region_army)
        for username, (full, role_code, unit_code, branch_code) in DEMO_USERS.items():
            multi = not isinstance(unit_code, str)  # several units: one role assignment per unit
            codes = [c for c in ([unit_code] if not multi else unit_code) if OU.objects.filter(code=c).exists()]
            if not codes:
                continue  # reference data for this region is missing; skip rather than fail the whole deploy
            legacy = User.objects.filter(username=f"demo.{username}").first()
            if legacy and not User.objects.filter(username=username).exists():
                legacy.username = username  # keep role assignment, password and MFA enrolment
                legacy.full_name = full
                legacy.save(update_fields=["username", "full_name", "updated_at"])
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
                if not multi:
                    continue
            else:
                user = User.objects.create_user(username, password=password, full_name=full)
            role = Role.objects.get(code=role_code)
            branch = ServiceBranch.objects.get(code=branch_code) if branch_code else None
            if multi:  # drop any earlier Headquarters-wide assignment: this account is limited to the listed units
                RoleAssignment.objects.filter(user=user, role=role, org_unit__level=OU.Level.HQ).delete()
            for code in codes:
                RoleAssignment.objects.get_or_create(user=user, role=role, org_unit=OU.objects.get(code=code), branch=branch)
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
