"""Governed changes to the organizational template (unit-type catalogue).

A proposal is a list of plain-data operations. `evaluate` simulates the resulting catalogue and reports every problem and
the impact on existing units *without writing anything*; `apply` re-evaluates and then writes, in one transaction.
The hard rules are the ones the direct editor already enforced (tier order, range order, unit types in use) plus a check
that no existing unit would end up under a parent of an equal or deeper type.
"""
import re

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.exceptions import ErrorDetail

from apps.audit.services import record

from .models import OrganizationalUnit, UnitType

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
MAX_OPERATIONS = 50
TEXT = {"name_en": 100, "name_so": 100, "description_en": 200, "description_so": 200}
NUMBERS = ("tier", "standard_per_parent", "reference_min", "reference_max")
FIELDS = set(TEXT) | set(NUMBERS) | {"parent_type", "active"}


class StructureApprovalRequired(APIException):
    status_code = 409
    default_detail = "Structure changes must be proposed and approved."
    default_code = "approval_required"


def _bad(code, message="Invalid."):
    return ValidationError([ErrorDetail(message, code=code)])  # used inside a field validator, so a plain list


def _clean_value(field, value):
    if field in TEXT:
        if not isinstance(value, str) or len(value.strip()) > TEXT[field]:
            raise _bad("invalid_value")
        return value.strip()
    if field in NUMBERS:
        if value is None and field != "tier":
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1_000_000 or (field == "tier" and value < 1):
            raise _bad("invalid_value")
        return value
    if field == "active":
        if not isinstance(value, bool):
            raise _bad("invalid_value")
        return value
    if field == "parent_type":
        if value is None:
            return None
        if not isinstance(value, str) or not CODE_RE.match(value.strip().upper()):
            raise _bad("invalid_value")
        return value.strip().upper()
    raise _bad("unknown_field")


def normalize(operations):
    """Syntax check only (shape and value types). Raises ValidationError; returns clean plain data."""
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise _bad("invalid_operations")
    clean, seen = [], set()
    for raw in operations:
        if not isinstance(raw, dict) or raw.get("op") not in ("create", "update"):
            raise _bad("invalid_operation")
        code = raw.get("code")
        if not isinstance(code, str) or not CODE_RE.match(code.strip().upper()):
            raise _bad("invalid_code")
        code = code.strip().upper()
        if code in seen:
            raise _bad("duplicate_code")
        seen.add(code)
        if raw["op"] == "create":
            body = {k: v for k, v in raw.items() if k not in ("op", "code")}
            if set(body) - FIELDS or "active" in body:
                raise _bad("unknown_field")
            if not str(body.get("name_en", "")).strip() or "tier" not in body:
                raise _bad("missing_field")
            clean.append({"op": "create", "code": code, **{k: _clean_value(k, v) for k, v in body.items()}})
        else:
            fields = raw.get("fields")
            if not isinstance(fields, dict) or not fields or set(fields) - FIELDS:
                raise _bad("unknown_field")
            clean.append({"op": "update", "code": code, "fields": {k: _clean_value(k, v) for k, v in fields.items()}})
    return clean


def _catalogue():
    out = {}
    for t in UnitType.objects.select_related("parent_type"):
        out[t.code] = {"name_en": t.name_en, "name_so": t.name_so, "tier": t.tier, "standard_per_parent": t.standard_per_parent,
                       "reference_min": t.reference_min, "reference_max": t.reference_max, "description_en": t.description_en,
                       "description_so": t.description_so, "active": t.active,
                       "parent_type": t.parent_type.code if t.parent_type_id else None}
    return out


def evaluate(operations):
    """Returns {errors, created, updated, units_by_type, affected_units}. Never writes. `errors` empty means applicable."""
    errors = []
    now = _catalogue()
    proposed = {c: dict(v) for c, v in now.items()}
    created, updated = [], []
    for op in operations:
        code = op["code"]
        if op["op"] == "create":
            if code in proposed:
                errors.append({"code": "code_taken", "type": code})
                continue
            body = {k: v for k, v in op.items() if k not in ("op", "code")}
            proposed[code] = {"name_en": "", "name_so": "", "tier": 0, "standard_per_parent": None, "reference_min": None,
                              "reference_max": None, "description_en": "", "description_so": "", "active": True,
                              "parent_type": None, **body}
            created.append(code)
        else:
            if code not in proposed:
                errors.append({"code": "unknown_type", "type": code})
                continue
            proposed[code].update(op["fields"])
            updated.append(code)
    for code, t in proposed.items():
        parent = t["parent_type"]
        if parent is not None:
            if parent == code or parent not in proposed:
                errors.append({"code": "unknown_parent_type", "type": code})
            elif proposed[parent]["tier"] >= t["tier"]:
                errors.append({"code": "tier_order", "type": code})
            elif t["active"] and not proposed[parent]["active"]:
                errors.append({"code": "inactive_parent", "type": code})
        lo, hi = t["reference_min"], t["reference_max"]
        if lo is not None and hi is not None and hi < lo:
            errors.append({"code": "range_order", "type": code})
        if not t["name_en"].strip():
            errors.append({"code": "missing_field", "type": code})
    # existing units
    units = {code: 0 for code in now}
    for row in OrganizationalUnit.objects.filter(unit_type__isnull=False, active=True).values("unit_type__code").annotate(n=Count("id")):
        units[row["unit_type__code"]] = row["n"]
    for code in updated:
        if code in now and not proposed[code]["active"] and units.get(code):
            errors.append({"code": "type_in_use", "type": code, "units": units[code]})
    bad_pairs = 0
    sample = []
    pairs = OrganizationalUnit.objects.filter(unit_type__isnull=False, parent__unit_type__isnull=False, active=True).values_list(
        "code", "unit_type__code", "parent__code", "parent__unit_type__code")
    for ucode, utype, pcode, ptype in pairs:
        if utype in proposed and ptype in proposed and proposed[utype]["tier"] <= proposed[ptype]["tier"]:
            bad_pairs += 1
            if len(sample) < 20:
                sample.append({"unit": ucode, "type": utype, "parent": pcode, "parent_type": ptype})
    if bad_pairs:
        errors.append({"code": "existing_units_conflict", "count": bad_pairs, "sample": sample})
    seen, unique = set(), []
    for e in errors:  # stable, de-duplicated
        key = (e["code"], e.get("type"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return {"errors": unique, "created": created, "updated": updated,
            "units_by_type": {c: n for c, n in units.items() if n},
            "affected_units": sum(units.get(c, 0) for c in updated)}


@transaction.atomic
def apply(change, actor, request=None):
    """Re-evaluate against the *current* catalogue (it may have changed since submission), then write."""
    report = evaluate(change.operations)
    if report["errors"]:
        raise ValidationError({"operations": [ErrorDetail("The proposal no longer applies.", code="proposal_invalid")]})
    types = {t.code: t for t in UnitType.objects.select_for_update()}
    for op in change.operations:  # phase 1: create (parents are linked in phase 2, so order inside a proposal is free)
        if op["op"] == "create":
            body = {k: v for k, v in op.items() if k not in ("op", "code", "parent_type")}
            types[op["code"]] = UnitType.objects.create(code=op["code"], **body)
            record("unit_type.create", request=request, actor=actor, entity_type="unit_type", entity_id=types[op["code"]].pk,
                   metadata={"code": op["code"], "via": "structure_change", "change": str(change.pk)})
    for op in change.operations:  # phase 2: field updates and parent links
        t = types[op["code"]]
        fields = op["fields"] if op["op"] == "update" else {k: v for k, v in op.items() if k in ("parent_type",)}
        if not fields:
            continue
        for k, v in fields.items():
            if k == "parent_type":
                t.parent_type = types[v] if v else None
            else:
                setattr(t, k, v)
        t.version += 1
        t.updated_at = timezone.now()
        t.save()
        if op["op"] == "update":
            record("unit_type.update", request=request, actor=actor, entity_type="unit_type", entity_id=t.pk,
                   metadata={"fields": sorted(fields), "via": "structure_change", "change": str(change.pk)})
    return report
