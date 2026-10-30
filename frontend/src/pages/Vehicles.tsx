import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, uploadForm } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { Icon } from "../components/Icon";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface UnitB extends Named { id: string }
interface Person { id: string; full_name: string; service_number: string | null; rank: Named; org_unit?: UnitB }
interface Cat extends Named { id: string }
interface VehicleRow {
  id: string; vehicle_id: string; plate: string; plate_status: string; category: Cat; vehicle_type: string; make: string; model: string;
  year: number | null; org_unit: UnitB; driver: Person | null; custodian: Person | null; location: string; status: string; condition: string;
  next_due_date: string | null; maintenance_overdue: boolean; disposal_pending: boolean; version: number;
}
interface HistoryEvent { id: string; kind: string; before: Record<string, unknown>; after: Record<string, unknown>; reason: string; authority_ref: string; effective_date: string | null; actor: string; at: string }
interface VehicleDetailT extends VehicleRow {
  notes: string; acquired_on: string | null; acquisition_ref: string; decommissioned_at: string | null;
  disposal: { requested_by: string; reason: string; authority_ref: string } | null;
  capabilities: Record<"edit" | "transfer" | "dispose" | "approve" | "cost", boolean>; assignment_history: HistoryEvent[];
}
interface Maint { id: string; kind: string; state: string; performed_on: string; reported_issue: string; work_performed: string; workshop: string; next_due_date: string | null; reference: string; version: number; cost?: string | null; currency?: string }
interface Doc { id: string; category: string; title: string; size_bytes: number; uploaded_at: string }
interface Tally {
  total: number; by_category: (Named & { count: number })[]; by_status: Record<string, number>;
  without_driver: number; without_custodian: number; overdue_maintenance: number; unavailable: number;
}
interface Summary {
  unit: UnitB; total: number; direct: Tally; subordinate: Tally; combined: Tally; decommissioned: number;
  by_child_unit: { unit: UnitB; total: number; direct: number }[];
}

interface StatusT extends Named { id: string; available: boolean; is_system: boolean; active: boolean }

/** Statuses are configured on the server (HQ can add more), so labels and choices always come from it. */
function useStatuses() {
  const { name } = useI18n();
  const r = useFetch<{ results: StatusT[] }>("/vehicles/statuses/");
  const list = r.data?.results ?? [];
  return { list, reload: r.reload, label: (code: string) => { const x = list.find((y) => y.code === code); return x ? name(x) : code; } };
}
const CONDITIONS = ["good", "fair", "poor", "unserviceable", "unknown"];
const tone = (s: string) => (s === "operational" ? "approved" : s === "decommissioned" || s === "out_of_service" ? "bad" : "draft");

/** Military vehicle registry: Organization → Brigade → Battalion → vehicles → vehicle details. All figures come from the server. */
export function Vehicles() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const unit = sp.get("unit") ?? "";
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [noDriver, setNoDriver] = useState(false);
  const [withDecom, setWithDecom] = useState(false);
  const [direct, setDirect] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [registering, setRegistering] = useState(false);
  const cats = useFetch<{ results: Cat[] }>("/vehicles/categories/");
  const st = useStatuses();
  const summary = useFetch<Summary>(unit ? "/vehicles/summary/" : null, { org_unit: unit });
  const list = useFetch<Page<VehicleRow>>("/vehicles/", {
    q, status, category, org_unit: unit || undefined, direct: direct ? 1 : undefined, page, page_size: pageSize === 25 ? undefined : pageSize,
    overdue: overdue ? 1 : undefined, no_driver: noDriver ? 1 : undefined, include_decommissioned: withDecom ? 1 : undefined,
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1); };
  const filtered = !!(q || status || category || unit || overdue || noDriver || withDecom || direct);
  const resetAll = () => { setQ(""); setStatus(""); setCategory(""); setOverdue(false); setNoDriver(false); setWithDecom(false); setDirect(false); setSp({}); setPage(1); };
  const flags: [string, boolean, (v: boolean) => void][] = [["veh.onlyOverdue", overdue, setOverdue], ["veh.onlyNoDriver", noDriver, setNoDriver], ["veh.showDecommissioned", withDecom, setWithDecom]];

  const columns: Column<VehicleRow>[] = [
    { id: "id", header: t("veh.col.vehicle"), width: 140, locked: true, sort: (v) => v.vehicle_id, cell: (v) => <Link to={`/vehicles/${v.id}`}>{v.vehicle_id}</Link> },
    { id: "category", header: t("veh.category"), width: 150, sort: (v) => name(v.category), cell: (v) => name(v.category) },
    { id: "plate", header: t("veh.col.plate"), width: 130, sort: (v) => v.plate, cell: (v) => v.plate || t(v.plate_status === "none" ? "veh.plateNone" : "veh.plateUnknown") },
    { id: "status", header: t("veh.status"), width: 170, sort: (v) => st.label(v.status),
      cell: (v) => <><Chip tone={tone(v.status)}>{st.label(v.status)}</Chip>{v.maintenance_overdue && <> <Chip tone="bad">{t("veh.overdue")}</Chip></>}</> },
    { id: "unit", header: t("veh.unit"), width: 200, sort: (v) => name(v.org_unit), cell: (v) => name(v.org_unit) },
    { id: "driver", header: t("veh.col.driver"), width: 220, sort: (v) => v.driver?.full_name ?? null,
      cell: (v) => (v.driver ? `${v.driver.rank.code} ${v.driver.full_name} (${v.driver.service_number ?? "—"})` : <span className="muted">{t("veh.noDriver")}</span>) },
    { id: "location", header: t("veh.col.location"), width: 160, sort: (v) => v.location, cell: (v) => v.location || "—" },
    { id: "model", header: t("veh.col.model"), width: 170, hidden: true, sort: (v) => `${v.make} ${v.model}`, cell: (v) => `${v.make} ${v.model}`.trim() || "—" },
    { id: "year", header: t("veh.col.year"), width: 90, hidden: true, align: "right", sort: (v) => v.year, cell: (v) => v.year ?? "—" },
    { id: "condition", header: t("veh.col.condition"), width: 130, hidden: true, sort: (v) => v.condition, cell: (v) => v.condition },
    { id: "due", header: t("veh.col.nextDue"), width: 130, hidden: true, sort: (v) => v.next_due_date, cell: (v) => v.next_due_date ?? "—" },
  ];

  return (
    <>
      <PageHeader title={t("veh.title")} actions={can("vehicles.create") && !registering ? <button type="button" onClick={() => setRegistering(true)}><Icon name="plus" size={16} /><span>{t("veh.register")}</span></button> : undefined} />
      <ErrorNotice error={list.error ?? summary.error} />
      <FilterBar
        search={{ value: q, label: t("veh.search"), onChange: reset(setQ) }}
        filters={[
          { id: "category", label: t("veh.category"), value: category, onChange: reset(setCategory), options: (cats.data?.results ?? []).map((c) => ({ value: c.code, label: name(c) })) },
          { id: "status", label: t("veh.status"), value: status, onChange: reset(setStatus), options: st.list.map((x) => ({ value: x.code, label: name(x) })) },
        ]}
        advancedExtra={<>
          <div className="fb-unit">
            <UnitPicker label={t("veh.unit")} value={unit} allowAll params={{ placeable: undefined }}
                        onChange={(id) => { setSp(id ? { unit: id } : {}); setPage(1); }} />
          </div>
          {flags.map(([k, v, set]) => (
            <label className="check" key={k}><input type="checkbox" checked={v} onChange={(e) => reset(set)(e.target.checked)} /><span>{t(k as Key)}</span></label>
          ))}
          {unit && <label className="check"><input type="checkbox" checked={direct} onChange={(e) => reset(setDirect)(e.target.checked)} /><span>{t("veh.direct")}</span></label>}
        </>}
        custom={[
          { id: "unit", label: `${t("veh.unit")}: ${summary.data ? name(summary.data.unit) : unit}`, active: !!unit, onClear: () => { setSp({}); setPage(1); } },
          ...flags.map(([k, v, set]) => ({ id: k, label: t(k as Key), active: v, onClear: () => reset(set)(false) })),
          { id: "direct", label: t("veh.direct"), active: direct && !!unit, onClear: () => reset(setDirect)(false) },
        ]}
        onReset={resetAll} />
      {can("vehicles.configure") && <CategoryManager cats={cats.data?.results ?? []} onDone={cats.reload} />}
      {registering && <RegisterForm unit={unit} cats={cats.data?.results ?? []} onDone={() => { setRegistering(false); list.reload(); summary.reload(); }} onCancel={() => setRegistering(false)} />}
      {can("vehicles.configure") && <StatusManager list={st.list} onDone={st.reload} />}
      {summary.data && <SummaryCards s={summary.data} onOpen={(id) => { setSp({ unit: id }); setPage(1); }} />}
      <DataTable id="vehicles" caption={t("veh.title")} columns={columns} rows={list.data?.results} rowKey={(v) => v.id}
                 loading={list.loading} filtered={filtered} onReset={resetAll} empty={{ icon: "truck", title: t("veh.none") }}
                 page={page} count={list.data?.count} pageSize={pageSize} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} />
    </>
  );
}

function TallyCard({ title, s }: { title: string; s: Tally }) {
  const { t, name } = useI18n();
  const st = useStatuses();
  return (
    <section className="card">
      <h3>{title}</h3>
      <div className="stat"><span>{t("veh.total")}</span><b>{s.total}</b></div>
      {s.by_category.map((c) => <div className="stat" key={c.code}><span>{name(c)}</span><b>{c.count}</b></div>)}
      {Object.entries(s.by_status).map(([k, n]) => <div className="stat" key={k}><span>{st.label(k)}</span><b>{n}</b></div>)}
      <div className="stat"><span>{t("veh.noDriver")}</span><b>{s.without_driver}</b></div>
      <div className="stat"><span>{t("veh.noCustodian")}</span><b>{s.without_custodian}</b></div>
      <div className="stat"><span>{t("veh.overdue")}</span><b>{s.overdue_maintenance}</b></div>
      <div className="stat"><span>{t("veh.unavailable")}</span><b>{s.unavailable}</b></div>
    </section>
  );
}

function SummaryCards({ s, onOpen }: { s: Summary; onOpen: (id: string) => void }) {
  const { t, name } = useI18n();
  return (
    <>
      <h2>{name(s.unit)}</h2>
      <TallyCard title={t("veh.direct")} s={s.direct} />
      <TallyCard title={t("veh.subordinate")} s={s.subordinate} />
      <TallyCard title={t("veh.combined")} s={s.combined} />
      {s.by_child_unit.length > 0 && (
        <section className="card">
          <h3>{t("veh.childUnits")}</h3>
          <ul className="list">
            {s.by_child_unit.map((c) => (
              <li key={c.unit.id} className="item">
                <button type="button" className="secondary" onClick={() => onOpen(c.unit.id)}>{name(c.unit)} · {c.total}</button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function RegisterForm({ unit, cats, onDone, onCancel }: { unit: string; cats: Cat[]; onDone: () => void; onCancel: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({ category: "", org_unit: unit, plate: "", plate_status: "registered", vehicle_type: "", make: "", model: "", year: "", location: "", condition: "unknown" });
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api("/vehicles/", { method: "POST", body: { ...f, year: f.year ? Number(f.year) : null } }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <ErrorNotice error={error} />
      <Field label={t("veh.category")}>
        <select value={f.category} required onChange={set("category")}><option value="" />{cats.map((c) => <option key={c.id} value={c.code}>{name(c)}</option>)}</select>
      </Field>
      <UnitPicker label={t("veh.unit")} value={f.org_unit} required onChange={(id) => setF({ ...f, org_unit: id })} />
      <Field label={t("veh.plateStatus")}>
        <select value={f.plate_status} onChange={set("plate_status")}>
          <option value="registered">{t("veh.plateRegistered")}</option><option value="none">{t("veh.plateNone")}</option><option value="unknown">{t("veh.plateUnknown")}</option>
        </select>
      </Field>
      {f.plate_status === "registered" && <Field label={t("veh.plate")}><input value={f.plate} required maxLength={32} onChange={set("plate")} /></Field>}
      <Field label={t("veh.type")}><input value={f.vehicle_type} maxLength={60} onChange={set("vehicle_type")} /></Field>
      <Field label={t("veh.make")}><input value={f.make} maxLength={60} onChange={set("make")} /></Field>
      <Field label={t("veh.model")}><input value={f.model} maxLength={60} onChange={set("model")} /></Field>
      <Field label={t("veh.year")}><input value={f.year} inputMode="numeric" pattern="[0-9]{4}" maxLength={4} onChange={set("year")} /></Field>
      <Field label={t("veh.location")}><input value={f.location} maxLength={200} onChange={set("location")} /></Field>
      <Field label={t("veh.condition")}><select value={f.condition} onChange={set("condition")}>{CONDITIONS.map((c) => <option key={c} value={c}>{t(`vcond.${c}` as Key)}</option>)}</select></Field>
      <div className="row"><button type="submit">{t("veh.register")}</button><button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button></div>
    </form>
  );
}

type Mode = "status" | "driver" | "custodian" | "location" | "transfer" | "maintenance" | "propose" | "approve" | "reject" | null;

export function VehicleDetail() {
  const { t, name } = useI18n();
  const { id = "" } = useParams();
  const st = useStatuses();
  const v = useFetch<VehicleDetailT>(`/vehicles/${id}/`);
  const history = useFetch<{ results: HistoryEvent[] }>(`/vehicles/${id}/history/`);
  const maint = useFetch<{ results: Maint[]; cost_visible: boolean }>(`/vehicles/${id}/maintenance/`);
  const docs = useFetch<{ results: Doc[] }>(`/vehicles/${id}/documents/`);
  const [mode, setMode] = useState<Mode>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const people = useFetch<{ results: Person[] }>(mode === "driver" || mode === "custodian" ? "/vehicles/people/" : null, { q });
  if (!v.data) return <>{v.error ? <ErrorNotice error={v.error} /> : <Loading />}</>;
  const d = v.data;
  const cap = d.capabilities;
  const closed = d.status === "decommissioned";
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const reloadAll = () => { v.reload(); history.reload(); maint.reload(); };

  async function run(path: string, body: Record<string, unknown>) {
    setBusy(true); setError(null);
    try { await api(`/vehicles/${id}/${path}/`, { method: "POST", body: { version: d.version, ...body } }); setMode(null); setF({}); setQ(""); reloadAll(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const base = { reason: f.reason ?? "", authority_ref: f.authority ?? "" };
    if (mode === "status") void run("status", { status: f.status, condition: f.condition || undefined, ...base });
    else if (mode === "driver") void run("driver", { driver: f.driver || null, ...base });
    else if (mode === "custodian") void run("custodian", { custodian: f.custodian || null, ...base });
    else if (mode === "location") void run("location", { location: f.location, reason: base.reason });
    else if (mode === "transfer") void run("transfer", { org_unit: f.org_unit, effective_date: f.date || undefined, ...base });
    else if (mode === "propose") void run("disposal/propose", base);
    else if (mode === "approve") void run("disposal/approve", base);
    else if (mode === "reject") void run("disposal/reject", base);
    else if (mode === "maintenance") void run("maintenance/add", { kind: f.kind || "service", state: f.state || "open", performed_on: f.date, reported_issue: f.issue, work_performed: f.work, workshop: f.workshop, next_due_date: f.due || undefined, cost: f.cost || undefined, currency: f.currency || undefined, reference: f.authority });
  };
  const open = (m: Mode, init: Record<string, string> = {}) => { setMode(m); setF(init); setError(null); };
  const person = (p: Person | null) => (p ? `${p.rank.code} ${p.full_name} (${p.service_number ?? "—"})` : "—");

  return (
    <>
      <p><Link to={`/vehicles?unit=${d.org_unit.id}`}>← {t("veh.back")}</Link></p>
      <h1>{d.vehicle_id}</h1>
      {closed && <Notice>{t("veh.decommissioned")}</Notice>}
      {d.disposal && <Notice>{t("veh.disposalPending")}: {d.disposal.reason} ({d.disposal.authority_ref})</Notice>}
      <section className="card">
        <div className="stat"><span>{t("veh.plate")}</span><b>{d.plate || t(d.plate_status === "none" ? "veh.plateNone" : "veh.plateUnknown")}</b></div>
        <div className="stat"><span>{t("veh.category")}</span><b>{name(d.category)}</b></div>
        <div className="stat"><span>{t("veh.make")} / {t("veh.model")}</span><b>{[d.make, d.model, d.year].filter(Boolean).join(" ") || "—"}</b></div>
        <div className="stat"><span>{t("veh.unit")}</span><b>{name(d.org_unit)}</b></div>
        <div className="stat"><span>{t("veh.driver")}</span><b>{person(d.driver)}</b></div>
        <div className="stat"><span>{t("veh.custodian")}</span><b>{person(d.custodian)}</b></div>
        <div className="stat"><span>{t("veh.location")}</span><b>{d.location || "—"}</b></div>
        <div className="row"><Chip tone={tone(d.status)}>{st.label(d.status)}</Chip><Chip>{t(`vcond.${d.condition}` as Key)}</Chip>{d.maintenance_overdue && <Chip tone="bad">{t("veh.overdue")}</Chip>}</div>
        {d.notes && <p className="muted">{d.notes}</p>}
      </section>
      {!closed && mode === null && (
        <div className="row">
          {cap.edit && <button type="button" onClick={() => open("status", { status: d.status })}>{t("veh.changeStatus")}</button>}
          {cap.edit && <button type="button" className="secondary" onClick={() => open("driver")}>{t("veh.assignDriver")}</button>}
          {cap.edit && <button type="button" className="secondary" onClick={() => open("custodian")}>{t("veh.assignCustodian")}</button>}
          {cap.edit && <button type="button" className="secondary" onClick={() => open("location", { location: d.location })}>{t("veh.updateLocation")}</button>}
          {cap.edit && <button type="button" className="secondary" onClick={() => open("maintenance", { kind: "service", state: "open" })}>{t("veh.addMaintenance")}</button>}
          {cap.transfer && <button type="button" className="secondary" onClick={() => open("transfer")}>{t("veh.transfer")}</button>}
          {cap.dispose && !d.disposal && <button type="button" className="secondary" onClick={() => open("propose")}>{t("veh.proposeDisposal")}</button>}
          {cap.approve && d.disposal && <button type="button" onClick={() => open("approve")}>{t("veh.approveDisposal")}</button>}
          {cap.approve && d.disposal && <button type="button" className="secondary" onClick={() => open("reject")}>{t("veh.rejectDisposal")}</button>}
        </div>
      )}
      {mode && (
        <form className="card" onSubmit={submit}>
          <ErrorNotice error={error} />
          {mode === "status" && (
            <>
              <Field label={t("veh.status")}><select value={f.status ?? ""} onChange={set("status")}>{st.list.filter((x) => x.code !== "decommissioned").map((x) => <option key={x.code} value={x.code}>{name(x)}</option>)}</select></Field>
              <Field label={t("veh.condition")}><select value={f.condition ?? ""} onChange={set("condition")}><option value="" />{CONDITIONS.map((c) => <option key={c} value={c}>{t(`vcond.${c}` as Key)}</option>)}</select></Field>
            </>
          )}
          {mode === "driver" && (
            <>
              <input type="search" value={q} maxLength={60} placeholder={t("veh.findPerson")} aria-label={t("veh.findPerson")} onChange={(e) => setQ(e.target.value)} />
              <Field label={t("veh.driver")}>
                <select value={f.driver ?? ""} onChange={set("driver")}><option value="">{t("veh.noDriver")}</option>{(people.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{person(p)}</option>)}</select>
              </Field>
            </>
          )}
          {mode === "custodian" && (
            <>
              <input type="search" value={q} maxLength={60} placeholder={t("veh.findPerson")} aria-label={t("veh.findPerson")} onChange={(e) => setQ(e.target.value)} />
              <Field label={t("veh.custodian")}>
                <select value={f.custodian ?? ""} onChange={set("custodian")}><option value="">{t("veh.noCustodian2")}</option>{(people.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{person(p)}</option>)}</select>
              </Field>
            </>
          )}
          {mode === "location" && <Field label={t("veh.location")}><input value={f.location ?? ""} required maxLength={200} onChange={set("location")} /></Field>}
          {mode === "transfer" && (
            <>
              <UnitPicker label={t("veh.unit")} value={f.org_unit ?? ""} required exclude={d.org_unit.id} onChange={(uid) => setF({ ...f, org_unit: uid })} />
              <Field label={t("veh.effectiveDate")}><input type="date" value={f.date ?? ""} onChange={set("date")} /></Field>
            </>
          )}
          {mode === "maintenance" && (
            <>
              <Field label={t("veh.kind")}><select value={f.kind ?? "service"} onChange={set("kind")}>{["service", "repair", "inspection"].map((k) => <option key={k} value={k}>{t(`vkind.${k}` as Key)}</option>)}</select></Field>
              <Field label={t("veh.performedOn")}><input type="date" required value={f.date ?? ""} onChange={set("date")} /></Field>
              <Field label={t("veh.issue")}><input value={f.issue ?? ""} maxLength={500} onChange={set("issue")} /></Field>
              <Field label={t("veh.work")}><input value={f.work ?? ""} maxLength={1000} onChange={set("work")} /></Field>
              <Field label={t("veh.workshop")}><input value={f.workshop ?? ""} maxLength={150} onChange={set("workshop")} /></Field>
              <Field label={t("veh.nextDue")}><input type="date" value={f.due ?? ""} onChange={set("due")} /></Field>
              {cap.cost && <Field label={t("veh.cost")}><input inputMode="decimal" value={f.cost ?? ""} onChange={set("cost")} /></Field>}
            </>
          )}
          {mode !== "maintenance" && mode !== "location" && <Field label={t("veh.authority")}><input value={f.authority ?? ""} required={["transfer", "propose"].includes(mode)} maxLength={150} onChange={set("authority")} /></Field>}
          {mode !== "maintenance" && <Field label={t("veh.reason")}><input value={f.reason ?? ""} required={["status", "propose", "reject"].includes(mode)} maxLength={300} onChange={set("reason")} /></Field>}
          <div className="row"><button type="submit" disabled={busy}>{t("veh.apply")}</button><button type="button" className="secondary" onClick={() => setMode(null)}>{t("common.cancel")}</button></div>
        </form>
      )}
      <h2>{t("veh.assignmentHistory")}</h2>
      <ul className="list">
        {d.assignment_history.map((e) => <li key={e.id} className="item"><b>{t(`vevent.${e.kind}` as Key)}</b><p className="muted">{(e.effective_date ?? e.at).slice(0, 10)} · {e.actor}{e.authority_ref ? ` · ${e.authority_ref}` : ""}</p></li>)}
      </ul>
      <h2>{t("veh.maintenance")}</h2>
      {(maint.data?.results ?? []).length === 0 && <p className="muted">{t("veh.none")}</p>}
      <ul className="list">
        {(maint.data?.results ?? []).map((m) => (
          <li key={m.id} className="item">
            <b>{t(`vkind.${m.kind}` as Key)}</b> · {m.performed_on} · <Chip tone={m.state === "completed" ? "approved" : "draft"}>{m.state}</Chip>
            <p className="muted">{m.reported_issue || "—"} → {m.work_performed || "—"}{m.workshop ? ` · ${m.workshop}` : ""}{m.next_due_date ? ` · ${t("veh.nextDue")}: ${m.next_due_date}` : ""}{m.cost ? ` · ${m.cost} ${m.currency ?? ""}` : ""}</p>
            {m.state === "open" && cap.edit && !closed && (
              <button type="button" className="secondary" disabled={busy}
                      onClick={() => { const work = window.prompt(t("veh.work")); if (work) { setBusy(true); void api(`/vehicles/${id}/maintenance/${m.id}/complete/`, { method: "POST", body: { version: m.version, work_performed: work } }).then(reloadAll).catch(setError).finally(() => setBusy(false)); } }}>
                {t("veh.complete")}
              </button>
            )}
          </li>
        ))}
      </ul>
      <h2>{t("veh.documents")}</h2>
      {(docs.data?.results ?? []).length === 0 && <p className="muted">{t("veh.none")}</p>}
      <ul className="list">
        {(docs.data?.results ?? []).map((x) => (
          <li key={x.id} className="item">
            <a href={`/api/v1/vehicles/${id}/documents/${x.id}/download/`}>{t("veh.download")}: {x.title}</a> <span className="muted">({t(`vdoc.${x.category}` as Key)})</span>
            {cap.edit && !closed && (
              <button type="button" className="secondary" disabled={busy} onClick={() => {
                const reason = window.prompt(t("veh.withdrawReason"));
                if (reason) { setBusy(true); void api(`/vehicles/${id}/documents/${x.id}/withdraw/`, { method: "POST", body: { reason } }).then(() => docs.reload()).catch(setError).finally(() => setBusy(false)); }
              }}>{t("veh.withdraw")}</button>
            )}
          </li>
        ))}
      </ul>
      {cap.edit && !closed && <DocumentUpload id={id} onDone={() => { docs.reload(); history.reload(); }} />}
      <h2>{t("veh.history")}</h2>
      <ul className="list">
        {(history.data?.results ?? []).map((e) => <li key={e.id} className="item"><b>{t(`vevent.${e.kind}` as Key)}</b><p className="muted">{e.at.slice(0, 10)} · {e.actor}{e.reason ? ` · ${e.reason}` : ""}</p></li>)}
      </ul>
    </>
  );
}

function DocumentUpload({ id, onDone }: { id: string; onDone: () => void }) {
  const { t } = useI18n();
  const [category, setCategory] = useState("registration");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("category", category); form.append("title", title); form.append("file", file);
    try { await uploadForm(`/vehicles/${id}/documents/upload/`, form); setTitle(""); setFile(null); (e.target as HTMLFormElement).reset(); onDone(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("veh.uploadDocument")}</h3>
      <ErrorNotice error={error} />
      <Field label={t("veh.docCategory")}>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>{["registration", "service_report", "receipt", "handover", "inspection", "other"].map((c) => <option key={c} value={c}>{t(`vdoc.${c}` as Key)}</option>)}</select>
      </Field>
      <Field label={t("veh.docTitle")}><input value={title} required maxLength={150} onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label={t("veh.chooseFile")}><input type="file" required accept="application/pdf,image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      <div className="row"><button type="submit" disabled={busy || !file}>{t("veh.upload")}</button></div>
    </form>
  );
}

/** HQ-only: add vehicle categories. Categories can be switched off, never deleted, so old records keep their category. */
function CategoryManager({ cats, onDone }: { cats: Cat[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({ code: "", name_en: "", name_so: "" });
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api("/vehicles/categories/", { method: "POST", body: f }); setF({ code: "", name_en: "", name_so: "" }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("veh.manageCategories")}</h3>
      <ErrorNotice error={error} />
      <ul className="list">{cats.map((c) => <li key={c.id} className="item">{name(c)} <span className="muted">({c.code})</span></li>)}</ul>
      <Field label={t("veh.categoryCode")}><input value={f.code} required maxLength={40} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
      <Field label={t("veh.categoryName")}><input value={f.name_en} required maxLength={120} onChange={(e) => setF({ ...f, name_en: e.target.value })} /></Field>
      <Field label={t("veh.categoryNameSo")}><input value={f.name_so} maxLength={120} onChange={(e) => setF({ ...f, name_so: e.target.value })} /></Field>
      <div className="row"><button type="submit">{t("veh.newCategory")}</button></div>
    </form>
  );
}

/** HQ-only: add operational statuses and say whether a vehicle in them counts as available. The six built-in ones are fixed. */
function StatusManager({ list, onDone }: { list: StatusT[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({ code: "", name_en: "", name_so: "", available: false });
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api("/vehicles/statuses/", { method: "POST", body: f }); setF({ code: "", name_en: "", name_so: "", available: false }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("veh.manageStatuses")}</h3>
      <ErrorNotice error={error} />
      <ul className="list">{list.map((x) => <li key={x.id} className="item">{name(x)} <span className="muted">({x.code}){x.is_system ? "" : ` · ${x.available ? t("veh.statusAvailable") : t("veh.unavailable")}`}</span></li>)}</ul>
      <Field label={t("veh.categoryCode")}><input value={f.code} required maxLength={30} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
      <Field label={t("veh.categoryName")}><input value={f.name_en} required maxLength={120} onChange={(e) => setF({ ...f, name_en: e.target.value })} /></Field>
      <Field label={t("veh.categoryNameSo")}><input value={f.name_so} maxLength={120} onChange={(e) => setF({ ...f, name_so: e.target.value })} /></Field>
      <label className="row"><input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={f.available} onChange={(e) => setF({ ...f, available: e.target.checked })} /><span>{t("veh.statusAvailable")}</span></label>
      <div className="row"><button type="submit">{t("veh.newStatus")}</button></div>
    </form>
  );
}
