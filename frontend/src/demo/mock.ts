/* eslint-disable */
// @ts-nocheck
/**
 * Built-in sample API for the standalone demo build (`npm run build:demo`, VITE_DEMO=1).
 * Every route answers with synthetic data held in memory; nothing is saved and no server is contacted.
 * Reconstructed from the compiled demo build (armyhq-demo-dist-2), so identifiers are short; behaviour is unchanged.
 * Routes the demo does not know answer 404 "Not available in the demo preview".
 */
import { ApiError as C } from "../api/client";
const a = (n) => new Date(Date.now() - n * 864e5).toISOString(), g = (n) => a(n).slice(0, 10), i = (n, e = n) => ({ name_en: n, name_so: e }), c = (n, e) => {
  const t = Number(e.page_size) || 25, r = Math.max(1, Number(e.page) || 1);
  return { count: n.length, next: null, previous: null, results: n.slice((r - 1) * t, r * t) };
}, E = [{ id: "b-army", code: "ARMY", ...i("Army", "Ciidanka Xoogga"), active: true, version: 1 }, { id: "b-navy", code: "NAVY", ...i("Navy", "Ciidanka Badda"), active: true, version: 1 }, { id: "b-police", code: "POLICE", ...i("Police", "Booliska"), active: true, version: 1 }], T = (n) => {
  const e = E.find((t) => t.id === n);
  return { id: e.id, code: e.code, name_en: e.name_en, name_so: e.name_so };
}, V = ["Dable", "Alifle", "2 Alifle", "Saddex Alifle", "Isbatoore", "Laba Xarigle", "Saddex Xarigle", "Xidigle", "Laba Xidigle", "Captain", "Gaashanle", "Gaashanle dhexe", "Gaashanle sare", "Sarreye Guuto (General)", "Sarreye Gaas", "Sarreye Guud (Marshall)", "Commander of the Puntland Defense Forces", "President / Commander-in-Chief"], m = V.map((n, e) => ({ id: `r-${e + 1}`, branch: "b-army", category: "unspecified", code: `PA-${String(e + 1).padStart(2, "0")}`, ...i(n), sort_order: e + 1, approval_status: "approved", approved_at: a(30), active: true, version: 1 })), j = [["TALISKA_GUUD", "Taliska Guud", 1, null, null, null, null, "Regional command"], ["QAYB", "Qayb", 2, "TALISKA_GUUD", null, 6e3, 7e3, ""], ["GAAS", "Gaas", 3, "QAYB", 2, 3500, 3500, ""], ["GUUTO", "Guuto", 4, "GAAS", null, 900, 1001, ""], ["URUR", "Urur", 5, "GUUTO", null, 320, 330, ""], ["HORIN", "Horin", 6, "URUR", null, 99, 99, ""], ["KOOX", "Koox", 7, "HORIN", null, 33, 33, ""], ["UNUG", "Unug", 8, "KOOX", null, 9, 9, ""]], D = j.map(([n, e, t, r, s, o, v, M]) => ({ id: `t-${n}`, code: n, ...i(e), tier: t, parent_type: r ? `t-${r}` : null, standard_per_parent: s, reference_min: o, reference_max: v, description_en: M, description_so: "", active: true, version: 1 })), F = [{ id: "d-SAHAN", code: "SAHAN", ...i("Sahan"), description_en: "Reconnaissance designation", description_so: "", active: true, version: 1 }, { id: "d-SANCO", code: "SANCO", ...i("Sanco"), description_en: "Miino baar / bomb squad designation", description_so: "", active: true, version: 1 }], W = [{ id: "dr-1", parent_type: "t-GUUTO", child_type: "t-HORIN", designation: "d-SAHAN", active: true, note: "Each Guuto has a designated Horin Sahan.", version: 1 }, { id: "dr-2", parent_type: "t-GAAS", child_type: "t-URUR", designation: "d-SAHAN", active: true, note: "Each Gaas has a designated Urur Sahan/Sanco.", version: 1 }, { id: "dr-3", parent_type: "t-GAAS", child_type: "t-URUR", designation: "d-SANCO", active: true, note: "Each Gaas has a designated Urur Sahan/Sanco.", version: 1 }], p = [];
function _(n, e, t, r, s, o, v, M = []) {
  const k = { id: `u-${n}`, code: n, ...i(e), level: t, parent: r ? `u-${r}` : null, branch: s, unit_type: o ? `t-${o}` : null, designations: M.map((X) => `d-${X}`), strength_exception_min: null, strength_exception_note: "", strength_exception_max: null, depth: v, active: true, version: 1 };
  return p.push(k), k;
}
_("PUNT-HQ", "Puntland Headquarters", "headquarters", null, null, null, 0);
for (const [n, e] of [["BARI", "Bari"], ["KARKAAR", "Karkaar"], ["NUGAAL", "Nugaal"], ["MUDUG", "Mudug"]]) _(n, `${e} Region`, "region", "PUNT-HQ", null, null, 1), _(`${n}-ARMY`, `${e} Army Command`, "branch_command", n, "b-army", "TALISKA_GUUD", 2), _(`${n}-POLICE`, `${e} Police Command`, "branch_command", n, "b-police", null, 2);
_("BARI-NAVY", "Bari Navy Command", "branch_command", "BARI", "b-navy", null, 2);
_("BARI-ARMY-QAYB-1", "Qayb 1", "unit", "BARI-ARMY", "b-army", "QAYB", 3);
_("BARI-ARMY-GAAS-A", "Gaas A", "unit", "BARI-ARMY-QAYB-1", "b-army", "GAAS", 4);
_("BARI-ARMY-GAAS-B", "Gaas B", "unit", "BARI-ARMY-QAYB-1", "b-army", "GAAS", 4);
_("BARI-ARMY-GUUTO-1", "Guuto 1", "unit", "BARI-ARMY-GAAS-A", "b-army", "GUUTO", 5);
_("BARI-ARMY-URUR-SAHAN", "Urur Sahan", "unit", "BARI-ARMY-GAAS-A", "b-army", "URUR", 5, ["SAHAN"]);
_("BARI-ARMY-DEMO-A", "Synthetic Unit A", "unit", "BARI-ARMY-GUUTO-1", "b-army", "HORIN", 6);
const f = (n) => {
  const e = p.find((t) => t.code === n);
  return { id: e.id, code: e.code, name_en: e.name_en, name_so: e.name_so, level: e.level, unit_type: e.unit_type };
}, H = (n) => p.filter((e) => e.parent === n).map((e) => ({ id: e.id, code: e.code, name_en: e.name_en, name_so: e.name_so, level: e.level, unit_type: e.unit_type, active: true, children: H(e.id) })), J = (n) => {
  const e = D.find((s) => s.id === n.unit_type), t = e != null && e.reference_min ? Math.round(e.reference_min * (0.9 + n.code.length % 4 * 0.05)) : null, r = !e || !e.reference_min ? "no_reference" : t < e.reference_min ? "below" : t > e.reference_max ? "above" : "within";
  return { id: n.id, code: n.code, name_en: n.name_en, name_so: n.name_so, level: n.level, active: true, parent: n.parent, unit_type: n.unit_type ?? "", designations: n.designations, reference_min: (e == null ? void 0 : e.reference_min) ?? null, reference_max: (e == null ? void 0 : e.reference_max) ?? null, has_exception: false, strength_exception_note: "", actual_strength: t, strength_status: r };
}, q = ["Abdi", "Hassan", "Farah", "Mohamed", "Ali", "Yusuf", "Ahmed", "Ismail", "Omar", "Liban", "Warsame", "Abshir"], Z = ["Jama", "Duale", "Warsame", "Hersi", "Mire", "Guled", "Saed", "Nur", "Osman", "Abdullahi"], B = ["active", "active", "active", "on_leave", "active", "suspended", "active", "retired"], I = ["BARI-ARMY-DEMO-A", "BARI-ARMY-GUUTO-1", "BARI-ARMY-GAAS-B", "KARKAAR-ARMY", "NUGAAL-ARMY", "MUDUG-ARMY"], d = Array.from({ length: 42 }, (n, e) => {
  const t = m[e * 5 % 16];
  return { id: `p-${e + 1}`, service_number: `DEMO-${String(e + 1).padStart(4, "0")}`, full_name: `${q[e % 12]} ${Z[e * 3 % 10]} (demo)`, phone: `+25290000${String(e + 1).padStart(4, "0")}`, branch: T("b-army"), org_unit: f(I[e % I.length]), rank: { id: t.id, code: t.code, name_en: t.name_en, name_so: t.name_so, approval_status: "approved" }, status: B[e % B.length], version: 1 };
}), K = ["analytics.view", "audit.view", "dashboard.view", "integrations.manage", "integrations.view", "logistics.approve", "logistics.configure", "logistics.manage", "logistics.reconcile", "logistics.report", "logistics.restricted", "logistics.restricted_approve", "logistics.view", "org.manage", "org.structure_approve", "org.structure_propose", "org.view", "personnel.export", "personnel.import", "personnel.manage", "personnel.view", "ranks.approve", "ranks.manage", "ranks.view", "reports.export", "reports.review", "reports.submit", "reports.summary", "reports.view", "roles.assign", "training.configure", "training.manage", "training.report", "training.view", "users.manage", "users.view"], L = { id: "role-hq", code: "hq_admin", ...i("HQ Administrator", "Maamulaha Xarunta"), is_privileged: true }, R = () => ({ id: "usr-1", username: "demo", full_name: "Demo Administrator", preferred_language: "en", mfa_enabled: true, requires_mfa: false, restrictions: [], permissions: K, features: { personnel_export: true, report_export: true, integrations: true }, assignments: [{ id: "as-1", role: L, org_unit: f("PUNT-HQ"), branch: null, valid_from: null, valid_until: null, revoked_at: null, created_at: a(60) }] }), h = ["demo", "bari.commander", "karkaar.officer", "nugaal.logistics", "mudug.trainer", "auditor"].map((n, e) => ({ id: `usr-${e + 1}`, username: n, full_name: n.replace(".", " ").replace(/\b\w/g, (t) => t.toUpperCase()), email: `${n.replace(".", "_")}@example.test`, preferred_language: "en", is_active: e !== 4, mfa_enabled: e % 2 === 0, must_change_password: false, last_login: a(e + 1), version: 1 })), ee = [L, { id: "role-reg", code: "regional_commander", ...i("Regional Commander"), is_privileged: false, requires_branch: false, allowed_scope_levels: ["region"], permissions: ["personnel.view", "org.view", "reports.view"] }, { id: "role-ro", code: "read_only", ...i("Read Only"), is_privileged: false, requires_branch: false, allowed_scope_levels: ["region", "branch_command"], permissions: ["dashboard.view"] }].map((n) => ({ requires_branch: false, allowed_scope_levels: ["headquarters"], permissions: K, ...n })), ne = Array.from({ length: 30 }, (n, e) => ({ id: `ae-${e}`, occurred_at: a(e * 0.3), actor_username: h[e % 4].username, action: ["auth.login", "rank.update", "personnel.create", "report.submit", "user.disable"][e % 5], entity_type: ["session", "rank", "personnel", "report", "user"][e % 5], entity_id: `x-${e}`, outcome: e % 9 === 8 ? "denied" : e % 11 === 10 ? "failure" : "success", correlation_id: `c0ffee${e}` })), U = [{ id: "n-1", kind: "submission_returned", created_at: a(0.2), read_at: null, submission: { id: "s-3", title: "Monthly readiness \u2013 Karkaar", status: "returned" } }, { id: "n-2", kind: "submission_approved", created_at: a(2), read_at: a(1), submission: { id: "s-1", title: "Monthly readiness \u2013 Bari", status: "approved" } }], P = [{ id: "rt-1", code: "READINESS", kind: "report", ...i("Monthly readiness"), figure_keys: ["personnel_present", "vehicles_ready"], separation_of_duties: true, active: true, version: 1 }, { id: "rt-2", code: "SUPPLY_REQ", kind: "request", ...i("Supply request"), figure_keys: ["items_requested"], separation_of_duties: true, active: true, version: 1 }], w = [["Monthly readiness \u2013 Bari", "approved", "BARI-ARMY"], ["Supply request \u2013 Nugaal", "under_review", "NUGAAL-ARMY"], ["Monthly readiness \u2013 Karkaar", "returned", "KARKAAR-ARMY"], ["Monthly readiness \u2013 Mudug", "submitted", "MUDUG-ARMY"]].map(([n, e, t], r) => ({ id: `s-${r + 1}`, report_type: P[r === 1 ? 1 : 0], org_unit: f(t), title: n, period_start: g(40), period_end: g(10), status: e, version: 1, current_revision: 1, submitter_username: h[r + 1].username, submitted_at: a(8 - r), decided_at: e === "approved" ? a(5) : null, updated_at: a(3) })), te = (n) => ({ ...n, body: "Synthetic demo report body.", figures: { personnel_present: 880, vehicles_ready: 14, items_requested: 120 }, capabilities: { edit: false, submit: false, start_review: n.status === "submitted", decide: n.status === "under_review", amend: false }, approved_revision_no: n.status === "approved" ? 1 : null, revisions: [{ revision_no: 1, title: n.title, body: "Synthetic demo report body.", figures: { personnel_present: 880 }, submitted_by_username: n.submitter_username, created_at: a(8) }], actions: [{ id: "a-1", revision_no: 1, action: "submit", from_status: "draft", to_status: "submitted", actor_username: n.submitter_username, comment: "", created_at: a(8) }] }), y = [{ id: "c-1", code: "general_supplies", ...i("General supplies"), kind: "stock", restricted: false, approval_status: "approved", active: true, version: 1 }, { id: "c-2", code: "vehicles", ...i("Vehicles"), kind: "asset", restricted: false, approval_status: "approved", active: true, version: 1 }], S = (n) => ({ id: n.id, code: n.code, name_en: n.name_en, name_so: n.name_so, kind: n.kind, restricted: n.restricted }), G = [["BARI-ARMY-DEMO-A", 40, 50, "boxes"], ["KARKAAR-ARMY", 300, 100, "boxes"], ["NUGAAL-ARMY", 12, 40, "litres"]].map(([n, e, t, r], s) => ({ id: `st-${s + 1}`, category: S(y[0]), org_unit: f(n), uom: r, quantity: e, reorder_level: t, below_reorder: e < t, version: 1 })), $ = [1, 2, 3].map((n) => ({ id: `as-${n}`, category: S(y[1]), org_unit: f("BARI-ARMY-DEMO-A"), identifier: `DEMO-VEH-00${n}`, description: "Synthetic demo vehicle", status: ["in_stock", "issued", "maintenance"][n - 1], issued_to_unit: null, custodian_username: null, version: 1 })), Y = [{ id: "rc-1", org_unit: f("BARI-ARMY-DEMO-A"), status: "open", includes_restricted: false, started_by_username: "demo", started_at: a(1), completed_at: null, version: 1, lines: [{ id: "l-1", kind: "stock", label: "General supplies", expected_quantity: 40, counted_quantity: null, found: null }, { id: "l-2", kind: "asset", label: "DEMO-VEH-001", expected_quantity: null, counted_quantity: null, found: null }] }], b = [["BASIC", "Basic training", 90], ["NCO", "NCO course", 45], ["MEDIC", "Combat first aid", 14]].map(([n, e, t], r) => ({ id: `co-${r + 1}`, code: n, ...i(e), duration_days: t, active: true, version: 1 })), O = ["completed", "in_progress", "enrolled", "failed", "completed"].map((n, e) => ({ id: `tr-${e + 1}`, personnel: { id: d[e].id, full_name: d[e].full_name, org_unit: d[e].org_unit }, course: { id: b[e % 3].id, code: b[e % 3].code, ...i(b[e % 3].name_en) }, status: n, start_date: g(60), end_date: g(10), completed_on: n === "completed" ? g(10) : null, notes: "", created_by_username: "demo", version: 1 })), re = [{ id: "ic-1", name: "Ministry data feed (demo)", description: "Synthetic read-only client", key_prefix: "ahq_demo", scopes: ["personnel.read"], org_unit: "u-PUNT-HQ", org_unit_code: "PUNT-HQ", expires_at: a(-200), status: "active", revoked_at: null, last_used_at: a(1), created_by_username: "demo", version: 1, created_at: a(30) }], se = [{ id: "sc-1", title: "Add Qayb reference strength note (demo)", rationale: "Illustrative proposal", operations: [{ op: "update", code: "QAYB", fields: { reference_max: 7e3 } }], status: "submitted", impact: { affected_units: 4, updated: ["QAYB"] }, proposed_by_username: "bari.commander", decided_by_username: "", decision_note: "", submitted_at: a(2), decided_at: null, version: 1, created_at: a(3) }], l = (n) => ({ total: n.reduce((e, t) => e + t.count, 0), rows: n, suppressed: false }), N = { personnel: { by_status: l([{ status: "active", count: 28 }, { status: "on_leave", count: 6 }, { status: "suspended", count: 4 }, { status: "retired", count: 4 }]), by_rank: l(m.slice(0, 6).map((n, e) => ({ ...i(n.name_en), code: n.code, count: 9 - e }))), by_branch: l([{ ...i("Army"), code: "ARMY", count: 42 }]), by_child_unit: l([{ unit: f("BARI-ARMY"), count: 18 }, { unit: f("KARKAAR-ARMY"), count: 12 }]), changes_by_month: l([{ month: g(60).slice(0, 7), field: "rank", count: 3 }, { month: g(30).slice(0, 7), field: "status", count: 5 }]) }, reports: { approved_by_type: l([{ ...i("Monthly readiness"), code: "READINESS", count: 7 }]), approved_by_month: l([{ month: g(30).slice(0, 7), count: 4 }]), pipeline: { by_status: l([{ status: "submitted", count: 2 }, { status: "approved", count: 7 }]), turnaround_hours: { median: 30, mean: 36 } } }, logistics: { stock_by_category: l([{ ...i("General supplies"), code: "general_supplies", count: 352 }]), low_stock_lines: 2, assets_by_status: l([{ status: "in_stock", count: 1 }, { status: "issued", count: 1 }, { status: "maintenance", count: 1 }]) }, training: { by_course: l(b.map((n, e) => ({ ...i(n.name_en), code: n.code, count: 10 - e * 3, completion_rate: 0.8 - e * 0.15 }))), completions_by_month: l([{ month: g(30).slice(0, 7), count: 6 }]) } };
let Q = (() => {
  try {
    return sessionStorage.getItem("armyhq.demo") === "1";
  } catch {
    return false;
  }
})();
const x = (n) => {
  Q = n;
  try {
    sessionStorage.setItem("armyhq.demo", n ? "1" : "0");
  } catch {
  }
}, z = () => new C(404, { code: "not_found", detail: "Not available in the demo preview" }), u = (n, e) => {
  const t = n.find((r) => r.id === e);
  if (!t) throw z();
  return t;
};
function A(n, e, t = {}) {
  return n.filter((r) => Object.entries(e).every(([s, o]) => o === "" || s === "page" || s === "page_size" || s === "placeable" || s === "at" ? true : t[s] ? t[s](r, o) : s === "q" ? JSON.stringify(r).toLowerCase().includes(o.toLowerCase()) : s in r && typeof r[s] != "object" ? String(r[s]) === o : true));
}
function ie(n, e) {
  let t;
  if (n === "/auth/csrf/") return { csrf_token: "demo" };
  if (n === "/auth/me/") {
    if (!Q) throw new C(401, { code: "not_authenticated", detail: "Sign in" });
    return R();
  }
  if (n === "/dashboard/") return { scope: { units_in_scope: p.length, regions_in_scope: 4, branch_commands_in_scope: 9 }, ranks: { draft: 0, approved: m.length }, accounts: { active: 5, disabled: 1, privileged_without_mfa: 0 }, audit: { events_24h: 14, failed_logins_24h: 1, denied_24h: 2 }, personnel: { total: d.length, active: d.filter((r) => r.status === "active").length }, reports: { my_open: 1, awaiting_review: 2 }, logistics: { low_stock: 2, assets_attention: 1 }, training: { in_progress: 3, enrolled: 4 } };
  if (n === "/notifications/unread-count/") return { count: U.filter((r) => !r.read_at).length };
  if (n === "/notifications/") return c(U, e);
  if (n === "/ranks/") return c(A(m, e), e);
  if (n === "/organization/branches/") return c(E, e);
  if (n === "/organization/units/tree/") return { count: p.length, truncated: false, roots: H(null) };
  if (n === "/organization/units/") return c(A(p, e, { parent: (r, s) => r.parent === s }), e);
  if (n === "/organization/unit-types/") return D;
  if (n === "/organization/designations/") return F;
  if (n === "/organization/designation-rules/") return W;
  if (n === "/organization/structure/") return c(p.filter((r) => r.unit_type).map(J), e);
  if (n === "/organization/structure/findings/") return { count: 0, truncated: false, results: [] };
  if (n === "/organization/structure-changes/") return c(se, e);
  if (n === "/personnel/") return c(A(d, e, { org_unit: (r, s) => r.org_unit.id === s, q: (r, s) => (r.full_name + r.service_number).toLowerCase().includes(s.toLowerCase()) }), e);
  if (t = n.match(/^\/personnel\/([^/]+)\/history\/$/)) return [{ id: "h-1", field: "rank", old_label: "Alifle", new_label: u(d, t[1]).rank.name_en, effective_date: g(120), reason: "Synthetic demo record", recorded_at: a(120), recorded_by_username: "demo" }];
  if (t = n.match(/^\/personnel\/([^/]+)\/$/)) return u(d, t[1]);
  if (n === "/users/") return c(A(h, e), e);
  if (t = n.match(/^\/users\/([^/]+)\/assignments\/$/)) return R().assignments;
  if (t = n.match(/^\/users\/([^/]+)\/$/)) return u(h, t[1]);
  if (n === "/roles/") return ee;
  if (n === "/audit-events/") return c(A(ne, e), e);
  if (n === "/reports/types/") return P;
  if (n === "/reports/submissions/") return c(A(w, e), e);
  if (t = n.match(/^\/reports\/submissions\/([^/]+)\/$/)) return te(u(w, t[1]));
  if (n === "/reports/summary/") {
    const r = { submissions: 7, totals: { personnel_present: 5400, vehicles_ready: 96 } };
    return { consolidated: r, figure_keys: ["personnel_present", "vehicles_ready"], regions: ["BARI", "KARKAAR", "NUGAAL", "MUDUG"].map((s) => ({ ...r, submissions: 2, totals: { personnel_present: 1350, vehicles_ready: 24 }, region: { id: `u-${s}`, code: s, ...i(p.find((o) => o.code === s).name_en) } })) };
  }
  if (n === "/logistics/categories/") return y;
  if (n === "/logistics/stock/") return c(A(G, e), e);
  if (t = n.match(/^\/logistics\/stock\/([^/]+)\/transactions\/$/)) return c([{ id: "tx-1", kind: "receipt", delta: 40, balance_after: 40, reason: "Opening balance (demo)", counterpart_unit: null, actor_username: "demo", created_at: a(20) }], e);
  if (t = n.match(/^\/logistics\/stock\/([^/]+)\/$/)) return u(G, t[1]);
  if (n === "/logistics/assets/") return c(A($, e), e);
  if (t = n.match(/^\/logistics\/assets\/([^/]+)\/events\/$/)) return [];
  if (t = n.match(/^\/logistics\/assets\/([^/]+)\/$/)) return u($, t[1]);
  if (n === "/logistics/reconciliations/") return c(Y.map(({ lines: r, ...s }) => s), e);
  if (t = n.match(/^\/logistics\/reconciliations\/([^/]+)\/$/)) return u(Y, t[1]);
  if (n === "/logistics/summary/") return { rows: [{ category: S(y[0]), region: { id: "u-BARI", code: "BARI", ...i("Bari Region") }, stock_lines: 3, quantity: 352, below_reorder: 2, assets: {} }, { category: S(y[1]), region: { id: "u-BARI", code: "BARI", ...i("Bari Region") }, stock_lines: 0, quantity: 0, below_reorder: 0, assets: { in_stock: 1, issued: 1, maintenance: 1 } }] };
  if (n === "/training/courses/") return b;
  if (n === "/training/records/") return c(A(O, e), e);
  if (t = n.match(/^\/training\/records\/([^/]+)\/$/)) return u(O, t[1]);
  if (n === "/training/summary/") return { rows: b.map((r) => ({ course: { id: r.id, code: r.code, ...i(r.name_en) }, region: { id: "u-BARI", code: "BARI", ...i("Bari Region") }, counts: { completed: 6, in_progress: 2, enrolled: 1 }, total: 9 })) };
  if (n === "/integrations/clients/") return c(re, e);
  if (/^\/integrations\/clients\/[^/]+\/calls\/$/.test(n)) return c([{ id: "ca-1", at: a(1), endpoint: "/api/v1/personnel/", status_code: 200, outcome: "success", ip_address: "203.0.113.5" }], e);
  if (n === "/analytics/") return { sections: ["personnel", "reports", "logistics", "training"] };
  if ((t = n.match(/^\/analytics\/([a-z]+)\/$/)) && N[t[1]]) return N[t[1]];
  throw z();
}
function ae(n, e, t) {
  let r;
  if (e === "/auth/login/") return x(true), R();
  if (e === "/auth/logout/") {
    x(false);
    return;
  }
  if (e === "/auth/me/") return R();
  if (r = e.match(/^\/ranks\/([^/]+)\/(approve|unapprove)\/$/)) {
    const s = u(m, r[1]);
    return s.approval_status = r[2] === "approve" ? "approved" : "draft", s.version++, s;
  }
  if ((r = e.match(/^\/ranks\/([^/]+)\/$/)) && n === "PATCH") {
    const s = u(m, r[1]);
    return Object.assign(s, t, { approval_status: "draft" }), s.version++, s;
  }
  if (e === "/ranks/") {
    const s = { id: `r-${m.length + 1}`, active: true, approval_status: "draft", approved_at: null, version: 1, ...t };
    return m.push(s), s;
  }
  if (e === "/personnel/") {
    const s = u(m, t.rank), o = u(p, t.org_unit), v = { id: `p-${d.length + 1}`, service_number: t.service_number || null, full_name: t.full_name, phone: t.phone ?? "", branch: T(o.branch ?? "b-army"), org_unit: f(o.code), rank: { id: s.id, code: s.code, name_en: s.name_en, name_so: s.name_so, approval_status: s.approval_status }, status: t.status ?? "active", version: 1 };
    return d.unshift(v), v;
  }
  if (r = e.match(/^\/personnel\/([^/]+)\/(transfer|change-rank|change-status)\/$/)) {
    const s = u(d, r[1]);
    if (r[2] === "transfer" && (s.org_unit = f(u(p, t.org_unit).code)), r[2] === "change-rank") {
      const o = u(m, t.rank);
      s.rank = { id: o.id, code: o.code, name_en: o.name_en, name_so: o.name_so, approval_status: o.approval_status };
    }
    return r[2] === "change-status" && (s.status = t.status), s.version++, s;
  }
  if ((r = e.match(/^\/personnel\/([^/]+)\/$/)) && n === "PATCH") {
    const s = u(d, r[1]);
    return Object.assign(s, t), s.version++, s;
  }
  return (r = e.match(/^\/notifications\/([^/]+)\/read\/$/)) ? (u(U, r[1]).read_at = a(0), {}) : (r = e.match(/^\/users\/([^/]+)\/(disable|enable)\/$/)) ? (u(h, r[1]).is_active = r[2] === "enable", {}) : /issue-reset-code/.test(e) ? { code: "DEMO-0000", valid_minutes: 15 } : e === "/personnel/import/commit/" ? { created: 0 } : {};
}
async function ue(n, e, t, r) {
  await new Promise((o) => setTimeout(o, 120));
  const s = e.endsWith("/") ? e : `${e}/`;
  return n === "GET" ? ie(s, t) : ae(n, s, r ?? {});
}
const ce = () => ({ batch_id: "demo", total: 0, valid: 0, can_commit: false, rows: [] });
export { ue as demoApi, ce as demoUpload };
