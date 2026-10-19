import csv
import io
import re
import unicodedata
from datetime import date

from apps.accounts import scope
from apps.accounts.models import User
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


# ---------------------------------------------------------------- reporting lines (supervisor / login link)
#
# Seniority is the rank's `sort_order` inside one service: HIGHER = MORE SENIOR (Army: Dable=1 ... President=18; the Police
# catalogue is stored in the same direction). Retired provisional ranks are parked at sort_order >= 1000 and are inactive:
# they are NOT comparable (they would otherwise look like the most senior rank in the force), so a person holding one
# must be given a current rank before a reporting line can be set for them.
def seniority(rank):
    return rank.sort_order if rank.active else None


def outranks(senior, junior):
    """True / False, or None when either rank cannot be compared (inactive)."""
    a, b = seniority(senior), seniority(junior)
    if a is None or b is None:
        return None
    return a > b


def check_supervisor(user, person, sup, overlay=None):
    """The one rulebook for "X reports to Y". Raises RuleError(code, "supervisor").

    Same service, strictly senior, reachable by the editor, no loop. `overlay` maps person-id -> supervisor-id for changes
    that are queued (bulk file) but not yet saved. Out-of-scope and non-existent supervisors give the same code."""
    bad = RuleError("supervisor_invalid", "supervisor")
    if sup.pk == person.pk or sup.branch_id != person.branch_id:
        raise bad
    if not (scope.can(user, "personnel.manage", unit=sup.org_unit) or scope.can(user, "personnel.view", unit=sup.org_unit)):
        raise bad
    cmp = outranks(sup.rank, person.rank)
    if cmp is None:
        raise RuleError("rank_not_comparable", "supervisor")
    if not cmp:
        raise RuleError("supervisor_not_senior", "supervisor")
    overlay = overlay or {}
    seen, cur = {person.pk}, sup.pk
    while cur is not None:
        if cur in seen:
            raise bad
        seen.add(cur)
        cur = overlay[cur] if cur in overlay else Personnel.objects.filter(pk=cur).values_list("supervisor_id", flat=True).first()


def check_account(person, acct):
    """Login link rules. Returns the User (or None to unlink)."""
    if acct is None:
        return None
    if not acct.is_active:
        raise RuleError("account_invalid", "account_username")
    if Personnel.objects.filter(account=acct).exclude(pk=person.pk).exists():
        raise RuleError("account_taken", "account_username")
    return acct


LINES_COLUMNS = ["service_number", "supervisor_service_number", "account_username"]
CLEAR = "clear"  # cell value that removes the supervisor / unlinks the account; a blank cell means "leave as it is"


def parse_lines_csv(upload):
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
    if "service_number" not in headers or not headers <= set(LINES_COLUMNS) or len(headers) < 2:
        raise RuleError("file_columns_invalid", "file")
    rows = []
    try:
        for raw in reader:
            if len(rows) >= MAX_IMPORT_ROWS:
                raise RuleError("file_too_many_rows", "file")
            row = {k: (raw.get(k) or "").strip()[:64] for k in LINES_COLUMNS}
            for k in ("supervisor_service_number", "account_username"):
                if row[k].lower() == CLEAR:
                    row[k] = CLEAR
            rows.append(row)
    except csv.Error:
        raise RuleError("file_columns_invalid", "file")
    if not rows:
        raise RuleError("file_empty", "file")
    return rows


def validate_reporting_rows(user, rows):
    """Check every row against the *uploader's own scope*. Rows are applied in file order, so a row may name as supervisor
    someone whose own supervisor is set earlier in the same file. Nothing is written here."""
    q = scope.unit_scope_q(user, "personnel.manage", "org_unit__")
    numbers = {r["service_number"] for r in rows if r["service_number"]} | \
        {r["supervisor_service_number"] for r in rows if r["supervisor_service_number"] not in ("", CLEAR)}
    found = {p.service_number: p for p in Personnel.objects.filter(service_number__in=numbers)
             .select_related("rank", "org_unit", "branch")}
    editable = set() if q is None else set(Personnel.objects.filter(q, service_number__in=numbers).values_list("pk", flat=True))
    accounts = {u.username: u for u in User.objects.filter(
        username__in={r["account_username"].lower() for r in rows if r["account_username"] not in ("", CLEAR)})}
    overlay, seen_people, seen_accounts, results = {}, set(), {}, []
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        errors, person = [], found.get(r["service_number"]) if r["service_number"] else None
        sup, acct = ..., ...  # Ellipsis = leave unchanged
        if person is None or person.pk not in editable:
            errors.append("person_unknown")  # unknown and out-of-scope are indistinguishable on purpose
        elif person.pk in seen_people:
            errors.append("duplicate_row")
        else:
            seen_people.add(person.pk)
            val = r["supervisor_service_number"]
            if val == CLEAR:
                sup = None
            elif val:
                cand = found.get(val)
                try:
                    if cand is None:
                        raise RuleError("supervisor_invalid", "supervisor")
                    check_supervisor(user, person, cand, overlay)
                    sup = cand
                except RuleError as exc:
                    errors.append(exc.code)
            val = r["account_username"].lower()
            if val == CLEAR:
                acct = None
            elif val:
                try:
                    cand = accounts.get(val)
                    if cand is None:
                        raise RuleError("account_invalid", "account_username")
                    check_account(person, cand)
                    if seen_accounts.get(cand.pk, person.pk) != person.pk:
                        raise RuleError("account_taken", "account_username")
                    seen_accounts[cand.pk] = person.pk
                    acct = cand
                except RuleError as exc:
                    errors.append(exc.code)
            if not errors and sup is not ...:
                overlay[person.pk] = sup.pk if sup else None
        results.append({"row": i, "errors": errors, "person": person, "supervisor": sup, "account": acct})
    return results


def apply_reporting_rows(actor, results):
    """Write the validated rows. Each person's version is bumped, like any other edit. Returns how many people changed."""
    from django.db.models import F
    from django.utils import timezone
    n = 0
    for res in results:
        changes = {}
        if res["supervisor"] is not ...:
            changes["supervisor"] = res["supervisor"]
        if res["account"] is not ...:
            changes["account"] = res["account"]
        if changes:
            Personnel.objects.filter(pk=res["person"].pk).update(
                **changes, version=F("version") + 1, updated_at=timezone.now())
            n += 1
    return n
