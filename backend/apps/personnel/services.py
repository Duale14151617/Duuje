import csv
import io
import re
import unicodedata
from datetime import date

from apps.accounts import scope
from apps.audit.services import record
from apps.organization.models import OrganizationalUnit
from apps.ranks.models import Rank

from .models import Personnel, PersonnelHistory

PHONE_RE = re.compile(r"^\+?[0-9 ()-]{6,20}$")
SERVICE_NO_RE = re.compile(r"^[A-Za-z0-9/-]{3,32}$")
STATUSES = {s.value for s in Personnel.Status}
IMPORT_COLUMNS = ["service_number", "full_name", "phone", "unit_code", "rank_code", "status"]
IMPORT_REQUIRED = {"full_name", "unit_code", "rank_code"}
MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 1_000_000


class RuleError(Exception):
    def __init__(self, code, field="non_field_errors"):
        super().__init__(code)
        self.code, self.field = code, field


def normalize_name(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[^\w\s]", "", value).split())


def normalize_phone(value):
    return re.sub(r"\D", "", value or "")


def check_assignment(unit, rank, allow_draft_rank=False):
    """Business rules tying a person's unit and rank together.

    `allow_draft_rank` exists ONLY for clearly tagged synthetic demo people (seed_test_personnel, opt-in); no API path sets it."""
    if unit.level not in (OrganizationalUnit.Level.BRANCH, OrganizationalUnit.Level.UNIT, OrganizationalUnit.Level.STATION):
        raise RuleError("unit_level_invalid", "org_unit")
    if not unit.active:
        raise RuleError("unit_inactive", "org_unit")
    if rank.branch_id != unit.branch_id:
        raise RuleError("rank_branch_mismatch", "rank")
    if rank.approval_status != Rank.Approval.APPROVED and not allow_draft_rank:
        raise RuleError("rank_not_approved", "rank")
    if not rank.active:
        raise RuleError("rank_inactive", "rank")


def service_number_taken(number, exclude_pk=None):
    if not number:
        return False
    qs = Personnel.objects.filter(service_number__iexact=number)
    return (qs.exclude(pk=exclude_pk) if exclude_pk else qs).exists()


NOT_SERVING = (Personnel.Status.RETIRED, Personnel.Status.DISCHARGED)


def duplicate_check(name_key, phone_key, unit, exclude_pk=None):
    """Identity check across ALL services (Army, Navy, Police). Returns a rule code or None:

      "duplicate_identity"  BLOCK, no override: same name AND same phone as someone still serving in a different service.
                            One person cannot be on two services' active rolls.
      "possible_duplicate"  FLAG, can be confirmed (confirm_duplicate): same name+phone anywhere (for example a retired
                            record in another service), same name in the same unit when there is no phone, or the same
                            name in another service when one side has no phone to tell the two people apart.

    Service numbers are checked separately and are unique across every service already (service_number_taken).
    Callers report only the code, never the other record, so the check cannot be used to browse other services' people.
    """
    base = Personnel.objects.filter(name_key=name_key)
    if exclude_pk:
        base = base.exclude(pk=exclude_pk)
    other_service = base.exclude(branch_id=unit.branch_id)
    if phone_key:
        same_phone = base.filter(phone_key=phone_key)
        if same_phone.exclude(branch_id=unit.branch_id).exclude(status__in=NOT_SERVING).exists():
            return "duplicate_identity"
        if same_phone.exists():
            return "possible_duplicate"
        if other_service.filter(phone_key="").exists():  # no phone on the other record: cannot rule it out
            return "possible_duplicate"
        return None
    if base.filter(org_unit_id=unit.pk).exists() or other_service.exists():
        return "possible_duplicate"
    return None


def possible_duplicate(name_key, phone_key, unit_id, exclude_pk=None):
    """Kept for callers that only need a yes/no (same-unit rule). New code should use duplicate_check()."""
    qs = Personnel.objects.filter(name_key=name_key)
    qs = qs.filter(phone_key=phone_key) if phone_key else qs.filter(org_unit_id=unit_id)
    return (qs.exclude(pk=exclude_pk) if exclude_pk else qs).exists()


def rank_label(rank):
    return f"{rank.code} {rank.name_en}"[:200]


def add_history(person, field, old_ref, new_ref, old_label, new_label, effective_date, reason, actor):
    return PersonnelHistory.objects.create(
        personnel=person, field=field, old_ref=old_ref or "", new_ref=new_ref, old_label=old_label or "",
        new_label=new_label, effective_date=effective_date, reason=(reason or "")[:300],
        recorded_by_id=getattr(actor, "pk", None), recorded_by_username=getattr(actor, "username", ""))


def create_personnel(actor, *, full_name, phone, service_number, org_unit, rank, status, effective_date,
                     reason="Record created", allow_draft_rank=False):
    check_assignment(org_unit, rank, allow_draft_rank=allow_draft_rank)
    person = Personnel.objects.create(
        service_number=service_number or None, full_name=full_name, phone=phone or "",
        name_key=normalize_name(full_name), phone_key=normalize_phone(phone),
        branch=org_unit.branch, org_unit=org_unit, rank=rank, status=status)
    day = effective_date or date.today()
    add_history(person, "rank", "", str(rank.pk), "", rank_label(rank), day, reason, actor)
    add_history(person, "org_unit", "", str(org_unit.pk), "", org_unit.name_en, day, reason, actor)
    add_history(person, "status", "", status, "", status, day, reason, actor)
    return person


# ---------------------------------------------------------------- CSV import
def parse_csv(upload):
    """Return list of raw row dicts. Raises RuleError for unsafe or malformed files."""
    if upload.size > MAX_IMPORT_BYTES:
        raise RuleError("file_too_large", "file")
    if not (upload.name or "").lower().endswith(".csv"):
        raise RuleError("file_type_invalid", "file")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RuleError("file_encoding_invalid", "file")
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip() for h in (reader.fieldnames or [])}
    if not IMPORT_REQUIRED <= headers or not headers <= set(IMPORT_COLUMNS):
        raise RuleError("file_columns_invalid", "file")
    rows = []
    try:
        for raw in reader:
            if len(rows) >= MAX_IMPORT_ROWS:
                raise RuleError("file_too_many_rows", "file")
            rows.append({k: (raw.get(k) or "").strip()[:200] for k in IMPORT_COLUMNS})
    except csv.Error:
        raise RuleError("file_columns_invalid", "file")
    if not rows:
        raise RuleError("file_empty", "file")
    return rows


def validate_import_rows(user, rows):
    """Validate every row against *the importing user's own scope*. Returns per-row error codes."""
    units = {u.code: u for u in scope.scoped_units(user, "personnel.import")
             .filter(code__in={r["unit_code"].upper() for r in rows}).select_related("branch")}
    ranks = {}
    seen_numbers, seen_people, results = set(), set(), []
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        errors = []
        unit = units.get(r["unit_code"].upper())
        if not r["full_name"]:
            errors.append("full_name_required")
        if unit is None:
            errors.append("unit_unknown")  # unknown and out-of-scope are indistinguishable on purpose
        rank = None
        if unit is not None:
            key = (unit.branch_id, r["rank_code"].upper())
            if key not in ranks:
                ranks[key] = Rank.objects.filter(branch_id=unit.branch_id, code=key[1]).first()
            rank = ranks[key]
            if rank is None:
                errors.append("rank_unknown")
            else:
                try:
                    check_assignment(unit, rank)
                except RuleError as exc:
                    errors.append(exc.code)
        status = r["status"] or "active"
        if status not in STATUSES:
            errors.append("status_invalid")
        if r["phone"] and not PHONE_RE.match(r["phone"]):
            errors.append("phone_invalid")
        number = r["service_number"]
        if number:
            if not SERVICE_NO_RE.match(number):
                errors.append("service_number_invalid")
            elif number.lower() in seen_numbers or service_number_taken(number):
                errors.append("service_number_taken")
            seen_numbers.add(number.lower())
        if r["full_name"] and unit is not None:
            nk, pk_ = normalize_name(r["full_name"]), normalize_phone(r["phone"])
            sig = (nk, pk_ or str(unit.pk))
            found = duplicate_check(nk, pk_, unit)
            if found:
                errors.append(found)
            elif sig in seen_people:
                errors.append("possible_duplicate")
            seen_people.add(sig)
        results.append({"row": i, "errors": errors, "unit": unit, "rank": rank, "status": status})
    return results


def commit_import(actor, rows, results):
    created = 0
    for r, res in zip(rows, results):
        create_personnel(actor, full_name=r["full_name"], phone=r["phone"], service_number=r["service_number"],
                         org_unit=res["unit"], rank=res["rank"], status=res["status"], effective_date=None,
                         reason="CSV import")
        created += 1
    return created


# ---------------------------------------------------------------- CSV export
def csv_safe(value):
    """Neutralise spreadsheet formula injection."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def export_csv(queryset):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(IMPORT_COLUMNS)
    for p in queryset.select_related("org_unit", "rank"):
        writer.writerow([csv_safe(x) for x in (p.service_number, p.full_name, p.phone, p.org_unit.code,
                                              p.rank.code, p.status)])
    return buf.getvalue()


def audit_denied_duplicate(request, kind):
    record("personnel.duplicate_blocked", request=request, outcome="denied", entity_type="personnel",
           metadata={"kind": kind})
