"""Organizational profiles: unit profile, department profile, organizational chart and analytics.

Everything here is READ-ONLY and built on the rules the system already has:
  * which units a caller may see        -> scope.scoped_units(user, "org.view")
  * which people a caller may count     -> personnel.view (or changes.propose, as the unit overview already allows)
  * which people a caller may NAME      -> personnel.view only, minus restricted departments (finance, medical ...)
                                           unless the caller holds `departments.view_restricted` for that unit
  * restricted (confidential) units     -> the existing gate inside the scope engine

Nothing is invented: a unit without a commander shows no commander, a department nobody leads shows no head. Strength figures
are counted from personnel rows, once each. "Active" means status == active; "inactive" is every other status (on leave,
suspended, jailed, retired, discharged, died); the status breakdown is always returned next to it.
"""
from collections import Counter, defaultdict

from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts import scope

from .models import Department, OrganizationalUnit, UnitDepartment

STANDARD_DEPARTMENTS = ("COMMAND_ADMIN", "HR", "MEDICAL", "FINANCE", "LOGISTICS", "COMMUNICATIONS", "TRAINING")
GHQ_UNIT_CODE = "ARMY-HQ"  # the Army Headquarters (Taliska Guud) is the General Headquarters of the organization
NAMED_CAP = 300  # names listed on one profile; the directory (paged) holds the complete list
ROLE_ORDER = ("commander", "deputy", "administrative")
CHART_ROLES = ("ghq", "regional", "brigade", "battalion")


# --------------------------------------------------------------------------------------------------- who may see what
def _union(user, codes, prefix="org_unit__"):
    q = None
    for code in codes:
        part = scope.unit_scope_q(user, code, prefix)
        if part is not None:
            q = part if q is None else (q | part)
    return q


def counting_q(user):
    """Rows the caller may COUNT (aggregates only). None when the caller may count nobody."""
    return _union(user, ("personnel.view", "changes.propose"))


def named_q(user):
    """Rows the caller may NAME. None when the caller may not see personnel names anywhere."""
    return scope.unit_scope_q(user, "personnel.view", "org_unit__")


def restricted_departments_exist():
    return Department.objects.filter(restricted_roster=True).exists()


def apply_roster_gate(user, qs, *, own=True):
    """Hide people of restricted departments (finance, medical ...) from callers who lack `departments.view_restricted` for
    their unit. A person always sees their own record, and a supervisor the records of the people who report to them
    (the existing team rule). Rows without a department are never hidden."""
    if not restricted_departments_exist():
        return qs
    cond = ~Q(department__restricted_roster=True)
    allowed = scope.unit_scope_q(user, "departments.view_restricted", "org_unit__")
    if allowed is not None:
        cond |= allowed
    if own:
        cond |= Q(account_id=user.pk) | Q(supervisor__account_id=user.pk)
    return qs.filter(cond)


def _personnel(user, mode):
    from apps.personnel.models import Personnel

    q = counting_q(user) if mode == "count" else named_q(user)
    if q is None:
        return Personnel.objects.none()
    qs = Personnel.objects.filter(q)
    return qs if mode == "count" else apply_roster_gate(user, qs)


def can_name(user, unit):
    return scope.can(user, "personnel.view", unit=unit) or scope.can(user, "changes.propose", unit=unit)


def can_see_restricted(user, unit):
    return scope.can(user, "departments.view_restricted", unit=unit)


# ----------------------------------------------------------------------------------------------------------- helpers
def _bucket(rows):
    """[(status, n)] -> {"total", "active", "inactive", "by_status"}."""
    by_status = {}
    for status, n in rows:
        by_status[status] = by_status.get(status, 0) + n
    total = sum(by_status.values())
    active = by_status.get("active", 0)
    return {"total": total, "active": active, "inactive": total - active, "by_status": by_status}


def _brief_unit(u):
    return {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so, "level": u.level,
            "unit_type": u.unit_type.code if u.unit_type_id else None,
            "formation_role": (u.unit_type.formation_role if u.unit_type_id else "") or "", "is_active": u.active}


def _brief_department(d):
    return {"id": str(d.pk), "code": d.code, "name_en": d.name_en, "name_so": d.name_so, "restricted": d.restricted_roster}


def _person(p):
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number, "status": p.status,
            "rank": {"id": str(p.rank_id), "code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so},
            "department": _brief_department(p.department) if p.department_id else None,
            "org_unit": {"id": str(p.org_unit_id), "code": p.org_unit.code, "name_en": p.org_unit.name_en,
                         "name_so": p.org_unit.name_so}}


def current_appointments(units=None, unit_ids=None):
    """Open appointments that have started and not yet reached their end date."""
    from apps.personnel.models import CommandAppointment

    today = timezone.localdate()
    qs = CommandAppointment.objects.filter(ended_at__isnull=True, effective_from__lte=today).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today))
    if unit_ids is not None:
        qs = qs.filter(org_unit_id__in=unit_ids)
    elif units is not None:
        qs = qs.filter(org_unit__in=units)
    return qs.select_related("appointment_type", "org_unit", "department", "personnel__rank", "personnel__department")


def _holder(a, *, names_ok, user):
    """The person holding an appointment, or None when the caller may not see names (or the department's roster)."""
    if not names_ok:
        return None
    p = a.personnel
    if p.department_id and p.department.restricted_roster and not can_see_restricted(user, a.org_unit):
        if p.account_id != user.pk:
            return None
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
            "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}


def _appointment(a, *, names_ok, user):
    return {"id": str(a.pk), "type": a.appointment_type.code, "type_en": a.appointment_type.name_en,
            "type_so": a.appointment_type.name_so, "role": a.appointment_type.role, "effective_from": a.effective_from,
            "department": _brief_department(a.department) if a.department_id else None,
            "holder": _holder(a, names_ok=names_ok, user=user)}


def _grouped(qs, *fields):
    """Rows of (*fields, n): one grouped query (default ordering cleared so it cannot widen the GROUP BY)."""
    return qs.order_by().values_list(*fields).annotate(n=Count("id"))


def _by_unit_status(qs):
    """Counter of (unit path, status) for a personnel queryset: one grouped query."""
    return Counter({(p, s): n for p, s, n in _grouped(qs, "org_unit__path", "status")})


def _rank_distribution(qs):
    rows = [{"rank": {"id": str(r), "code": c, "name_en": en, "name_so": so}, "sort_order": order, "count": n}
            for r, c, en, so, order, n in _grouped(qs, "rank_id", "rank__code", "rank__name_en", "rank__name_so", "rank__sort_order")]
    rows.sort(key=lambda x: (-x["sort_order"], x["rank"]["code"]))
    return rows


def _rollup(counter, path):
    return _bucket(((s, n) for (p, s), n in counter.items() if p.startswith(path)))


def _direct(counter, path):
    return _bucket(((s, n) for (p, s), n in counter.items() if p == path))


# ------------------------------------------------------------------------------------------------------ unit profile
def unit_profile(user, unit):
    """One unit: identification, leadership, departments, sub-units, strength and distribution. Aggregates always (for callers
    who may count); names only for callers who may see personnel and, for restricted departments, the restricted roster."""
    names_ok = can_name(user, unit)
    sub = _personnel(user, "count").filter(org_unit__path__startswith=unit.path)
    counter = _by_unit_status(sub)
    stats = _rollup(counter, unit.path)
    stats["direct"] = _direct(counter, unit.path)["total"]

    # --- leadership: current appointments of this unit that are not department offices
    appts = [a for a in current_appointments(unit_ids=[unit.pk]) if a.department_id is None]
    leadership = {role: [] for role in ROLE_ORDER}
    other = []
    for a in appts:
        item = _appointment(a, names_ok=names_ok, user=user)
        (leadership[a.appointment_type.role] if a.appointment_type.role in leadership else other).append(item)

    # --- departments: those the unit has established, plus any department that has people in the unit's subtree
    est = {ud.department_id: ud for ud in UnitDepartment.objects.filter(unit=unit, active=True).select_related("department")}
    dept_counts = defaultdict(Counter)
    for dept_id, status, n in _grouped(sub, "department_id", "status"):
        dept_counts[dept_id][status] += n
    dept_offices = defaultdict(dict)
    for a in current_appointments(unit_ids=[unit.pk]):
        if a.department_id:
            dept_offices[a.department_id].setdefault(a.appointment_type.role, []).append(a)
    dept_ids = set(est) | {d for d in dept_counts if d is not None}
    depts = {d.pk: d for d in Department.objects.filter(pk__in=dept_ids)}
    unassigned = _bucket(dept_counts.get(None, Counter()).items())
    departments = []
    for d in sorted(depts.values(), key=lambda x: (x.sort_order, x.code)):
        b = _bucket(dept_counts.get(d.pk, Counter()).items())
        offices = dept_offices.get(d.pk, {})
        head = [_appointment(a, names_ok=names_ok, user=user) for a in offices.get("department_head", [])]
        deputy = [_appointment(a, names_ok=names_ok, user=user) for a in offices.get("department_deputy", [])]
        departments.append({"department": _brief_department(d), "established": d.pk in est, "established_active": d.pk in est and d.active,
                            "head": head[0] if head else None, "deputy": deputy[0] if deputy else None,
                            "staff": b["total"], "active": b["active"], "inactive": b["inactive"]})

    # --- medical and finance staff (the departments with these codes), named only where the roster gate allows
    def function_block(code):
        d = next((x for x in depts.values() if x.code == code), None)
        if d is None:
            return {"department": None, "count": 0, "active": 0, "people": None, "roster_hidden": False}
        b = _bucket(dept_counts.get(d.pk, Counter()).items())
        hidden = d.restricted_roster and not can_see_restricted(user, unit)
        people = None
        if names_ok and not hidden:
            rows = _personnel(user, "name").filter(org_unit__path__startswith=unit.path, department=d)
            people = [_person(p) for p in rows.select_related("rank", "org_unit", "department").order_by("rank__sort_order", "full_name")[:NAMED_CAP]]
        return {"department": _brief_department(d), "count": b["total"], "active": b["active"], "people": people,
                "roster_hidden": hidden}

    # --- rank distribution
    by_rank = _rank_distribution(sub)

    # --- direct sub-units with their own totals
    kids = list(scope.scoped_units(user, "org.view").filter(parent=unit, active=True).select_related("unit_type").order_by("code"))
    children = []
    for k in kids:
        kb = _rollup(counter, k.path)
        children.append({**_brief_unit(k), "total": kb["total"], "active": kb["active"], "inactive": kb["inactive"],
                         "direct": _direct(counter, k.path)["total"]})
    parent = unit.parent if unit.parent_id and scope.scoped_units(user, "org.view").filter(pk=unit.parent_id).exists() else None
    chain = [{"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}
             for u in scope.scoped_units(user, "org.view").filter(path__in=_ancestors(unit)).order_by("path")]
    unit = OrganizationalUnit.objects.select_related("unit_type", "parent").get(pk=unit.pk)
    return {
        "unit": {**_brief_unit(unit), "restricted": unit.restricted, "version": unit.version,
                 "parent": _brief_unit(parent) if parent else None},
        "breadcrumb": chain,
        "leadership": {**leadership, "other": other},
        "departments": departments,
        "unassigned_department": unassigned,
        "medical": function_block("MEDICAL"),
        "finance": function_block("FINANCE"),
        "children": children,
        "stats": stats,
        "by_rank": by_rank,
        "can": {"name": names_ok, "manage": scope.can(user, "org.manage", unit=unit),
                "appoint": scope.can(user, "personnel.appointments_manage", unit=unit),
                "restricted": can_see_restricted(user, unit)},
        "counts_complete": counting_q(user) is not None,
    }


def _ancestors(unit):
    parts = [p for p in unit.path.split("/") if p]
    return ["/" + "/".join(parts[:i]) + "/" for i in range(1, len(parts))]


# ------------------------------------------------------------------------------------------------ department profile
def department_profile(user, unit, department):
    """One department of one unit: leadership, deputy, staff (assigned to this unit) and assigned personnel (below it)."""
    names_ok = can_name(user, unit)
    est = UnitDepartment.objects.filter(unit=unit, department=department).first()
    appts = [a for a in current_appointments(unit_ids=[unit.pk]) if a.department_id == department.pk]
    head = next((a for a in appts if a.appointment_type.role == "department_head"), None)
    deputy = next((a for a in appts if a.appointment_type.role == "department_deputy"), None)
    base = _personnel(user, "count").filter(org_unit__path__startswith=unit.path, department=department)
    stats = _bucket(_grouped(base, "status"))
    roster_hidden = department.restricted_roster and not can_see_restricted(user, unit)
    staff = assigned = None
    staff_total = base.filter(org_unit=unit).count()
    assigned_total = base.exclude(org_unit=unit).count()
    if names_ok and not roster_hidden:
        named = _personnel(user, "name").filter(org_unit__path__startswith=unit.path, department=department).select_related(
            "rank", "org_unit", "department").order_by("rank__sort_order", "full_name")
        staff = [_person(p) for p in named.filter(org_unit=unit)[:NAMED_CAP]]
        assigned = [_person(p) for p in named.exclude(org_unit=unit)[:NAMED_CAP]]
    unit = OrganizationalUnit.objects.select_related("unit_type").get(pk=unit.pk)
    return {
        "unit": _brief_unit(unit), "department": {**_brief_department(department), "description_en": department.description_en,
                                                  "description_so": department.description_so},
        "established": bool(est and est.active), "head": _appointment(head, names_ok=names_ok, user=user) if head else None,
        "deputy": _appointment(deputy, names_ok=names_ok, user=user) if deputy else None,
        "stats": stats, "staff": staff, "assigned": assigned, "staff_total": staff_total, "assigned_total": assigned_total,
        "roster_hidden": roster_hidden,
        "can": {"name": names_ok, "manage": scope.can(user, "org.manage", unit=unit),
                "appoint": scope.can(user, "personnel.appointments_manage", unit=unit)},
    }


# ----------------------------------------------------------------------------------------------------- organization chart
def chart(user, include_inactive=False):
    """Expandable chart: General Headquarters > regional commands > brigades > battalions, each with its strength. Units below a
    battalion (and sections) are counted inside their formation, so the chart stays readable and every person is counted once."""
    units_qs = scope.scoped_units(user, "org.view").select_related("unit_type")
    if not include_inactive:
        units_qs = units_qs.filter(active=True)
    units = list(units_qs.order_by("path"))
    counter = _by_unit_status(_personnel(user, "count"))
    nodes, roots = {}, []
    chart_units = [u for u in units if u.unit_type_id and u.unit_type.formation_role in CHART_ROLES]
    for u in chart_units:
        b = _rollup(counter, u.path)
        nodes[u.pk] = {**_brief_unit(u), "total": b["total"], "active": b["active"], "inactive": b["inactive"], "children": []}
    by_path = {u.path: u for u in chart_units}
    for u in chart_units:  # path order: parents first; a unit whose nearest formation ancestor is out of scope becomes a root
        parent = None
        for path in reversed(_ancestors(u)):
            cand = by_path.get(path)
            if cand is not None:
                parent = nodes[cand.pk]
                break
        (parent["children"] if parent else roots).append(nodes[u.pk])
    # General Headquarters comes first and carries the regional commands (they sit side by side in the unit tree, but
    # operationally they answer to it); then regions, brigades, battalions, each level ordered by code.
    ghq = next((n for n in roots if n["formation_role"] == "ghq"), None)
    if ghq is not None:
        rest = [n for n in roots if n is not ghq]
        ghq["children"] = rest + ghq["children"]
        for n in rest:
            for k in ("total", "active", "inactive"):
                ghq[k] += n[k]
        roots = [ghq]
    order = {r: i for i, r in enumerate(CHART_ROLES)}

    def sort(ns):
        ns.sort(key=lambda n: (order.get(n["formation_role"], 9), n["code"]))
        for n in ns:
            sort(n["children"])
    sort(roots)
    return {"count": len(nodes), "roots": roots, "counts_complete": counting_q(user) is not None}


# ------------------------------------------------------------------------------------------------------------ analytics
def analytics(user, root=None):
    """Organization-wide figures for the units the caller may see, optionally below one unit. Aggregates only."""
    sub = _personnel(user, "count")
    if root is not None:
        sub = sub.filter(org_unit__path__startswith=root.path)
    counter = _by_unit_status(sub)
    totals = _bucket(((s, n) for (p, s), n in counter.items()))

    units_qs = scope.scoped_units(user, "org.view").filter(active=True).select_related("unit_type", "parent")
    if root is not None:
        units_qs = units_qs.filter(path__startswith=root.path)
    units = list(units_qs.order_by("path"))
    chart_units = [u for u in units if u.unit_type_id and u.unit_type.formation_role in CHART_ROLES]

    by_formation = {role: [] for role in CHART_ROLES}
    for u in chart_units:
        b = _rollup(counter, u.path)
        by_formation[u.unit_type.formation_role].append({
            **_brief_unit(u), "parent_id": str(u.parent_id) if u.parent_id else None,
            "total": b["total"], "active": b["active"], "inactive": b["inactive"]})

    # department staffing: people per department, and how many units have established / staffed / led each
    dept_rows = list(Department.objects.filter(active=True))
    per_dept = defaultdict(Counter)
    for d, s, n in _grouped(sub, "department_id", "status"):
        per_dept[d][s] += n
    unit_ids = {u.pk for u in units}
    est = defaultdict(set)
    for ud in UnitDepartment.objects.filter(active=True, unit_id__in=unit_ids):
        est[ud.department_id].add(ud.unit_id)
    heads, deputies = defaultdict(set), defaultdict(set)
    appts = list(current_appointments(unit_ids=unit_ids))
    for a in appts:
        if a.department_id and a.appointment_type.role == "department_head":
            heads[a.department_id].add(a.org_unit_id)
        elif a.department_id and a.appointment_type.role == "department_deputy":
            deputies[a.department_id].add(a.org_unit_id)
    departments = []
    for d in dept_rows:
        b = _bucket(per_dept.get(d.pk, Counter()).items())
        e = est.get(d.pk, set())
        departments.append({"department": _brief_department(d), "established_in": len(e), "with_head": len(e & heads.get(d.pk, set())),
                            "with_deputy": len(e & deputies.get(d.pk, set())), "total": b["total"], "active": b["active"],
                            "inactive": b["inactive"]})
    unassigned = _bucket(per_dept.get(None, Counter()).items())

    # leadership summary for the chart units: who has a commander and a deputy, and where the gaps are
    have = defaultdict(set)
    for a in appts:
        if a.department_id is None and a.appointment_type.role in ("commander", "deputy"):
            have[a.org_unit_id].add(a.appointment_type.role)
    gaps, with_cmd, with_dep = [], 0, 0
    for u in chart_units:
        h = have.get(u.pk, set())
        with_cmd += "commander" in h
        with_dep += "deputy" in h
        missing = [r for r in ("commander", "deputy") if r not in h]
        if missing:
            gaps.append({**_brief_unit(u), "missing": missing})
    for rows in by_formation.values():
        rows.sort(key=lambda r: r["code"])
    leadership = {"units": len(chart_units), "with_commander": with_cmd, "with_deputy": with_dep,
                  "vacancies": gaps[:200], "vacancies_total": len(gaps)}

    by_rank = _rank_distribution(sub)
    return {"totals": totals, "by_formation": by_formation, "departments": departments, "unassigned_department": unassigned,
            "leadership": leadership, "by_rank": by_rank, "root": _brief_unit(root) if root is not None else None,
            "counts_complete": counting_q(user) is not None}


def establish_standard_departments():
    """Establish the seven standard departments in every headquarters, region, regional command, brigade and battalion.
    Additive and idempotent: it only creates what is missing, so a department an administrator has retired stays retired.
    No people and no appointments are created. Returns the number of departments established."""
    units = OrganizationalUnit.objects.filter(active=True).filter(
        Q(unit_type__formation_role__in=CHART_ROLES) | Q(level__in=("headquarters", "region")))
    depts = list(Department.objects.filter(code__in=STANDARD_DEPARTMENTS, active=True))
    have = set(UnitDepartment.objects.filter(unit__in=units).values_list("unit_id", "department_id"))
    new = [UnitDepartment(unit_id=u, department=d) for u in units.values_list("pk", flat=True) for d in depts if (u, d.pk) not in have]
    UnitDepartment.objects.bulk_create(new)
    return len(new)
