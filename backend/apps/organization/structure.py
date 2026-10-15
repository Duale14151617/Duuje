"""Read-only analysis of the organizational template: reference vs actual strength and structure findings.

Everything is derived from existing records. Nothing here creates, edits or fills in personnel or units, and none of
it blocks anything: reference figures and the standard template are information, and variations are allowed.
"""
from collections import defaultdict

from django.db.models import Count, Q

from apps.accounts import scope
from apps.personnel.models import Personnel

from .models import DesignationRule, OrganizationalUnit, UnitType

SERVING = ~Q(status__in=["retired", "discharged"])  # strength counts people still in service


def _ancestor_prefixes(path):
    """'/a/b/c/' -> ['/a/', '/a/b/', '/a/b/c/'] (every ancestor path including the unit itself)."""
    parts = path.strip("/").split("/")
    return ["/" + "/".join(parts[: i + 1]) + "/" for i in range(len(parts))]


def subtree_strength(user, units):
    """{unit_path: serving personnel in that unit's subtree}, only for units the user may see personnel for.

    Strength is personnel data, so it needs personnel.view covering the unit; otherwise the value is None.
    """
    pq = scope.unit_scope_q(user, "personnel.view", "org_unit__")
    if pq is None:
        return {}
    direct = (Personnel.objects.filter(pq).filter(SERVING).values("org_unit__path").annotate(n=Count("id")))
    totals = defaultdict(int)
    for row in direct:
        for prefix in _ancestor_prefixes(row["org_unit__path"]):
            totals[prefix] += row["n"]
    return totals


def strength_status(unit, utype, actual):
    """('no_reference'|'unknown'|'below'|'within'|'above', has_exception, lo, hi). Informational only."""
    has_exception = unit.strength_exception_min is not None or unit.strength_exception_max is not None
    if has_exception:
        lo, hi = unit.strength_exception_min, unit.strength_exception_max
    else:
        lo, hi = (utype.reference_min, utype.reference_max) if utype else (None, None)
    if lo is None and hi is None:
        return "no_reference", has_exception, lo, hi
    if actual is None:
        return "unknown", has_exception, lo, hi
    if lo is not None and actual < lo:
        return "below", has_exception, lo, hi
    if hi is not None and actual > hi:
        return "above", has_exception, lo, hi
    return "within", has_exception, lo, hi


def findings(user):
    """Deviations from the standard template, for units inside the user's org.view scope."""
    units = list(scope.scoped_units(user, "org.view").filter(active=True)
                 .select_related("unit_type", "parent__unit_type").prefetch_related("designations"))
    by_id = {u.pk: u for u in units}
    out = []

    def brief(u):
        return {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}

    # 1. standard number of children of a given type (two Gaas under each Qayb)
    children = defaultdict(lambda: defaultdict(int))
    for u in units:
        if u.parent_id in by_id and u.unit_type_id:
            children[u.parent_id][u.unit_type_id] += 1
    for t in UnitType.objects.filter(active=True, standard_per_parent__isnull=False, parent_type__isnull=False):
        for u in units:
            if u.unit_type_id == t.parent_type_id:
                actual = children[u.pk][t.pk]
                if actual != t.standard_per_parent:
                    out.append({"code": "child_count", "unit": brief(u), "type": t.code,
                                "expected": t.standard_per_parent, "actual": actual})

    # 2. a unit of a type whose parent does not have the template's parent type (a variation, flagged for review)
    for u in units:
        t, p = u.unit_type, u.parent
        if t and t.parent_type_id and p and p.unit_type_id and p.unit_type_id != t.parent_type_id:
            out.append({"code": "non_standard_parent", "unit": brief(u), "type": t.code, "parent_type": p.unit_type.code})

    # 3. designated specialist unit below each parent type (Guuto -> Horin Sahan, Gaas -> Urur Sahan/Sanco)
    designated = defaultdict(set)  # (child_type_id, designation_id) -> ancestor paths that have one
    for u in units:
        if u.unit_type_id:
            for d in u.designations.all():
                for prefix in _ancestor_prefixes(u.path)[:-1]:
                    designated[(u.unit_type_id, d.pk)].add(prefix)
    for rule in DesignationRule.objects.filter(active=True, designation__active=True).select_related(
            "parent_type", "child_type", "designation"):
        for u in units:
            if u.unit_type_id == rule.parent_type_id and u.path not in designated[(rule.child_type_id, rule.designation_id)]:
                out.append({"code": "missing_designated_unit", "unit": brief(u), "rule": str(rule.pk),
                            "parent_type": rule.parent_type.code, "child_type": rule.child_type.code,
                            "designation": rule.designation.code})
    return out
