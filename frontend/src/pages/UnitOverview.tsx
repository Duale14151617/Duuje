import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Department, OrgOffice, Page, Person, UnitDepartmentRow, UnitProfile } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { DataTable, type Column } from "../components/DataTable";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { FilterBar } from "../components/FilterBar";
import { BarRow, Holder, StatTiles } from "../components/OrgBits";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, ErrorNotice, Field, Loading, Notice, PageHeader, TabPanel, Tabs } from "../components/ui";
import { statusTone } from "../components/status";
import { useI18n, type Key } from "../i18n";
import { OrgAnalyticsView, OrgChart } from "./OrgChart";
import { OrgTree } from "./OrgTree";

type Hub = "chart" | "tree" | "analytics" | "find";

/** Units and structure hub: expandable chart, organization analytics, and a finder for any unit. */
export function UnitsHome() {
  const { t } = useI18n();
  const { can } = useAuth();
  const nav = useNavigate();
  const [tab, setTab] = useState<Hub>("chart");
  const [id, setId] = useState("");
  const tabs: { id: Hub; label: string }[] = [
    { id: "chart", label: t("org2.tab.chart") },
    { id: "tree", label: t("org2.tab.tree") },
    ...(can("analytics.view") ? [{ id: "analytics" as const, label: t("org2.tab.analytics") }] : []),
    { id: "find", label: t("org2.tab.find") },
  ];
  return (
    <>
      <PageHeader title={t("uo.title")} subtitle={t("org2.subtitle")} actions={can("orgprofile.configure")
        ? <Link className="btn secondary" to="/structure?tab=settings">{t("org2.settings")}</Link> : undefined} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} label={t("uo.title")} controls idPrefix="orghub" />
      <TabPanel id="chart" active={tab === "chart"} idPrefix="orghub"><OrgChart /></TabPanel>
      <TabPanel id="tree" active={tab === "tree"} idPrefix="orghub"><OrgTree embedded /></TabPanel>
      <TabPanel id="analytics" active={tab === "analytics"} idPrefix="orghub"><OrgAnalyticsView /></TabPanel>
      <TabPanel id="find" active={tab === "find"} idPrefix="orghub">
        <div className="card">
          <UnitPicker label={t("uo.pick")} value={id} onChange={(v) => { setId(v); if (v) nav(`/units/${v}`); }} />
        </div>
      </TabPanel>
    </>
  );
}

type Tab = "overview" | "leadership" | "departments" | "personnel";
const ORDERINGS = ["name", "rank", "service_number", "status", "department", "unit"];

function OfficeRows({ offices }: { offices: OrgOffice[] }) {
  const { t, lang } = useI18n();
  if (offices.length === 0) return <p className="muted">{t("org2.vacant")}</p>;
  return (
    <table><tbody>{offices.map((o) => (
      <tr key={o.id}><td>{lang === "so" && o.type_so ? o.type_so : o.type_en}</td><td><Holder office={o} /></td><td className="muted">{o.effective_from}</td></tr>
    ))}</tbody></table>
  );
}

function Directory({ unitId }: { unitId: string }) {
  const { t, name } = useI18n();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dept, setDept] = useState("");
  const [direct, setDirect] = useState(false);
  const [ordering, setOrdering] = useState("name");
  const [desc, setDesc] = useState(false);
  const [page, setPage] = useState(1);
  const { can } = useAuth();
  const canBulk = can("personnel.manage");
  const [picked, setPicked] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [bulkError, setBulkError] = useState<unknown>(null);
  const departments = useFetch<Department[]>("/organization/departments/");
  const list = useFetch<Page<Person>>("/personnel/", { org_unit: unitId, q, status, department: dept || undefined, direct: direct ? 1 : undefined,
    ordering: `${desc ? "-" : ""}${ordering}`, page });
  const reset = () => { setQ(""); setStatus(""); setDept(""); setDirect(false); setPage(1); };
  const toggle = (id: string) => setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const pageIds = (list.data?.results ?? []).map((p) => p.id);
  async function applyBulk(department: string | null) {
    setBulkError(null); setBulkMsg(null);
    try {
      const r = await api<{ updated: number; skipped: number }>("/personnel/bulk-department/", { method: "POST", body: { ids: picked, department } });
      setBulkMsg(t("org2.bulkDone", { updated: r.updated, skipped: r.skipped }));
      setPicked([]); list.reload();
    } catch (err) { setBulkError(err); }
  }
  const columns: Column<Person>[] = [
    ...(canBulk ? [{ id: "pick", header: "", width: 44, locked: true,
      cell: (p: Person) => <input type="checkbox" aria-label={p.full_name} checked={picked.includes(p.id)} onChange={() => toggle(p.id)} /> }] : []),
    { id: "name", header: t("pers.fullName"), width: 220, locked: true, sort: (p) => p.full_name, cell: (p) => <Link to={`/personnel/${p.id}`}>{p.full_name}</Link> },
    { id: "service", header: t("pers.serviceNumber"), width: 130, sort: (p) => p.service_number, cell: (p) => p.service_number ?? "-" },
    { id: "rank", header: t("pers.rank"), width: 170, sort: (p) => p.rank.code, cell: (p) => `${p.rank.code} ${name(p.rank)}` },
    { id: "department", header: t("dept.department"), width: 170, sort: (p) => (p.department ? name(p.department) : null),
      cell: (p) => (p.department ? name(p.department) : <span className="muted">{t("dept.unassigned")}</span>) },
    { id: "unit", header: t("pers.unit"), width: 200, sort: (p) => name(p.org_unit), cell: (p) => <Link to={`/units/${p.org_unit.id}`}>{name(p.org_unit)}</Link> },
    { id: "status", header: t("pers.status"), width: 120, sort: (p) => p.status, cell: (p) => <Chip tone={statusTone(p.status)}>{t(`pstatus.${p.status}` as Key)}</Chip> },
  ];
  const filtered = !!(q || status || dept || direct);
  return (
    <>
      <FilterBar search={{ value: q, label: t("pers.search"), onChange: (v) => { setQ(v); setPage(1); } }}
        filters={[
          { id: "status", label: t("pers.status"), value: status, onChange: (v) => { setStatus(v); setPage(1); },
            options: ["active", "on_leave", "suspended", "jailed", "retired", "discharged", "died"].map((s) => ({ value: s, label: t(`pstatus.${s}` as Key) })) },
          { id: "department", label: t("dept.department"), value: dept, onChange: (v) => { setDept(v); setPage(1); },
            options: (departments.data ?? []).map((d) => ({ value: d.id, label: name(d) })) },
        ]}
        advancedExtra={<label className="check"><input type="checkbox" checked={direct} onChange={(e) => { setDirect(e.target.checked); setPage(1); }} /><span>{t("org2.directOnly")}</span></label>}
        custom={[{ id: "direct", label: t("org2.directOnly"), active: direct, onClear: () => setDirect(false) }]}
        onReset={reset} />
      <div className="row">
        <Field label={t("org2.orderBy")}>
          <select value={ordering} onChange={(e) => { setOrdering(e.target.value); setPage(1); }}>
            {ORDERINGS.map((o) => <option key={o} value={o}>{t(`org2.order.${o}` as Key)}</option>)}
          </select>
        </Field>
        <label className="check"><input type="checkbox" checked={desc} onChange={(e) => { setDesc(e.target.checked); setPage(1); }} /><span>{t("org2.descending")}</span></label>
      </div>
      <ErrorNotice error={list.error} />
      {canBulk && (
        <div className="card">
          <div className="row">
            <label className="check"><input type="checkbox" checked={pageIds.length > 0 && pageIds.every((i) => picked.includes(i))}
              onChange={(e) => setPicked(e.target.checked ? Array.from(new Set([...picked, ...pageIds])) : picked.filter((i) => !pageIds.includes(i)))} />
              <span>{t("org2.selectPage")}</span></label>
            <span className="muted">{t("org2.selected", { n: picked.length })}</span>
            <select value={target} aria-label={t("dept.department")} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{t("dept.unassigned")}</option>
              {(departments.data ?? []).map((d) => <option key={d.id} value={d.id}>{name(d)}</option>)}
            </select>
            <button type="button" disabled={picked.length === 0} onClick={() => void applyBulk(target || null)}>{t("org2.assignSelected")}</button>
          </div>
          <ErrorNotice error={bulkError} />
          {bulkMsg && <Notice>{bulkMsg}</Notice>}
        </div>
      )}
      <DataTable id="unit-directory" caption={t("org2.directory")} columns={columns} rows={list.data?.results} rowKey={(p) => p.id} loading={list.loading}
                 filtered={filtered} onReset={reset} empty={{ icon: "users", title: t("pers.noResults") }}
                 page={page} count={list.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}

function EstablishDepartment({ unitId, established, onDone }: { unitId: string; established: string[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const all = useFetch<Department[]>("/organization/departments/");
  const [pick, setPick] = useState("");
  const [error, setError] = useState<unknown>(null);
  const options = (all.data ?? []).filter((d) => !established.includes(d.id));
  if (options.length === 0) return null;
  async function add() {
    setError(null);
    try { await api("/organization/unit-departments/", { method: "POST", body: { unit: unitId, department: pick } }); setPick(""); onDone(); }
    catch (err) { setError(err); }
  }
  async function addAll() {
    setError(null);
    try {
      for (const d of options.filter((x) => x.active)) await api("/organization/unit-departments/", { method: "POST", body: { unit: unitId, department: d.id } });
      onDone();
    } catch (err) { setError(err); onDone(); }
  }
  return (
    <div className="card">
      <h3>{t("org2.establish")}</h3>
      <ErrorNotice error={error} />
      <div className="row">
        <select value={pick} aria-label={t("dept.department")} onChange={(e) => setPick(e.target.value)}>
          <option value="" />{options.map((d) => <option key={d.id} value={d.id}>{name(d)}</option>)}
        </select>
        <button type="button" disabled={!pick} onClick={() => void add()}>{t("org2.establish")}</button>
        <button type="button" className="secondary" onClick={() => void addAll()}>{t("org2.establishAll")}</button>
      </div>
    </div>
  );
}

function RetireDepartment({ unitId, deptId, onDone }: { unitId: string; deptId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [error, setError] = useState<unknown>(null);
  async function retire() {
    setError(null);
    try {
      const rows = await api<UnitDepartmentRow[]>("/organization/unit-departments/", { query: { unit: unitId } });
      const row = rows.find((r) => r.department.id === deptId);
      if (row) await api(`/organization/unit-departments/${row.id}/`, { method: "PATCH", body: { active: false, version: row.version } });
      onDone();
    } catch (err) { setError(err); }
  }
  return <><ErrorNotice error={error} /><button type="button" className="secondary sm" onClick={() => void retire()}>{t("org2.retire")}</button></>;
}

/** Profile of one unit: identification, leadership, departments, strength and distribution, and the personnel directory. */
export function UnitOverview() {
  const { id = "" } = useParams();
  const { t, name, lang } = useI18n();
  const [tab, setTab] = useState<Tab>("overview");
  const res = useFetch<UnitProfile>(id ? `/organization/units/${id}/profile/` : null);
  if (res.loading && !res.data) return <Loading />;
  if (res.error || !res.data) return <ErrorNotice error={res.error} />;
  const o = res.data;
  const title = name(o.unit);
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: t("org2.tab.overview") }, { id: "leadership", label: t("org2.tab.leadership") },
    { id: "departments", label: t("org2.tab.departments") },
    ...(o.can.name ? [{ id: "personnel" as const, label: t("org2.tab.personnel") }] : []),
  ];
  const lead = o.leadership;
  const pdf = () => ({
    title, subtitle: `${o.unit.code} · ${t("org2.total")}: ${o.stats.total} · ${t("org2.active")}: ${o.stats.active} · ${t("org2.inactive")}: ${o.stats.inactive}`,
    sections: [
      { heading: t("org2.tab.leadership"), columns: [{ header: "", width: 2 }, { header: "", width: 3 }],
        rows: [...lead.commander, ...lead.deputy, ...lead.administrative].map((a) => [lang === "so" && a.type_so ? a.type_so : a.type_en,
          a.holder ? `${name(a.holder.rank)} ${a.holder.full_name}` : "-"]) },
      { heading: t("uo.subunits"), columns: [{ header: "", width: 3 }, { header: t("org2.total"), width: 1, align: "right" as const }, { header: t("org2.active"), width: 1, align: "right" as const }],
        rows: o.children.map((c) => [`${name(c)} (${c.code})`, String(c.total), String(c.active)]) },
      { heading: t("org2.byRank"), columns: [{ header: "", width: 3 }, { header: "", width: 1, align: "right" as const }],
        rows: o.by_rank.map((r) => [`${r.rank.code} ${name(r.rank)}`, String(r.count)]) },
    ],
  });

  return (
    <>
      <p className="muted">
        {o.breadcrumb.map((b) => <span key={b.id}><Link to={`/units/${b.id}`}>{name(b)}</Link> › </span>)}
      </p>
      <PageHeader title={<>{title} {o.unit.formation_role && <Chip>{t(`org2.role.${o.unit.formation_role}` as Key)}</Chip>}</>}
        subtitle={<>{o.unit.code}{o.unit.parent ? <> · {t("org2.parent")}: <Link to={`/units/${o.unit.parent.id}`}>{name(o.unit.parent)}</Link></> : null}
          {!o.unit.is_active ? <> · <Chip tone="draft">{t("tree.inactive")}</Chip></> : null}{o.unit.restricted ? <> · <Chip tone="draft">{t("dept.restricted")}</Chip></> : null}</>}
        actions={<ExportPdfButton build={pdf} filename={`unit-${o.unit.code}`} />} />
      {!o.counts_complete && <Notice>{t("uo.noCounts")}</Notice>}
      <Tabs tabs={tabs} value={tab} onChange={setTab} label={title} controls idPrefix="unit" />

      <TabPanel id="overview" active={tab === "overview"} idPrefix="unit">
        <div className="card">
          <h2>{t("uo.strength")}</h2>
          <StatTiles b={o.stats} extra={[{ label: t("uo.direct"), value: o.stats.direct }]} />
          <p className="muted">{t("org2.definition")}</p>
          {Object.keys(o.stats.by_status).length > 0 && <p className="muted">{Object.entries(o.stats.by_status).map(([k, v]) => `${t(`pstatus.${k}` as Key)} ${v}`).join(" · ")}</p>}
        </div>
        <div className="card">
          <h2>{t("uo.subunits")}</h2>
          {o.children.length === 0 ? <p className="muted">{t("uo.noSubunits")}</p> : (
            <table>
              <thead><tr><th></th><th>{t("org2.total")}</th><th>{t("org2.active")}</th><th>{t("org2.inactive")}</th></tr></thead>
              <tbody>{o.children.map((c) => (
                <tr key={c.id}><td><Link to={`/units/${c.id}`}>{name(c)}</Link> <span className="muted">{c.code}</span>{c.formation_role ? <> <Chip>{t(`org2.role.${c.formation_role}` as Key)}</Chip></> : null}</td>
                  <td>{c.total}</td><td>{c.active}</td><td>{c.inactive}</td></tr>
              ))}</tbody>
            </table>
          )}
        </div>
        <div className="card">
          <h2>{t("org2.byRank")}</h2>
          {o.by_rank.length === 0 ? <p className="muted">{t("org2.noPeople")}</p> : o.by_rank.map((r) => (
            <BarRow key={r.rank.id} label={`${r.rank.code} ${name(r.rank)}`} value={r.count} max={Math.max(...o.by_rank.map((x) => x.count))} />
          ))}
        </div>
        <div className="card">
          <h2>{t("org2.byDepartment")}</h2>
          {o.departments.map((d) => <BarRow key={d.department.id} label={name(d.department)} value={d.staff} max={Math.max(1, ...o.departments.map((x) => x.staff), o.unassigned_department.total)}
                                            to={`/units/${o.unit.id}/departments/${d.department.id}`} />)}
          <BarRow label={t("dept.unassigned")} value={o.unassigned_department.total} max={Math.max(1, ...o.departments.map((x) => x.staff), o.unassigned_department.total)} />
        </div>
        {([["medical", o.medical], ["finance", o.finance]] as const).map(([k, f]) => f.department && (
          <div className="card" key={k}>
            <h2>{t(k === "medical" ? "org2.medicalStaff" : "org2.financeStaff")} ({f.count})</h2>
            <p className="muted">{t("org2.active")}: {f.active}</p>
            {f.roster_hidden ? <Notice>{t("dept.rosterHidden")}</Notice> : f.people && f.people.length > 0 ? (
              <table><tbody>{f.people.map((p) => (
                <tr key={p.id}><td>{name(p.rank)}</td><td><Link to={`/personnel/${p.id}`}>{p.full_name}</Link></td><td className="muted">{p.service_number ?? "-"}</td></tr>
              ))}</tbody></table>
            ) : null}
          </div>
        ))}
      </TabPanel>

      <TabPanel id="leadership" active={tab === "leadership"} idPrefix="unit">
        {([["commander", lead.commander], ["deputy", lead.deputy], ["administrative", lead.administrative]] as const).map(([k, rows]) => (
          <div className="card" key={k}><h2>{t(`org2.lead.${k}` as Key)}</h2><OfficeRows offices={rows} /></div>
        ))}
        {lead.other.length > 0 && <div className="card"><h2>{t("uo.commanders")}</h2><OfficeRows offices={lead.other} /></div>}
        {o.can.appoint && <p className="muted">{t("org2.appointHint")}</p>}
      </TabPanel>

      <TabPanel id="departments" active={tab === "departments"} idPrefix="unit">
        <div className="card">
          <h2>{t("org2.tab.departments")}</h2>
          {o.departments.length === 0 ? <p className="muted">{t("org2.noDepartments")}</p> : (
            <table>
              <thead><tr><th>{t("dept.department")}</th><th>{t("org2.head")}</th><th>{t("org2.deputy")}</th><th>{t("org2.staff")}</th><th /></tr></thead>
              <tbody>{o.departments.map((d) => (
                <tr key={d.department.id}>
                  <td><Link to={`/units/${o.unit.id}/departments/${d.department.id}`}>{name(d.department)}</Link>
                    {d.department.restricted ? <> <Chip tone="draft">{t("dept.restricted")}</Chip></> : null}
                    {!d.established ? <> <Chip tone="draft">{t("org2.notEstablished")}</Chip></> : null}</td>
                  <td><Holder office={d.head} /></td><td><Holder office={d.deputy} /></td><td>{d.staff}</td>
                  <td>{o.can.manage && d.established && <RetireDepartment unitId={o.unit.id} deptId={d.department.id} onDone={res.reload} />}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
        {o.can.manage && <EstablishDepartment unitId={o.unit.id} established={o.departments.filter((d) => d.established).map((d) => d.department.id)} onDone={res.reload} />}
      </TabPanel>

      <TabPanel id="personnel" active={tab === "personnel"} idPrefix="unit"><Directory unitId={o.unit.id} /></TabPanel>
    </>
  );
}

