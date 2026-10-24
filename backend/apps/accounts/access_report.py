"""Access report: every user, their username, roles, scope (where in the organization and which branch) and what they can do.

Read-only. Built from the same data the authorization engine uses (RoleAssignment -> Role -> Permission), so the report states what the
server will actually allow today. Never includes passwords, hashes, MFA secrets or reset tokens.
"""
from collections import defaultdict

from django.utils import timezone

from .models import Role, RoleAssignment, User

AREAS = {  # permission prefix -> readable area
    "dashboard": "Dashboard", "org": "Organization", "ranks": "Ranks", "personnel": "Personnel", "reports": "Reports",
    "training": "Training", "logistics": "Logistics", "analytics": "Analytics", "cid": "CID", "disciplinary": "Disciplinary",
    "documents": "Documents", "payroll": "Payroll", "survivor": "Survivor benefits", "payment": "Payments", "arrears": "Arrears",
    "weapons": "Weapons", "attendance": "Attendance", "users": "Users and roles", "audit": "Audit log", "police": "Police",
    "search": "Cross-service search", "integrations": "Integrations", "system": "System", "roles": "Roles",
}


def area(code):
    return AREAS.get(code.split(".")[0], code.split(".")[0].title())


def status_of(a, user, today):
    if a.revoked_at is not None:
        return "revoked"
    if not user.is_active:
        return "user disabled"
    if a.valid_from and a.valid_from > today:
        return "not started"
    if a.valid_until and a.valid_until < today:
        return "expired"
    return "active"


def scope_of(a):
    unit, branch = a.org_unit, a.branch
    glob = unit.level == "headquarters" and branch is None
    if glob:
        text = "Whole system (headquarters, all branches)"
    else:
        text = f"{unit.name_en} [{unit.code}] ({unit.level}) and every unit below it"
        text += f", {branch.name_en} branch only" if branch else ", all branches"
    return {"unit_code": unit.code, "unit_name": unit.name_en, "unit_level": unit.level, "unit_path": unit.path,
            "branch": branch.code if branch else None, "global": glob, "text": text}


def notes_for(perms, a):
    out = []
    if "cid.access" in perms:
        out.append("can reach restricted CID records")
    if "police.cross_access" in perms or (a.branch and a.branch.code == "POLICE"):
        out.append("can reach Police records")
    if "system.full_access" in perms:
        out.append("maintenance override: not hidden by module switches")
    if a.role.is_privileged:
        out.append("privileged role: MFA required")
    return out


def build(include_inactive=True):
    today = timezone.localdate()
    perm_desc = {}
    roles = []
    for r in Role.objects.prefetch_related("permissions").order_by("code"):
        perms = sorted(r.permissions.all(), key=lambda p: p.code)
        for p in perms:
            perm_desc[p.code] = p.description
        roles.append({"code": r.code, "name_en": r.name_en, "name_so": r.name_so, "privileged": r.is_privileged,
                      "requires_branch": r.requires_branch, "allowed_scope_levels": r.allowed_scope_levels,
                      "permissions": [{"code": p.code, "description": p.description} for p in perms]})
    users = []
    findings = defaultdict(list)
    qs = User.objects.order_by("username").prefetch_related(
        "assignments__role__permissions", "assignments__org_unit", "assignments__branch", "assignments__created_by")
    for u in qs:
        if not include_inactive and not u.is_active:
            continue
        rows = []
        for a in sorted(u.assignments.all(), key=lambda x: x.created_at):
            perms = sorted(p.code for p in a.role.permissions.all())
            st = status_of(a, u, today)
            row = {"role": a.role.code, "role_name": a.role.name_en, "status": st, "scope": scope_of(a),
                   "valid_from": a.valid_from.isoformat() if a.valid_from else None,
                   "valid_until": a.valid_until.isoformat() if a.valid_until else None,
                   "granted_by": a.created_by.username if a.created_by_id else None, "granted_at": a.created_at.isoformat(),
                   "permissions": perms, "areas": sorted({area(c) for c in perms}), "notes": notes_for(set(perms), a)}
            rows.append(row)
            if st == "active" and a.valid_until and (a.valid_until - today).days <= 30:
                findings["Assignments ending within 30 days"].append(f"{u.username}: {a.role.code} until {a.valid_until}")
            if st == "active" and a.role.is_privileged and not u.mfa_enabled:
                findings["Privileged role without MFA enrolled"].append(f"{u.username}: {a.role.code}")
            if st == "active" and row["scope"]["global"]:
                findings["Active whole-system access"].append(f"{u.username}: {a.role.code}")
        active = [r for r in rows if r["status"] == "active"]
        if u.is_active and not active:
            findings["Active users with no effective role"].append(u.username)
        if u.locked_until and u.locked_until > timezone.now():
            findings["Locked accounts"].append(u.username)
        eff = sorted({c for r in active for c in r["permissions"]})
        users.append({"username": u.username, "full_name": u.full_name, "email": u.email, "active": u.is_active, "mfa_enabled": u.mfa_enabled,
                      "must_change_password": u.must_change_password, "locked": bool(u.locked_until and u.locked_until > timezone.now()),
                      "created_at": u.created_at.isoformat(), "assignments": rows,
                      "effective_permission_count": len(eff), "effective_areas": sorted({area(c) for c in eff})})
    return {"generated_at": timezone.now().isoformat(), "users": users, "roles": roles, "findings": dict(findings),
            "summary": {"users": len(users), "active_users": sum(1 for u in users if u["active"]),
                        "assignments": sum(len(u["assignments"]) for u in users),
                        "active_assignments": sum(1 for u in users for r in u["assignments"] if r["status"] == "active")}}


def to_csv(report):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["username", "full_name", "user_active", "mfa", "role", "role_name", "assignment_status", "scope", "branch", "valid_from",
                "valid_until", "granted_by", "areas", "permissions", "notes"])
    for u in report["users"]:
        rows = u["assignments"] or [None]
        for r in rows:
            if r is None:
                w.writerow([u["username"], u["full_name"], u["active"], u["mfa_enabled"], "", "", "no role", "", "", "", "", "", "", "", ""])
                continue
            w.writerow([u["username"], u["full_name"], u["active"], u["mfa_enabled"], r["role"], r["role_name"], r["status"], r["scope"]["text"],
                        r["scope"]["branch"] or "all", r["valid_from"] or "", r["valid_until"] or "", r["granted_by"] or "",
                        "; ".join(r["areas"]), "; ".join(r["permissions"]), "; ".join(r["notes"])])
    return buf.getvalue()


def to_markdown(report):
    esc = lambda s: str(s).replace("|", "\\|")
    L = ["# Access report: users, roles, scope and capabilities", "", f"Generated {report['generated_at']}. Read-only; no passwords or secrets.", ""]
    s = report["summary"]
    L += [f"- Users: {s['users']} ({s['active_users']} active)", f"- Role assignments: {s['assignments']} ({s['active_assignments']} in force today)", ""]
    if report["findings"]:
        L += ["## Points to review", ""]
        for title, items in report["findings"].items():
            L += [f"**{title}** ({len(items)})", ""] + [f"- {i}" for i in items[:100]] + [""]
    L += ["## Users", "", "| Username | Name | Active | MFA | Role | Status | Scope | Valid until | Can work in |", "|---|---|---|---|---|---|---|---|---|"]
    for u in report["users"]:
        if not u["assignments"]:
            L.append(f"| {esc(u['username'])} | {esc(u['full_name'])} | {'yes' if u['active'] else 'no'} | {'yes' if u['mfa_enabled'] else 'no'} | none | - | - | - | - |")
        for r in u["assignments"]:
            L.append(f"| {esc(u['username'])} | {esc(u['full_name'])} | {'yes' if u['active'] else 'no'} | {'yes' if u['mfa_enabled'] else 'no'} | "
                     f"{esc(r['role'])} | {r['status']} | {esc(r['scope']['text'])} | {r['valid_until'] or '-'} | {esc(', '.join(r['areas']))} |")
    L += ["", "## What each role can do", ""]
    for r in report["roles"]:
        L += [f"### {r['role_name'] if 'role_name' in r else r['name_en']} (`{r['code']}`)", "",
              f"MFA required: {'yes' if r['privileged'] else 'no'}. Allowed scope levels: {', '.join(r['allowed_scope_levels']) or 'any'}."
              f"{' Needs a branch.' if r['requires_branch'] else ''}", ""]
        by = defaultdict(list)
        for p in r["permissions"]:
            by[area(p["code"])].append(p)
        for ar in sorted(by):
            L.append(f"- **{ar}:** " + "; ".join(f"`{p['code']}` {p['description']}" if p["description"] else f"`{p['code']}`" for p in by[ar]))
        L.append("")
    return "\n".join(L)
