"""Idempotent seed of system reference data: permissions, roles, branches, organization, official Army ranks, template.

Safe to re-run. Roles/permissions are system-defined and are re-synced; organization units
and ranks are only created if missing, so administrator edits and rank approvals are kept.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Permission, Role
from django.utils import timezone

from apps.organization.models import DesignationRule, SpecialistDesignation, UnitType
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.reference import ensure_reference, tag_regional_army_commands
from apps.attendance.models import AbsenceReason
from apps.attendance.situation import FIGURE_KEYS
from apps.personnel.models import AppointmentType, Personnel
from apps.ranks.catalogue import apply_official_ranks
from apps.personnel.police_appointments import ensure_types as ensure_police_appointment_types
from apps.ranks.police_catalogue import apply_police_ranks
from apps.organization.police import ensure_police_module
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
    "personnel.view_team": "View your own personnel record and your direct subordinates' records (read-only, within the assignment's scope)",
    "weapons.view": "View the weapon register (serial numbers, custody, condition, history) for units in scope",
    "payroll.view": "View salary profiles, payroll runs and payment status (headquarters finance)",
    "payroll.manage": "Propose salary profiles; prepare, submit and adjust payroll runs",
    "payroll.approve": "Approve salary profiles and payroll runs (never your own work)",
    "payroll.review": "Record pay decisions for suspended and jailed personnel (a record only: never changes pay by itself)",
    "payroll.decide": "Approve or reject pay decisions for suspended and jailed personnel (never your own entry)",
    "payroll.policy_confirm": "Confirm or later revise a payroll or survivor policy value, with authority reference and reason (policy authority)",
    "payment.prepare": "Prepare Sahal / bank-transfer payment instructions against approved amounts",
    "payment.authorize": "Authorize a prepared payment (never one you prepared)",
    "payment.execute": "Send an authorized payment outside the system and record its outcome (never one you authorized)",
    "payment.reconcile": "Reconcile paid payments with provider or bank statements (never one you executed)",
    "payment.details": "See the full recipient details (mobile number, bank account) of a payment; every reveal is audited",
    "arrears.manage": "Record and verify arrears claims (earlier unpaid salary), kept apart from payroll and survivor benefits",
    "arrears.approve": "Approve arrears claims (never one you recorded or verified)",
    "survivor.view": "View survivor-benefit cases and beneficiaries",
    "survivor.manage": "Open survivor cases, register beneficiaries, propose allocations, raise disputes",
    "survivor.verify": "Verify or reject beneficiaries and mark a case verified",
    "survivor.approve": "Authorize survivor allocations and close cases (never your own proposal)",
    "weapons.manage": "Register weapons, issue them to personnel, take them back and record condition for units in scope",
    "vehicles.view": "View the military vehicle register (Vehicle ID, plate, driver, location, status, history) for units in scope; every view is audited",
    "vehicles.create": "Register Army vehicles into units in scope",
    "vehicles.edit": "Edit vehicle details, assign drivers and custodians, record location, status, maintenance and documents for units in scope",
    "vehicles.transfer": "Transfer vehicles between units (needs authority in both the sending and receiving unit)",
    "vehicles.dispose": "Propose decommissioning/disposal of a vehicle (the proposal needs separate approval)",
    "vehicles.approve": "Approve or reject a proposed vehicle disposal; cannot decide one's own proposal",
    "vehicles.cost": "See and record maintenance costs on vehicles in scope",
    "vehicles.configure": "Create and edit vehicle categories (headquarters)",
    "attendance.view": "View attendance and absence records and summaries for personnel in scope",
    "attendance.record": "Record and amend daily attendance for personnel in scope (never changes personnel status)",
    "personnel.appointments_manage": "Appoint and end command appointments (Taliye Qaybeed, Taliye Urur ...) for units in scope; never grants access by itself",
    "personnel.record_death": "Report a death and attach supporting evidence for personnel in scope (does not change status by itself)",
    "personnel.confirm_death": "Confirm a reported death, which sets the status to Died (must be a different officer from the reporter)",
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
    "police.cross_access": "Reach Police records from a branch-unrestricted assignment (command authority only; CID still needs cid.access)",
    "search.cross_service": "Search personnel across all services (Army and Police) within the records the user is otherwise allowed to see",
    "disciplinary.view": "View a person's disciplinary history in scope (encrypted, every view is audited)",
    "disciplinary.manage": "Add disciplinary entries and corrections in scope (entries are append-only)",
    "documents.view": "List and download service documents on personnel files in scope (every access is audited)",
    "documents.manage": "Upload and withdraw service documents on personnel files in scope",
    "reports.combined": "See combined Army + Police summaries (headquarters-wide; command authority). Aggregates only",
    "cid.access": "Reach personnel records inside restricted units such as CID (Police). Never implied by any other permission",
    "system.full_access": "Maintenance override: reach every part of the system even where a module switch (for example the Police pilot being off) would hide it. Super administrator only; every action stays in the audit log",
}
# Never granted to administrators by default (reports.configure is not sensitive, so hq_admin keeps it).
SENSITIVE_PREFIXES = ("personnel.", "reports.view", "reports.submit", "reports.review", "reports.summary", "reports.export",
                      "logistics.view", "logistics.manage", "logistics.restricted", "logistics.reconcile",
                      "logistics.report", "logistics.approve", "training.view", "training.manage", "training.report", "analytics.",
                      "org.structure_approve", "cid.", "police.", "search.", "disciplinary.", "documents.", "reports.combined", "attendance.", "weapons.", "vehicles.", "payroll.", "survivor.", "payment.", "arrears.", "system.")
REPORT_TYPES = [  # code, kind, name_en, name_so, figure keys
    ("monthly_admin_report", "report", "Monthly administrative report", "Warbixinta maamul ee bishii",
     ["personnel_strength", "personnel_on_leave", "personnel_in_training"]),
    ("transfer_request", "request", "Personnel transfer request", "Codsi wareejin shaqaale", []),
    ("training_request", "request", "Training request", "Codsi tababar", []),
]
REPORT_TYPES.append(("unit_situation_report", "report", "Unit situation report", "Warbixinta xaaladda cutubka", FIGURE_KEYS))
# Absence reasons: neutral starting set, editable data. None requires a document until the army decides.
ABSENCE_REASONS = [("illness", "Illness", "Jiro"), ("official_duty", "Official duty away from the unit", "Hawl rasmi meel kale"),
                   ("unexplained", "No reason given", "Sabab lama bixin")]
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
    "unit_admin": ("Unit administrator", "Maamulaha cutubka", False, False, ["unit", "branch_command", "station"],
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
    # Police CID: must be assigned at a CID unit (or above) AND limited to the POLICE branch; carries cid.access.
    "cid_officer": ("CID officer", "Sarkaalka CID", True, True, ["region", "branch_command", "unit"],
                    BASIC + ["personnel.view", "personnel.manage", "reports.view", "reports.submit", "cid.access"]),
    # The two highest command appointments (President / Commander-in-Chief; Commander of the Puntland Defense Forces) are
    # ranks in the Army catalogue; ACCESS is by role, so assign this role to those two people. Read-only oversight, HQ-wide,
    # across Army and Police. Deliberately has no cid.access.
    "command_authority": ("Command authority", "Awoodda taliska", True, False, ["headquarters"],
                          BASIC + ["personnel.view", "reports.view", "reports.summary", "analytics.view", "police.cross_access",
                          "search.cross_service"]),
    "auditor": ("Auditor", "Hubiyaha", True, False, ["headquarters"], ["dashboard.view", "org.view", "audit.view"]),
    # Owner-level role: every permission (including system.full_access, the maintenance override of module switches), HQ-wide, MFA
    # required. Separation-of-duties rules in the code still apply (nobody can approve their own submission), and the audit log and
    # append-only records stay protected, so keep a second approver account for those flows.
    "super_admin": ("Super administrator", "Maamulaha sare", True, False, ["headquarters"], list(PERMISSIONS)),
    # Every non-commanding member of the forces. Own record plus direct subordinates (Personnel.supervisor), nothing else:
    # no unit-wide listing, no export, no reports. Commanders keep their unit/region/branch roles.
    "member": ("Member (non-commanding)", "Xubin (aan taliye ahayn)", False, False, [],
               BASIC + ["personnel.view_team"]),
    # Taliye Guuto / Taliye Urur: record attendance for their unit and below, and make the unit situation report (attendance,
    # personnel status, ammunition issued and remaining). Assigned per unit; link it to the command appointment so that it ends with it.
    "unit_commander": ("Unit commander (Taliye Guuto / Taliye Urur)", "Taliyaha cutubka (Taliye Guuto / Taliye Urur)", False, False,
                       ["unit", "station"], BASIC + ["personnel.view", "attendance.view", "attendance.record", "reports.view", "reports.submit",
                                          "logistics.view", "logistics.restricted", "weapons.view", "vehicles.view"]),
    # Taliye Qaybeed: sees what the heads of the Guuto and Urur in the region have posted (reports, attendance, personnel). Assigned at the
    # regional command (a Qayb). View only: reviewing or approving the reports is a separate authority.
    "regional_commander": ("Regional commander (Taliye Qaybeed)", "Taliyaha Qaybta (Taliye Qaybeed)", True, False, ["branch_command"],
                           BASIC + ["personnel.view", "attendance.view", "reports.view"]),
    # Armourer / weapons custodian: runs the weapon register. Holds the restricted-asset rights it needs to issue and return, and no
    # personnel permission (the issue screen uses a minimal lookup). Privileged: requires MFA like the other restricted roles.
    "weapons_custodian": ("Weapons custodian", "Ilaaliyaha hubka", True, False, ["branch_command", "unit"],
                          BASIC + ["logistics.view", "logistics.manage", "logistics.restricted", "weapons.view", "weapons.manage"]),
    # Transport / fleet officer: keeps the vehicle register for the units in the assignment. Privileged (MFA) like the other restricted
    # custodians. Disposal approval is a separate role so that the proposer and the approver are different people.
    "transport_officer": ("Transport officer", "Sarkaalka gaadiidka", True, False, ["region", "branch_command", "unit"],
                          BASIC + ["vehicles.view", "vehicles.create", "vehicles.edit", "vehicles.transfer", "vehicles.dispose", "vehicles.cost"]),
    "vehicle_disposal_approver": ("Vehicle disposal approver", "Ansixiyaha ka saarista gaadiidka", True, False, ["headquarters", "region", "branch_command"],
                                  BASIC + ["vehicles.view", "vehicles.approve"]),
    # Finance duties are split four ways: the payroll officer PREPARES (runs, payment instructions, arrears), the approver AUTHORISES,
    # the payment officer EXECUTES (sends the payment outside the system and records it), the reconciler CHECKS it against the
    # statement; the auditor only reads the audit log. The service layer also refuses self-approval, so one person holding two
    # roles still cannot approve, execute or reconcile their own work. Names/levels to confirm with the army.
    "payroll_officer": ("Payroll officer", "Sarkaalka mushaharka", True, False, ["headquarters"],
                        BASIC + ["payroll.view", "payroll.manage", "payroll.review", "payment.prepare", "arrears.manage", "survivor.view"]),
    "payroll_approver": ("Payroll approver", "Ansixiyaha mushaharka", True, False, ["headquarters"],
                         BASIC + ["payroll.view", "payroll.approve", "payroll.decide", "payment.authorize", "arrears.approve",
                                  "survivor.view", "survivor.approve"]),
    "payment_officer": ("Payment execution officer", "Sarkaalka fulinta lacag-bixinta", True, False, ["headquarters"],
                        BASIC + ["payroll.view", "payment.execute", "payment.details"]),
    "payment_reconciler": ("Payment reconciliation officer", "Sarkaalka isku-xaaqidda lacagaha", True, False, ["headquarters"],
                           BASIC + ["payroll.view", "payment.reconcile"]),
    "survivor_officer": ("Survivor-benefit officer", "Sarkaalka gunnada ka dhaxlayaasha", True, False, ["headquarters"],
                         BASIC + ["survivor.view", "survivor.manage", "survivor.verify"]),
    "read_only": ("Read-only user", "Isticmaale akhrin oo keliya", False, False, [],
                  BASIC + ["personnel.view", "reports.view"]),
}
# Command appointments supplied by army personnel. code, Somali, English working label, unit type it belongs to, one holder per unit.
# Assumptions to confirm: Taliye Guuto follows the Taliye Qaybeed / Taliye Urur pattern; Abaanduule is confirmed (2026-10-23) as the
# Battalion Executive Officer / Second-in-Command (Urur level). Kept non-exclusive until the army says whether a Urur has only one.
APPOINTMENT_TYPES = [
    ("TALIYE_QAYBEED", "Taliye Qaybeed", "Regional command commander (Taliye Qaybeed)", "QAYB", True),
    ("TALIYE_GUUTO", "Taliye Guuto", "Guuto commander (Taliye Guuto)", "GUUTO", True),
    ("TALIYE_URUR", "Taliye Urur", "Urur commander (Taliye Urur)", "URUR", True),
    ("ABAANDUULE", "Abaanduule", "Abaanduule (Battalion Executive Officer / Second-in-Command)", "URUR", False),
]
# Puntland Police command appointments (2026-10-23): one Chief of Police in each region's Police command, and under him one lead for each\n# station of that region. Names are plain English working labels, no Somali wording was supplied, so none is invented. Only created while the\n# Police pilot switch is on. Where each may be held is enforced in apps/personnel/appointments.py (LEVEL_RULES).
POLICE_APPOINTMENT_TYPES = [
    ("POLICE_CHIEF", "Chief of Police", "Chief of Police (regional Police command)", True),
    ("POLICE_STATION_LEAD", "Station Lead", "Station Lead (Police station)", True),
]
BRANCHES = [("ARMY", "Army", "Ciidanka Dhulka"), ("NAVY", "Navy", "Ciidanka Badda"), ("POLICE", "Police", "Booliska")]
REGIONS = ["Bari", "Karkaar", "Nugaal", "Mudug"]

# Army ranks live in apps/ranks/catalogue.py (the 16 official Puntland Army ranks, as supplied).
# The organizational template lives in apps/organization/reference.py.


# Extra grants per role (applied on top of the tuples above).
EXTRA = {
    "hq_admin": ["logistics.configure", "training.configure", "vehicles.configure"],
    "hq_reporting": ["logistics.report", "training.report", "analytics.view"],
    "regional_chief": ["vehicles.view", "weapons.view", "logistics.view", "logistics.report", "training.view", "training.report", "analytics.view",
                       "personnel.record_death"],
    # Disciplinary history and service documents are sensitive: only these privileged (MFA) roles hold them by default
    # (branch_admin, cid_officer), plus super_admin. Adjust here if the institution decides otherwise; the next seed run
    # re-syncs roles. Combined Army + Police summaries go to command_authority only (and super_admin).
    "branch_admin": ["vehicles.view", "logistics.view", "logistics.report", "training.view", "training.report", "analytics.view",
                     "disciplinary.view", "disciplinary.manage", "documents.view", "documents.manage",
                     "personnel.record_death", "personnel.confirm_death", "personnel.appointments_manage"],
    "cid_officer": ["disciplinary.view", "disciplinary.manage", "documents.view", "documents.manage"],
    "command_authority": ["reports.combined"],
    "unit_admin": ["logistics.view", "training.view", "personnel.record_death"],
    "logistics_custodian": ["logistics.view", "logistics.manage", "logistics.reconcile", "logistics.report"],
    "training_admin": ["training.view", "training.manage", "training.report", "training.configure"],
}
VEHICLE_CATEGORIES = [  # code, name_en, name_so, sort. Available categories only: seeding does not assert that the Army owns any vehicle of a type.
    ("ambulance", "Ambulance", "Gaari bakhaar", 10), ("armored_truck", "Armored truck", "Gawaari hubaysan", 20),
    ("hilux_4x4", "Hilux 4x4", "Hilux 4x4", 30), ("truck", "Truck", "Gawaari xamuul", 40), ("bus", "Bus", "Bas", 50),
    ("motorcycle", "Motorcycle", "Mooto", 60), ("utility", "Utility vehicle", "Gaari adeeg", 70),
]
CATEGORIES = [  # code, kind, restricted, name_en, name_so  (seeded as DRAFT; weapon and ammunition categories included, no weapons or stock)
    ("general_supplies", "stock", False, "General supplies", "Saadka guud"),
    ("uniforms_clothing", "stock", False, "Uniforms and clothing", "Maryo iyo dharka"),
    ("vehicles", "asset", False, "Vehicles", "Gawaarida"),
    ("communications_equipment", "asset", False, "Communications equipment", "Qalabka isgaarsiinta"),
    ("restricted_equipment", "asset", True, "Restricted equipment", "Qalabka xaddidan"),
    ("weapons", "asset", True, "Weapons", "Hubka"),  # restricted, serial-numbered; draft until approved by the restricted-approval authority
    ("ammunition", "stock", True, "Ammunition", "Rasaasta"),  # restricted stock; draft until approved. Situation reports sum categories whose code starts with "ammunition"
    # Weapon categories (Weapon register). Code must start with "weapons"; one category per class of weapon. Restricted, serial-numbered,
    # draft until approved by the restricted-approval authority. Add or rename more under Logistics -> Categories.
    ("weapons_rifles", "asset", True, "Rifles", "Qori (bunduuc)"),
    ("weapons_pistols", "asset", True, "Pistols", "Bastoolado"),
    ("weapons_smg", "asset", True, "Submachine guns", "Qori-yaryare toosh"),
    ("weapons_machine_guns", "asset", True, "Machine guns", "Hubka toosha (bakoorad)"),
    ("weapons_sniper", "asset", True, "Sniper rifles", "Qoryaha sirdoonka (sniper)"),
    ("weapons_launchers", "asset", True, "Rocket and grenade launchers", "Gantaalaha RPG iyo bambooyinka"),
    ("weapons_mortars", "asset", True, "Mortars and crew-served weapons", "Hubka culus iyo kooxeed"),
    # Ammunition categories (Ammunition ledger). Code must start with "ammunition"; one category per calibre or type.
    ("ammunition_556", "stock", True, "Ammunition 5.56x45 mm", "Rasaasta 5.56x45 mm"),
    ("ammunition_762x39", "stock", True, "Ammunition 7.62x39 mm", "Rasaasta 7.62x39 mm"),
    ("ammunition_762x51", "stock", True, "Ammunition 7.62x51 mm", "Rasaasta 7.62x51 mm"),
    ("ammunition_762x54", "stock", True, "Ammunition 7.62x54R mm", "Rasaasta 7.62x54R mm"),
    ("ammunition_9mm", "stock", True, "Ammunition 9 mm (pistol / SMG)", "Rasaasta 9 mm"),
    ("ammunition_127", "stock", True, "Ammunition 12.7 mm", "Rasaasta 12.7 mm"),
    ("ammunition_145", "stock", True, "Ammunition 14.5 mm", "Rasaasta 14.5 mm"),
    ("ammunition_rockets", "stock", True, "Rockets and RPG rounds", "Gantaalaha iyo rasaasta RPG"),
    ("ammunition_mortar", "stock", True, "Mortar bombs", "Bambooyinka mortarka"),
    ("ammunition_grenades", "stock", True, "Hand grenades", "Gantaalaha gacanta"),
]
COURSES = [("basic_administration", "Basic administration", "Maamul aasaasi ah", 5),
           ("first_aid", "First aid", "Gargaarka degdegga ah", 3),
           ("leadership_basics", "Leadership basics", "Aasaaska hoggaaminta", 10)]


class Command(BaseCommand):
    help = "Seed permissions, roles, branches, organization and draft rank catalogue (idempotent)."

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.payroll.models import PolicySetting
        from apps.payroll.policy_defaults import seed_policy
        seed_policy(PolicySetting)  # payroll/survivor policy items (confirmed defaults and open questions); never overwrites
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
        for code, so, en, utype, exclusive in APPOINTMENT_TYPES:  # created once; administrator edits are never overwritten
            AppointmentType.objects.get_or_create(code=code, defaults={
                "name_so": so, "name_en": en, "unit_type": types.get(utype), "exclusive": exclusive})
        police_created = depts_created = 0
        if settings.POLICE_MODULE_ENABLED:  # pilot switch: nothing Police-specific is created while it is off
            police_created = apply_police_ranks(Rank, branches["POLICE"], timezone.now())
            ensure_police_appointment_types(AppointmentType)  # Chief of Police, Station Commander
            depts_created = ensure_police_module(OU, [r.upper() for r in REGIONS])
            for code, so, en, exclusive in POLICE_APPOINTMENT_TYPES:  # created once; administrator edits are never overwritten
                AppointmentType.objects.get_or_create(code=code, defaults={
                    "name_so": so, "name_en": en, "unit_type": None, "exclusive": exclusive})
        for code, kind, en, so, keys in REPORT_TYPES:  # created once; admin edits are never overwritten
            rt, _ = ReportType.objects.get_or_create(code=code, defaults={
                "kind": kind, "name_en": en, "name_so": so, "figure_keys": keys})
            if code == "unit_situation_report" and rt.figure_keys != keys:  # computed by code, so its keys follow the code
                ReportType.objects.filter(pk=rt.pk).update(figure_keys=keys)
        for code, en, so in ABSENCE_REASONS:
            AbsenceReason.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so})
        for code, kind, restricted, en, so in CATEGORIES:  # draft until institutionally reviewed
            InventoryCategory.objects.get_or_create(code=code, defaults={
                "kind": kind, "restricted": restricted, "name_en": en, "name_so": so})
        from apps.vehicles.models import SYSTEM_STATUSES, VehicleCategory, VehicleStatusType
        for code, en, so, avail, order in SYSTEM_STATUSES:
            VehicleStatusType.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "available": avail, "is_system": True, "sort_order": order})
        for code, en, so, order in VEHICLE_CATEGORIES:
            VehicleCategory.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "sort_order": order})
        for code, en, so, days in COURSES:
            Course.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "duration_days": days})
        self.stdout.write(self.style.SUCCESS(
            f"Reference data ready. Official Army ranks created this run: {created}; provisional ranks removed: {removed}, retired: {deactivated}. Police module: {'ON' if settings.POLICE_MODULE_ENABLED else 'off'} (draft ranks created {police_created}, departments created {depts_created})."))
