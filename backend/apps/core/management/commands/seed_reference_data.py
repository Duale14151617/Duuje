"""Idempotent seed of system reference data: permissions, roles, branches, organization, official Army ranks, template.

Safe to re-run. Roles/permissions are system-defined and are re-synced; organization units
and ranks are only created if missing, so administrator edits and rank approvals are kept.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Permission, Role
from django.utils import timezone

from apps.organization.models import DesignationRule, SpecialistDesignation, UnitType
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.reference import ensure_reference, tag_regional_army_commands
from apps.personnel.models import Personnel
from apps.ranks.catalogue import apply_official_ranks
from apps.organization.models import ServiceBranch
from apps.ranks.models import Rank
from apps.logistics.models import InventoryCategory
from apps.training.models import Course
from apps.workflows.models import ReportType

PERMISSIONS = {
    "users.view": "View user accounts",
    "users.manage": "Create, edit, disable user accounts",
    "roles.assign": "Assign and revoke scoped roles",
    "org.view": "View organization structure in scope",
    "org.manage": "Change organization structure in scope",
    "ranks.view": "View rank catalogue",
    "ranks.manage": "Edit rank catalogue entries",
    "ranks.approve": "Approve rank catalogue entries",
    "audit.view": "Read audit events",
    "dashboard.view": "See the dashboard",
    "personnel.view": "View personnel records in scope",
    "personnel.manage": "Create/edit personnel, transfers, rank and status changes in scope",
    "personnel.import": "Import personnel from CSV in scope",
    "personnel.export": "Export personnel to CSV in scope (also needs PERSONNEL_EXPORT_ENABLED)",
    "reports.view": "View requests/reports in scope",
    "reports.submit": "Prepare and submit requests/reports in scope",
    "reports.review": "Review, approve, reject or return reports in scope",
    "reports.summary": "See approved regional/headquarters summaries in scope",
    "reports.export": "Export summaries (also needs REPORT_EXPORT_ENABLED)",
    "reports.configure": "Configure request/report types",
    "logistics.view": "View stock and assets (non-restricted categories) in scope",
    "logistics.manage": "Receive/issue/transfer stock and manage assets in scope",
    "logistics.restricted": "Separately view/manage RESTRICTED equipment categories in scope",
    "logistics.reconcile": "Run stock and asset reconciliations in scope",
    "logistics.report": "See logistics summaries in scope",
    "logistics.configure": "Create and edit inventory categories",
    "logistics.approve": "Approve (institutionally review) inventory categories",
    "logistics.restricted_approve": "Approve RESTRICTED inventory categories",
    "training.view": "View training records in scope",
    "training.manage": "Enrol people and update training records in scope",
    "training.report": "See training summaries in scope",
    "training.configure": "Create and edit the course catalogue",
    # 2.0. Analytics only ever returns sections the holder already has the underlying permission for.
    "analytics.view": "Open analytics (each section still needs its own report/personnel/logistics/training permission)",
    "integrations.view": "View integration clients and their call log (headquarters)",
    "integrations.manage": "Create, change, rotate and revoke integration clients (headquarters)",
    "org.structure_propose": "Propose and submit changes to organizational levels and strength standards (headquarters)",
    "org.structure_approve": "Approve or reject proposed structure changes (headquarters); cannot approve one's own proposal",
}
# Never granted to administrators by default (reports.configure is not sensitive, so hq_admin keeps it).
SENSITIVE_PREFIXES = ("personnel.", "reports.view", "reports.submit", "reports.review", "reports.summary", "reports.export",
                      "logistics.view", "logistics.manage", "logistics.restricted", "logistics.reconcile",
                      "logistics.report", "logistics.approve", "training.view", "training.manage", "training.report", "analytics.",
                      "org.structure_approve")
REPORT_TYPES = [  # code, kind, name_en, name_so, figure keys
    ("monthly_admin_report", "report", "Monthly administrative report", "Warbixinta maamul ee bishii",
     ["personnel_strength", "personnel_on_leave", "personnel_in_training"]),
    ("transfer_request", "request", "Personnel transfer request", "Codsi wareejin shaqaale", []),
    ("training_request", "request", "Training request", "Codsi tababar", []),
]
BASIC = ["dashboard.view", "org.view", "ranks.view"]
# code: (name_en, name_so, privileged, requires_branch, allowed_levels, permissions)
ROLES = {
    "hq_admin": ("Headquarters administrator", "Maamulaha Xarunta Guud", True, False, ["headquarters"],
                 [c for c in PERMISSIONS if not c.startswith(SENSITIVE_PREFIXES)]),
    "hq_reporting": ("Headquarters reporting user", "Isticmaalaha warbixinta Xarunta", False, False,
                     ["headquarters"], BASIC + ["personnel.view", "personnel.export", "reports.view", "reports.summary", "reports.export"]),
    "regional_chief": ("Regional chief", "Taliyaha gobolka", True, False, ["region"],
                       BASIC + ["personnel.view", "personnel.manage", "personnel.export", "reports.view", "reports.review",
                              "reports.summary", "reports.export"]),
    "branch_admin": ("Branch administrator", "Maamulaha laanta", True, True, ["region", "branch_command"],
                     BASIC + ["org.manage", "personnel.view", "personnel.manage", "personnel.import", "reports.view",
                      "reports.submit", "reports.review", "reports.summary"]),
    "unit_admin": ("Unit administrator", "Maamulaha cutubka", False, False, ["unit", "branch_command"],
                   BASIC + ["org.manage", "personnel.view", "personnel.manage", "reports.view", "reports.submit"]),
    "reporting_officer": ("Reporting officer", "Sarkaalka warbixinta", False, False, [],
                          BASIC + ["personnel.view", "reports.view", "reports.submit"]),
    "logistics_custodian": ("Logistics custodian", "Ilaaliyaha saadka", False, False, [],
                            ["dashboard.view", "org.view"]),
    "training_admin": ("Training administrator", "Maamulaha tababarka", False, False, [],
                       ["dashboard.view", "org.view"]),
    "restricted_custodian": ("Restricted equipment custodian", "Ilaaliyaha qalabka xaddidan", True, False, [],
                             ["dashboard.view", "org.view", "logistics.view", "logistics.manage",
                              "logistics.restricted", "logistics.reconcile", "logistics.report"]),
    "logistics_reviewer": ("Institutional logistics reviewer", "Dib-u-eegaha saadka hay'adda", True, False,
                           ["headquarters"], ["dashboard.view", "org.view", "logistics.approve",
                                              "logistics.restricted_approve"]),
    "structure_approver": ("Structure approver", "Ansixiyaha qaab-dhismeedka", True, False, ["headquarters"],
                           ["dashboard.view", "org.view", "org.structure_approve"]),
    "auditor": ("Auditor", "Hubiyaha", True, False, ["headquarters"], ["dashboard.view", "org.view", "audit.view"]),
    "read_only": ("Read-only user", "Isticmaale akhrin oo keliya", False, False, [],
                  BASIC + ["personnel.view", "reports.view"]),
}
BRANCHES = [("ARMY", "Army", "Ciidanka Dhulka"), ("NAVY", "Navy", "Ciidanka Badda"), ("POLICE", "Police", "Booliska")]
REGIONS = ["Bari", "Karkaar", "Nugaal", "Mudug"]

# Army ranks live in apps/ranks/catalogue.py (the 16 official Puntland Army ranks, as supplied).
# The organizational template lives in apps/organization/reference.py.


# Extra grants per role (applied on top of the tuples above).
EXTRA = {
    "hq_admin": ["logistics.configure", "training.configure"],
    "hq_reporting": ["logistics.report", "training.report", "analytics.view"],
    "regional_chief": ["logistics.view", "logistics.report", "training.view", "training.report", "analytics.view"],
    "branch_admin": ["logistics.view", "logistics.report", "training.view", "training.report", "analytics.view"],
    "unit_admin": ["logistics.view", "training.view"],
    "logistics_custodian": ["logistics.view", "logistics.manage", "logistics.reconcile", "logistics.report"],
    "training_admin": ["training.view", "training.manage", "training.report", "training.configure"],
}
CATEGORIES = [  # code, kind, restricted, name_en, name_so  (seeded as DRAFT; nothing weapon-specific is seeded)
    ("general_supplies", "stock", False, "General supplies", "Saadka guud"),
    ("uniforms_clothing", "stock", False, "Uniforms and clothing", "Maryo iyo dharka"),
    ("vehicles", "asset", False, "Vehicles", "Gawaarida"),
    ("communications_equipment", "asset", False, "Communications equipment", "Qalabka isgaarsiinta"),
    ("restricted_equipment", "asset", True, "Restricted equipment", "Qalabka xaddidan"),
]
COURSES = [("basic_administration", "Basic administration", "Maamul aasaasi ah", 5),
           ("first_aid", "First aid", "Gargaarka degdegga ah", 3),
           ("leadership_basics", "Leadership basics", "Aasaaska hoggaaminta", 10)]


class Command(BaseCommand):
    help = "Seed permissions, roles, branches, organization and draft rank catalogue (idempotent)."

    @transaction.atomic
    def handle(self, *args, **opts):
        perms = {c: Permission.objects.update_or_create(code=c, defaults={"description": d})[0]
                 for c, d in PERMISSIONS.items()}
        for code, (en, so, priv, req_branch, levels, codes) in ROLES.items():
            role, _ = Role.objects.update_or_create(code=code, defaults={
                "name_en": en, "name_so": so, "is_privileged": priv,
                "requires_branch": req_branch, "allowed_scope_levels": levels})
            role.permissions.set([perms[c] for c in dict.fromkeys(list(codes) + EXTRA.get(code, []))])

        branches = {}
        for code, en, so in BRANCHES:
            branches[code], _ = ServiceBranch.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so})

        hq = OU.objects.filter(level=OU.Level.HQ).first() or OU.objects.create(
            code="HQ", name_en="Headquarters", name_so="Xarunta Guud", level=OU.Level.HQ)
        for name in REGIONS:
            region = OU.objects.filter(code=name.upper()).first() or OU.objects.create(
                code=name.upper(), name_en=name, name_so=name, level=OU.Level.REGION, parent=hq)
            for bcode, b in branches.items():
                OU.objects.filter(code=f"{region.code}-{bcode}").first() or OU.objects.create(
                    code=f"{region.code}-{bcode}", name_en=f"{name} {b.name_en}",
                    name_so=f"{name} {b.name_so}", level=OU.Level.BRANCH, parent=region, branch=b)

        army = branches["ARMY"]
        # Official Puntland Army ranks (18, as supplied). Idempotent; never overwrites administrator edits or approvals.
        created, removed, deactivated = apply_official_ranks(Rank, Personnel, army, timezone.now())
        # Organizational template (Taliska Guud ... Unug), specialist designations and the expected relationships.
        types = ensure_reference(UnitType, SpecialistDesignation, DesignationRule)
        tag_regional_army_commands(OU, ServiceBranch, types)
        for code, kind, en, so, keys in REPORT_TYPES:  # created once; admin edits are never overwritten
            ReportType.objects.get_or_create(code=code, defaults={
                "kind": kind, "name_en": en, "name_so": so, "figure_keys": keys})
        for code, kind, restricted, en, so in CATEGORIES:  # draft until institutionally reviewed
            InventoryCategory.objects.get_or_create(code=code, defaults={
                "kind": kind, "restricted": restricted, "name_en": en, "name_so": so})
        for code, en, so, days in COURSES:
            Course.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "duration_days": days})
        self.stdout.write(self.style.SUCCESS(
            f"Reference data ready. Official Army ranks created this run: {created}; provisional ranks removed: {removed}, retired: {deactivated}."))
