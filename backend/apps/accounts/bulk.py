"""Create many login accounts from one CSV: name, role and unit (and optionally the personnel record to link).

Same two-step flow as the other imports: a preview that only reports, then a commit that re-checks everything and writes
all-or-nothing. Every account gets a random temporary password that must be changed at first sign-in and expires; the
passwords are returned once by the commit and never stored in clear. Each row is checked against the uploader's own authority
(they cannot hand out a role they do not hold, or link a person outside their scope)."""
import csv
import io

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import F
from django.utils import timezone

from apps.audit.services import record
from apps.organization.models import OrganizationalUnit, ServiceBranch
from apps.personnel.models import Personnel

from . import scope
from .models import Role, RoleAssignment, User
from .serializers import AssignmentCreateSerializer
from .services import USERNAME_PATTERN, generate_temp_password, sensitive_role, suggest_usernames, temp_password_deadline

COLUMNS = ["full_name", "username", "email", "role", "unit", "branch", "service_number", "language"]
REQUIRED = ["full_name", "role", "unit"]
MAX_ROWS = 50  # each account costs one slow password hash; the server gives a request 30 seconds
MAX_BYTES = 200_000


class BulkError(Exception):
    def __init__(self, code, field="file"):
        super().__init__(code)
        self.code, self.field = code, field


def parse_csv(upload):
    if upload.size > MAX_BYTES:
        raise BulkError("file_too_large")
    if not (upload.name or "").lower().endswith(".csv"):
        raise BulkError("file_type_invalid")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BulkError("file_encoding_invalid")
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip() for h in (reader.fieldnames or [])}
    if not set(REQUIRED) <= headers or not headers <= set(COLUMNS):
        raise BulkError("file_columns_invalid")
    rows = []
    try:
        for raw in reader:
            if len(rows) >= MAX_ROWS:
                raise BulkError("file_too_many_rows")
            rows.append({k: (raw.get(k) or "").strip()[:150] for k in COLUMNS})
    except csv.Error:
        raise BulkError("file_columns_invalid")
    if not rows:
        raise BulkError("file_empty")
    return rows


def validate_rows(actor, rows):
    """Check every row. Nothing is written. Returns [{row, errors, data}] where data is what apply() will create."""
    roles = {r.code: r for r in Role.objects.prefetch_related("permissions")}
    units = {u.code: u for u in OrganizationalUnit.objects.filter(active=True)}
    branches = {b.code: b for b in ServiceBranch.objects.filter(active=True)}
    numbers = {r["service_number"] for r in rows if r["service_number"]}
    people = {p.service_number: p for p in Personnel.objects.filter(service_number__in=numbers).select_related("org_unit")}
    linked = set(Personnel.objects.filter(service_number__in=numbers, account__isnull=False).values_list("service_number", flat=True))
    wanted = {r["username"] for r in rows if r["username"]}
    existing = set(User.objects.filter(username__in=wanted).values_list("username", flat=True))
    beyond_cache, used_names, seen_people, results = {}, set(), set(), []
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        errors, data = [], {}
        if not r["full_name"]:
            errors.append("full_name_required")
        username = r["username"]
        if username:
            if not USERNAME_PATTERN.match(username):
                errors.append("invalid_username")
            elif username in existing or username in used_names:
                errors.append("username_taken")
        elif r["full_name"]:
            free = suggest_usernames(r["full_name"], limit=1, extra_taken=used_names)
            if free:
                username = free[0]
            else:
                errors.append("username_unavailable")
        if r["email"]:
            try:
                validate_email(r["email"])
            except DjangoValidationError:
                errors.append("email_invalid")
        lang = r["language"].lower() or "so"
        if lang not in ("en", "so"):
            errors.append("language_invalid")
        role, unit = roles.get(r["role"]), units.get(r["unit"])
        branch = branches.get(r["branch"]) if r["branch"] else None
        if role is None:
            errors.append("role_unknown")
        if unit is None:
            errors.append("unit_unknown")
        if r["branch"] and branch is None:
            errors.append("branch_unknown")
        if role and unit and not (r["branch"] and branch is None):
            check = AssignmentCreateSerializer(data={"role": role.code, "org_unit": str(unit.pk), "branch": str(branch.pk) if branch else None})
            if not check.is_valid():
                for field_errors in check.errors.values():
                    errors.extend(str(e.code) for e in field_errors)
            if role.code not in beyond_cache:
                beyond_cache[role.code] = any(not scope.can(actor, c) for c in role.permissions.values_list("code", flat=True))
            if beyond_cache[role.code]:
                errors.append("role_exceeds_authority")
        person = None
        if r["service_number"]:
            person = people.get(r["service_number"])
            if person is None or not scope.can(actor, "personnel.manage", unit=person.org_unit):
                errors.append("person_unknown")  # unknown and out-of-scope are indistinguishable on purpose
            elif person.status == Personnel.Status.DIED:
                errors.append("person_deceased")
            elif r["service_number"] in linked:
                errors.append("person_already_linked")
            elif person.pk in seen_people:
                errors.append("duplicate_row")
            else:
                seen_people.add(person.pk)
        if not errors:
            used_names.add(username)
            data = {"username": username, "full_name": r["full_name"], "email": r["email"], "language": lang,
                    "role": role, "unit": unit, "branch": branch, "person": person}
        elif username:
            used_names.add(username)  # keep generated/typed names reserved so later rows never collide with this one
        results.append({"row": i, "errors": list(dict.fromkeys(errors)), "data": data})
    return results


def apply_rows(request, results):
    """Create the accounts (call inside a transaction). Returns one entry per account, including the one-time password."""
    actor, deadline, now, out = request.user, temp_password_deadline(), timezone.now(), []
    for res in results:
        d = res["data"]
        password = generate_temp_password()
        user = User.objects.create_user(
            d["username"], password=password, full_name=d["full_name"], email=d["email"], preferred_language=d["language"],
            must_change_password=True, temp_password_expires_at=deadline)
        a = RoleAssignment.objects.create(user=user, role=d["role"], org_unit=d["unit"], branch=d["branch"], created_by=actor)
        record("user.create", request=request, entity_type="user", entity_id=user.pk,
               metadata={"username": user.username, "generated_password": True, "via": "bulk"})
        record("role_assignment.create", request=request, entity_type="role_assignment", entity_id=a.pk,
               metadata={"user": str(user.pk), "role": d["role"].code, "org_unit": str(d["unit"].pk),
                         "branch": str(d["branch"].pk) if d["branch"] else None})
        if d["person"] is not None:
            Personnel.objects.filter(pk=d["person"].pk).update(account=user, version=F("version") + 1, updated_at=now)
            record("personnel.reporting_lines", request=request, entity_type="personnel", entity_id=d["person"].pk,
                   metadata={"account_linked": user.username, "via": "bulk_users"})
        out.append({"row": res["row"], "username": user.username, "full_name": user.full_name, "role": d["role"].code,
                    "unit": d["unit"].code, "linked": d["person"] is not None, "temporary_password": password,
                    "expires_at": deadline})
        if sensitive_role(d["role"]):
            record("role_assignment.privileged", request=request, entity_type="role_assignment", entity_id=a.pk,
                   metadata={"user": str(user.pk), "role": d["role"].code, "via": "bulk"})
            out[-1]["_alert"] = (user, d["role"], d["unit"])
    return out
