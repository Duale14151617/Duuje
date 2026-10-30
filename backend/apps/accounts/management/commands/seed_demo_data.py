"""Synthetic demo users and units. NEVER use with real data. Explicit demo mode only."""
import os

from django.conf import settings
from django.core.management import call_command
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

# Non-commanding member: sees only their own record and the people who report to them (see _demo_team).
# Taliye Urur / Guuto stand-in: records attendance and makes the unit situation report for the synthetic unit.
DEMO_USERS.setdefault("bari.commander", ("Bari Unit Commander (Demo)", "unit_commander", "BARI-ARMY-DEMO-A", None))
DEMO_USERS.setdefault("bari.member", ("Bari Member (Demo Person 03)", "member", "BARI-ARMY-DEMO-A", None))
# Finance duties are split between four roles (the service layer refuses self-approval), so the payroll flow needs one account each.
DEMO_USERS.setdefault("payroll.officer", ("Payroll Officer", "payroll_officer", "HQ", None))
DEMO_USERS.setdefault("payroll.approver", ("Payroll Approver", "payroll_approver", "HQ", None))
DEMO_USERS.setdefault("payment.officer", ("Payment Execution Officer", "payment_officer", "HQ", None))
DEMO_USERS.setdefault("payment.reconciler", ("Payment Reconciliation Officer", "payment_reconciler", "HQ", None))
DEMO_USERS.setdefault("president", ("President / Commander-in-Chief", "command_authority", "HQ", None))
DEMO_USERS.setdefault("commander", ("Commander of the Puntland Defense Forces", "command_authority", "HQ", None))

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


# Health Department of each Army regional command: a head who manages the department's people, and a reporting officer.
for _name in ("Bari", "Nugaal", "Mudug", "Sanaag"):  # the four Army regional commands (Karkaar is within Bari)
    _r = _name.upper()
    DEMO_USERS.setdefault(f"{_name.lower()}.health", (f"{_name} Health Department Head", "unit_admin", f"{_r}-ARMY-HEALTH", None))
    DEMO_USERS.setdefault(f"{_name.lower()}.healthofficer", (f"{_name} Health Reporting Officer", "reporting_officer", f"{_r}-ARMY-HEALTH", None))

# Regional finance pays that region's SALARIES (headquarters prepares and approves the monthly run). Four accounts per Army regional command, one
# per step so nobody approves their own work: prepare, authorize, send (outside the system) and reconcile. Roles are assigned at the command.
# A read-only auditor sits at the first battalion (Urur) of each command. Karkaar is within Bari.
for _name in ("Bari", "Nugaal", "Mudug", "Sanaag"):
    _k, _r = _name.lower(), _name.upper()
    DEMO_USERS.setdefault(f"{_k}.fin.prepare", (f"{_name} Finance: Prepare Payments", "payroll_officer", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.fin.authorize", (f"{_name} Finance: Authorize Payments", "payroll_approver", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.fin.pay", (f"{_name} Finance: Send Payments", "payment_officer", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.fin.reconcile", (f"{_name} Finance: Reconcile", "payment_reconciler", f"{_r}-ARMY", None))
    DEMO_USERS.setdefault(f"{_k}.audit.u1", (f"{_name} Battalion 1 Finance Auditor", "auditor", f"{_r}-ARMY-G1-U1", None))

# Roles that had no demo account. Survivor benefits need two people (one registers, another verifies), so there are two survivor officers.
# Arrears need a second payroll officer: one records the claim, a different one verifies it, then the approver decides.
DEMO_USERS.setdefault("payroll.officer2", ("Payroll Officer 2", "payroll_officer", "HQ", None))
DEMO_USERS.setdefault("structure.approver", ("Structure Approver", "structure_approver", "HQ", None))
DEMO_USERS.setdefault("survivor.officer", ("Survivor-Benefit Officer", "survivor_officer", "HQ", None))
DEMO_USERS.setdefault("survivor.verifier", ("Survivor-Benefit Verifier", "survivor_officer", "HQ", None))
# Taliye Qaybeed: one per Army regional command (assigned at the command, view and review of what its Guuto and Urur post).
for _name in ("Bari", "Nugaal", "Mudug", "Sanaag"):
    DEMO_USERS.setdefault(f"{_name.lower()}.regcommander", (f"{_name} Regional Commander (Taliye Qaybeed)", "regional_commander", f"{_name.upper()}-ARMY", None))

# One weapons custodian per Army regional command (Karkaar is within Bari): register, issue and take back weapons in that region only.
for _name in ("Bari", "Nugaal", "Mudug", "Sanaag"):
    DEMO_USERS.setdefault(f"{_name.lower()}.weapons", (f"{_name} Weapons Custodian", "weapons_custodian", f"{_name.upper()}-ARMY", None))


# Vehicle register: the transport officer keeps it, a different person approves disposals.
DEMO_USERS.setdefault("transport.officer", ("Transport Officer", "transport_officer", "BARI", None))
DEMO_USERS.setdefault("vehicle.approver", ("Vehicle Disposal Approver", "vehicle_disposal_approver", "HQ", None))


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
        # The supplied Army structure (Taliska Guud, directorates, Qaybta commands). Synthetic deployments only: a real
        # deployment applies it deliberately with `manage.py apply_army_structure` (dry run first).
        call_command("apply_army_structure", "--apply", stdout=self.stdout)
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
        self._demo_team()
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

    def _demo_team(self):
        """Reporting line for the member demo: Demo Person 03 (PA-10) supervises 01 (PA-03) and 02 (PA-05); the
        `bari.member` login belongs to person 03, so it sees those three records and nobody else."""
        by_no = {p.service_number: p for p in Personnel.objects.filter(service_number__startswith="DEMO-")}
        boss, a, b = by_no.get("DEMO-0003"), by_no.get("DEMO-0001"), by_no.get("DEMO-0002")
        user = User.objects.filter(username="bari.member").first()
        if not (boss and a and b and user):
            return
        Personnel.objects.filter(pk__in=[a.pk, b.pk]).update(supervisor=boss)
        if not Personnel.objects.filter(account=user).exists():
            Personnel.objects.filter(pk=boss.pk).update(account=user)

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
        self._demo_weapons_ammunition(unit)

    def _demo_weapons_ammunition(self, unit):
        """Synthetic weapon register entries and ammunition ledger opening balances (demo only; serials are fake)."""
        from apps.logistics.models import Asset, InventoryCategory, StockLine, StockTransaction
        from apps.weapons.models import WeaponDetail
        weapons = {  # category code: (weapon type, make/model, caliber, how many)
            "weapons_rifles": ("Assault rifle", "Demo rifle", "7.62x39 mm", 3),
            "weapons_pistols": ("Pistol", "Demo pistol", "9 mm", 2),
            "weapons_machine_guns": ("Machine gun", "Demo machine gun", "7.62x54R mm", 1),
        }
        ammo = {"ammunition_762x39": 3000, "ammunition_9mm": 800, "ammunition_762x54": 500}  # category code: opening balance (rounds)
        InventoryCategory.objects.filter(code__in=[*weapons, *ammo]).update(approval_status="approved")
        for code, (wtype, make, cal, n) in weapons.items():
            cat = InventoryCategory.objects.get(code=code)
            for i in range(1, n + 1):
                asset, _ = Asset.objects.get_or_create(category=cat, identifier=f"DEMO-{code[8:12].upper()}-{i:03d}",
                                                       defaults={"org_unit": unit, "description": "Synthetic demo weapon"})
                WeaponDetail.objects.get_or_create(asset=asset, defaults={"weapon_type": wtype, "make_model": make, "caliber": cal})
        for code, qty in ammo.items():
            cat = InventoryCategory.objects.get(code=code)
            line, created = StockLine.objects.get_or_create(category=cat, org_unit=unit, defaults={"uom": "rounds", "quantity": qty})
            if created:
                StockTransaction.objects.create(stock_line=line, kind="opening", delta=qty, balance_after=qty,
                                                reason="Synthetic demo opening balance", actor_username="demo")
        self._demo_soldier_holdings(unit)

    def _demo_soldier_holdings(self, unit):
        """Give two demo soldiers a weapon and some rounds, so the holdings report has something to show (demo only)."""
        from django.db.models import F
        from apps.logistics.models import Asset, StockLine, StockTransaction
        from apps.weapons.models import SoldierRounds, WeaponCustody
        if SoldierRounds.objects.exists() or WeaponCustody.objects.exists():
            return
        people = list(Personnel.objects.filter(service_number__in=["DEMO-0001", "DEMO-0002"], org_unit__path__startswith=unit.path)
                      .select_related("org_unit").order_by("service_number"))
        rifles = list(Asset.objects.filter(category__code="weapons_rifles", identifier__startswith="DEMO-", status="in_stock").order_by("identifier"))
        line = StockLine.objects.filter(category__code="ammunition_762x39", org_unit=unit).first()
        for n, person in enumerate(people):
            if n < len(rifles):
                a = rifles[n]
                WeaponCustody.objects.create(asset=a, personnel=person, issued_by_username="demo", authority_ref="Demo order 1/2026",
                                             issue_condition="serviceable", status_before="in_stock")
                Asset.objects.filter(pk=a.pk).update(status="issued", issued_to_unit=person.org_unit)
            if line is not None:
                issued, spent = 120 - 30 * n, 20 * (n + 1)
                line.refresh_from_db()
                txn = StockTransaction.objects.create(stock_line=line, kind="issue", delta=-issued, balance_after=line.quantity - issued,
                                                      reason=f"Issued to {person.service_number}", external_ref=f"DEMO-ISS-{n + 1}", actor_username="demo")
                StockLine.objects.filter(pk=line.pk).update(quantity=F("quantity") - issued, version=F("version") + 1)
                SoldierRounds.objects.create(personnel=person, stock_line=line, kind="issue", delta=issued, reference=f"DEMO-ISS-{n + 1}",
                                           store_transaction=txn, actor_username="demo")
                SoldierRounds.objects.create(personnel=person, stock_line=line, kind="expended", delta=-spent, note="Demo range practice", actor_username="demo")
