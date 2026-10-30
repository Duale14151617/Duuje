import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, downloadCsv, fetchAll, photoUrl, upload } from "../api/client";
import type { HistoryEntry, ImportPreview, Page, Person, Rank, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Notice, PageHeader, TabPanel, Tabs, useErrorText } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { Icon, type IconName } from "../components/Icon";
import { AttendanceTab, HistoryTimeline, ServiceRecordTab, TrainingTab } from "../components/PersonnelTabs";
import { statusTone } from "../components/status";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { PersonnelProfile } from "../components/PersonnelProfile";
import { AppointmentsPanel } from "../components/AppointmentsPanel";
import { DeathPanel } from "../components/DeathPanel";
import { ReportingLine } from "../components/ReportingLine";
import { DisciplinaryPanel, DocumentsPanel } from "../components/PersonnelRecords";
import { UnitPicker } from "../components/UnitPicker";
import { useUnitTypes } from "../api/useUnitTypes";
import { useI18n, type Key } from "../i18n";
import { downloadText, inspectCsv, toCsv, type CsvInspection } from "../lib/csv";

const STATUSES = ["active", "on_leave", "suspended", "jailed", "died", "retired", "discharged"];
const SETTABLE = STATUSES.filter((s) => s !== "died");  // Died is only ever set by a confirmed death record (see DeathPanel)
const today = () => new Date().toISOString().slice(0, 10);

function useApprovedRanks() {
  const r = useFetch<Page<Rank>>("/ranks/", { approval_status: "approved", page_size: 100 });
  return r.data?.results ?? [];
}

export function PersonnelList() {
  const { t, name } = useI18n();
  const { me, can } = useAuth();
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [status, setStatus] = useState("");
  const [unit, setUnit] = useState("");
  const [unitLabel, setUnitLabel] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [noSup, setNoSup] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);
  const cat = useUnitTypes();
  const list = useFetch<Page<Person>>("/personnel/", { q, status, org_unit: unit, page, page_size: pageSize === 25 ? undefined : pageSize, no_supervisor: noSup ? 1 : undefined });
  const canExport = can("personnel.export") && !!me?.features.personnel_export;
  const filtered = !!(q || status || unit || noSup);
  const reset = () => { setQ(""); setStatus(""); setUnit(""); setUnitLabel(""); setNoSup(false); setPage(1); };

  async function exportCsv() {
    setExportError(null);
    try { await downloadCsv("/personnel/export/", { q, status, org_unit: unit }, "personnel.csv"); }
    catch (err) { setExportError(err); }
  }

  async function buildPdf() {
    const people = await fetchAll<Person>("/personnel/", { q, status, org_unit: unit });
    const filters = [q && `${t("pers.search")}: ${q}`, status && `${t("pers.status")}: ${t(`pstatus.${status}` as Key)}`, unit && `${t("pers.unit")}: ${unitLabel || unit}`]
      .filter(Boolean).join("  |  ");
    return {
      title: t("pers.title"), landscape: true,
      subtitle: [filters, t("pdf.rowsCount", { n: people.length })].filter(Boolean).join("  |  "),
      sections: [{
        columns: [
          { header: t("pers.serviceNumber"), width: 1.2 }, { header: t("nav.personnel"), width: 3 }, { header: t("pers.rank"), width: 2.2 },
          { header: t("pers.unit"), width: 3 }, { header: t("pers.status"), width: 1.2 }],
        rows: people.map((p) => [p.service_number ?? "", p.full_name, `${p.rank.code} ${name(p.rank)}`, name(p.org_unit), t(`pstatus.${p.status}` as Key)]),
      }],
    };
  }

  const unitType = (p: Person) => (p.org_unit.unit_type && cat.typeById.get(p.org_unit.unit_type) ? name(cat.typeById.get(p.org_unit.unit_type)!) : "");
  const columns: Column<Person>[] = [
    { id: "name", header: t("pers.fullName"), width: 240, locked: true, sort: (p) => p.full_name,
      cell: (p) => <Link to={`/personnel/${p.id}`}>{p.full_name}</Link> },
    { id: "service", header: t("pers.serviceNumber"), width: 140, sort: (p) => p.service_number, cell: (p) => p.service_number ?? "-" },
    { id: "rank", header: t("pers.rank"), width: 190, sort: (p) => p.rank.code, cell: (p) => `${p.rank.code} ${name(p.rank)}` },
    { id: "unit", header: t("pers.unit"), width: 230, sort: (p) => name(p.org_unit),
      cell: (p) => <>{name(p.org_unit)}{unitType(p) ? <span className="cell-sub">{unitType(p)}</span> : null}</> },
    { id: "branch", header: t("pers.branch"), width: 150, hidden: true, sort: (p) => name(p.branch), cell: (p) => name(p.branch) },
    { id: "phone", header: t("pers.phone"), width: 150, hidden: true, cell: (p) => p.phone || "-" },
    { id: "status", header: t("pers.status"), width: 130, sort: (p) => t(`pstatus.${p.status}` as Key), cell: (p) => <Chip tone={statusTone(p.status)}>{t(`pstatus.${p.status}` as Key)}</Chip> },
  ];

  return (
    <>
      <PageHeader title={t("pers.title")} actions={<>
        {can("personnel.manage") && <Link className="btn" to="/personnel/new"><Icon name="plus" size={16} /><span>{t("pers.add")}</span></Link>}
        {can("personnel.import") && <Link className="btn secondary" to="/personnel/import">{t("pers.import")}</Link>}
        {can("personnel.manage") && <Link className="btn secondary" to="/personnel/reporting-lines">{t("replines.title")}</Link>}
      </>} />
      <FilterBar
        search={{ value: q, label: t("pers.search"), onChange: (v) => { setQ(v); setPage(1); } }}
        filters={[{ id: "status", label: t("pers.status"), value: status, onChange: (v) => { setStatus(v); setPage(1); },
          options: STATUSES.map((s) => ({ value: s, label: t(`pstatus.${s}` as Key) })) }]}
        advancedExtra={<>
          <div className="fb-unit">
            <UnitPicker label={t("pers.unit")} value={unit} allowAll onChange={(id, u) => { setUnit(id); setUnitLabel(u ? name(u) : ""); setPage(1); }} />
          </div>
          {can("personnel.manage") && (
            <label className="check">
              <input type="checkbox" checked={noSup} onChange={(e) => { setNoSup(e.target.checked); setPage(1); }} />
              <span>{t("rline.onlyWithout")}</span>
            </label>
          )}
        </>}
        custom={[
          { id: "unit", label: `${t("pers.unit")}: ${unitLabel || unit}`, active: !!unit, onClear: () => { setUnit(""); setUnitLabel(""); setPage(1); } },
          { id: "nosup", label: t("rline.onlyWithout"), active: noSup, onClear: () => { setNoSup(false); setPage(1); } },
        ]}
        onReset={reset} />
      <ErrorNotice error={list.error ?? exportError} />
      <DataTable id="personnel" caption={t("pers.title")} columns={columns} rows={list.data?.results} rowKey={(p) => p.id}
                 loading={list.loading} filtered={filtered} onReset={reset}
                 empty={{ icon: "users", title: t("pers.noResults"), action: can("personnel.manage") ? <Link className="btn" to="/personnel/new">{t("pers.add")}</Link> : undefined }}
                 page={page} count={list.data?.count} pageSize={pageSize} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }}
                 actions={canExport ? <>
                   <button type="button" className="secondary sm" onClick={() => void exportCsv()}>{t("pers.export")}</button>
                   <ExportPdfButton filename="personnel.pdf" className="secondary sm" build={buildPdf} onError={setExportError} />
                 </> : undefined} />
    </>
  );
}

export function PersonnelForm() {
  const { t, name } = useI18n();
  const navigate = useNavigate();
  const ranks = useApprovedRanks();
  const [form, setForm] = useState({ full_name: "", service_number: "", phone: "", org_unit: "", rank: "", status: "active" });
  const [confirm, setConfirm] = useState(false);
  const [chosenUnit, setChosenUnit] = useState<Unit | null>(null);
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const unit = chosenUnit;
  const rankChoices = ranks.filter((r) => !!unit && r.branch === unit.branch);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const p = await api<Person>("/personnel/", { method: "POST", body: { ...form, confirm_duplicate: confirm } });
      navigate(`/personnel/${p.id}`);
    } catch (err) { setError(err); }
  }
  const dup = error instanceof ApiError && error.fieldCode === "possible_duplicate";

  return (
    <>
      <p><Link to="/personnel">{t("common.back")}</Link></p>
      <h1>{t("pers.add")}</h1>
      <ErrorNotice error={error} />
      <form className="card" onSubmit={(e) => void save(e)}>
        <Field label={t("pers.fullName")}><input value={form.full_name} onChange={set("full_name")} required /></Field>
        <Field label={t("pers.serviceNumber")}><input value={form.service_number} onChange={set("service_number")} /></Field>
        <Field label={t("pers.phone")}><input type="tel" value={form.phone} onChange={set("phone")} /></Field>
        <UnitPicker label={t("pers.unit")} value={form.org_unit} required
                    onChange={(id, u) => { setChosenUnit(u); setForm({ ...form, org_unit: id, rank: "" }); }} />
        <Field label={t("pers.rank")}>
          <select value={form.rank} onChange={set("rank")} required>
            <option value="" />
            {rankChoices.map((r) => <option key={r.id} value={r.id}>{r.code} {name(r)}</option>)}
          </select>
        </Field>
        {unit && rankChoices.length === 0 && <Notice>{t("pers.noApprovedRanks")}</Notice>}
        <Field label={t("pers.status")}>
          <select value={form.status} onChange={set("status")}>
            {SETTABLE.map((s) => <option key={s} value={s}>{t(`pstatus.${s}` as Key)}</option>)}
          </select>
        </Field>
        {dup && (
          <label className="row" style={{ marginBottom: ".75rem" }}>
            <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            <span>{t("pers.confirmDuplicate")}</span>
          </label>
        )}
        <button type="submit">{t("common.create")}</button>
      </form>
    </>
  );
}

type Mode = "edit" | "transfer" | "rank" | "status" | null;

function ChangeForm({ person, mode, onDone }: { person: Person; mode: Exclude<Mode, null>; onDone: () => void }) {
  const { t, name } = useI18n();
  const ranks = useApprovedRanks();
  const [fullName, setFullName] = useState(person.full_name);
  const [phone, setPhone] = useState(person.phone);
  const [serviceNumber, setServiceNumber] = useState(person.service_number ?? "");
  const [unit, setUnit] = useState("");
  const [rank, setRank] = useState("");
  const [status, setStatus] = useState("");
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const base = { version: person.version };
    const tracked = { ...base, effective_date: date, reason };
    try {
      if (mode === "edit") {
        await api(`/personnel/${person.id}/`, { method: "PATCH", body: {
          ...base, full_name: fullName, phone, service_number: serviceNumber, confirm_duplicate: confirm } });
      } else if (mode === "transfer") {
        await api(`/personnel/${person.id}/transfer/`, { method: "POST", body: { ...tracked, org_unit: unit } });
      } else if (mode === "rank") {
        await api(`/personnel/${person.id}/change-rank/`, { method: "POST", body: { ...tracked, rank } });
      } else {
        await api(`/personnel/${person.id}/change-status/`, { method: "POST", body: { ...tracked, status } });
      }
      onDone();
    } catch (err) { setError(err); }
  }
  const dup = error instanceof ApiError && error.fieldCode === "possible_duplicate";

  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <ErrorNotice error={error} />
      {mode === "edit" && (
        <>
          <Field label={t("pers.fullName")}><input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></Field>
          <Field label={t("pers.serviceNumber")}><input value={serviceNumber} onChange={(e) => setServiceNumber(e.target.value)} /></Field>
          <Field label={t("pers.phone")}><input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
          {dup && (
            <label className="row" style={{ marginBottom: ".75rem" }}>
              <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              <span>{t("pers.confirmDuplicateEdit")}</span>
            </label>
          )}
        </>
      )}
      {mode === "transfer" && (
        <UnitPicker label={t("pers.unit")} value={unit} required exclude={person.org_unit.id}
                    params={{ branch: person.branch.id }} onChange={(id) => setUnit(id)} />
      )}
      {mode === "rank" && (
        <Field label={t("pers.rank")}>
          <select value={rank} onChange={(e) => setRank(e.target.value)} required>
            <option value="" />
            {ranks.filter((r) => r.branch === person.branch.id && r.id !== person.rank.id)
              .map((r) => <option key={r.id} value={r.id}>{r.code} {name(r)}</option>)}
          </select>
        </Field>
      )}
      {mode === "status" && (
        <Field label={t("pers.status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)} required>
            <option value="" />
            {SETTABLE.filter((s) => s !== person.status).map((s) => <option key={s} value={s}>{t(`pstatus.${s}` as Key)}</option>)}
          </select>
        </Field>
      )}
      {mode !== "edit" && (
        <div className="grid">
          <Field label={t("pers.effectiveDate")}><input type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} required /></Field>
          <Field label={t("pers.reason")}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
        </div>
      )}
      <div className="row">
        <button type="submit">{t("common.save")}</button>
        <button type="button" className="secondary" onClick={onDone}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

type ProfileTab = "personal" | "service" | "assignments" | "attendance" | "training" | "admin";

export function PersonnelDetail() {
  const { id = "" } = useParams();
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const person = useFetch<Person>(`/personnel/${id}/`);
  const history = useFetch<HistoryEntry[]>(`/personnel/${id}/history/`);
  const [mode, setMode] = useState<Mode>(null);
  const [photoV, setPhotoV] = useState(0);
  const [photoBroken, setPhotoBroken] = useState(false);
  const p = person.data;
  const done = () => { setMode(null); person.reload(); history.reload(); };

  const tabs: { id: ProfileTab; label: string; icon: IconName }[] = [
    { id: "personal", label: t("pf.tab.personal"), icon: "user" },
    { id: "service", label: t("pf.tab.service"), icon: "award" },
    { id: "assignments", label: t("pf.tab.assignments"), icon: "briefcase" },
    ...(can("attendance.view") ? [{ id: "attendance" as const, label: t("pf.tab.attendance"), icon: "calendar" as const }] : []),
    ...(can("training.view") ? [{ id: "training" as const, label: t("pf.tab.training"), icon: "cap" as const }] : []),
    { id: "admin", label: t("pf.tab.admin"), icon: "clock" },
  ];
  const wanted = sp.get("tab");
  const tab: ProfileTab = tabs.find((x) => x.id === wanted)?.id ?? "personal";
  const setTab = (next: ProfileTab) => setSp(next === "personal" ? {} : { tab: next }, { replace: true });
  const photo = photoUrl(id, photoV);

  return (
    <>
      <p><Link to="/personnel">{t("common.back")}</Link></p>
      <ErrorNotice error={person.error} />
      {person.loading && !p ? <Loading /> : null}
      {p && (
        <section className="card pf-head">
          <div className="pf-photo">
            <img src={photoBroken || !photo ? "/avatar-default.png" : photo} alt="" width={112} height={140} onError={() => setPhotoBroken(true)} />
          </div>
          <div className="pf-id">
            <h1>{p.full_name}</h1>
            <div className="pf-badges">
              <Chip tone={statusTone(p.status)}>{t(`pstatus.${p.status}` as Key)}</Chip>
              <Chip>{p.rank.code} {name(p.rank)}</Chip>
            </div>
            <p className="pf-meta">
              <span>{t("pers.serviceNumber")}: <b>{p.service_number ?? "-"}</b></span>
              <span>{t("pers.unit")}: <b>{name(p.org_unit)}</b></span>
              <span>{t("pers.branch")}: <b>{name(p.branch)}</b></span>
              <span>{t("pers.phone")}: <b>{p.phone || "-"}</b></span>
            </p>
          </div>
          {can("personnel.manage") && mode === null && p.status !== "died" && (
            <div className="pf-actions">
              <button type="button" className="secondary sm" onClick={() => setMode("edit")}><Icon name="edit" size={16} /><span>{t("pers.editBasics")}</span></button>
              <button type="button" className="secondary sm" onClick={() => setMode("transfer")}>{t("pers.transfer")}</button>
              <button type="button" className="secondary sm" onClick={() => setMode("rank")}>{t("pers.changeRank")}</button>
              <button type="button" className="secondary sm" onClick={() => setMode("status")}>{t("pers.changeStatus")}</button>
            </div>
          )}
        </section>
      )}
      {p && mode && <ChangeForm person={p} mode={mode} onDone={done} />}
      {p && (
        <>
          <Tabs tabs={tabs} value={tab} onChange={setTab} label={t("pf.tabs")} controls idPrefix="pf" />
          <TabPanel id="personal" idPrefix="pf" active={tab === "personal"}>
            <section className="card">
              <h2>{t("pf.basic")}</h2>
              <dl className="kv">
                <div><dt>{t("pers.fullName")}</dt><dd>{p.full_name}</dd></div>
                <div><dt>{t("pers.serviceNumber")}</dt><dd>{p.service_number ?? "-"}</dd></div>
                <div><dt>{t("pers.phone")}</dt><dd>{p.phone || "-"}</dd></div>
                {p.account_username !== undefined && <div><dt>{t("rline.account")}</dt><dd>{p.account_username || t("rline.noAccount")}</dd></div>}
              </dl>
            </section>
            <PersonnelProfile personId={p.id} canManage={can("personnel.manage")} onPhotoChanged={() => { setPhotoBroken(false); setPhotoV((v) => v + 1); }} />
          </TabPanel>
          <TabPanel id="service" idPrefix="pf" active={tab === "service"}>
            <ErrorNotice error={history.error} />
            <ServiceRecordTab person={p} history={history.data ?? []} canManage={can("personnel.manage")} />
          </TabPanel>
          <TabPanel id="assignments" idPrefix="pf" active={tab === "assignments"}>
            <AppointmentsPanel person={p} />
            <ReportingLine person={p} canManage={can("personnel.manage") && p.status !== "died"} onChanged={done} />
          </TabPanel>
          <TabPanel id="attendance" idPrefix="pf" active={tab === "attendance"}><AttendanceTab person={p} /></TabPanel>
          <TabPanel id="training" idPrefix="pf" active={tab === "training"}><TrainingTab person={p} /></TabPanel>
          <TabPanel id="admin" idPrefix="pf" active={tab === "admin"}>
            <DeathPanel person={p} onChanged={done} />
            <section className="card">
              <h2>{t("pers.history")}</h2>
              <ErrorNotice error={history.error} />
              <HistoryTimeline entries={history.data ?? []} />
            </section>
            {can("disciplinary.view") && <DisciplinaryPanel personId={p.id} canManage={can("disciplinary.manage")} />}
            {can("documents.view") && <DocumentsPanel personId={p.id} canManage={can("documents.manage")} />}
          </TabPanel>
        </>
      )}
    </>
  );
}

const IMPORT_COLUMNS = ["service_number", "full_name", "phone", "unit_code", "rank_code", "status"];
const IMPORT_REQUIRED = ["full_name", "unit_code", "rank_code"];
const IMPORT_LIMITS = { columns: IMPORT_COLUMNS, required: IMPORT_REQUIRED, maxBytes: 1_000_000, maxRows: 1000 };

export function PersonnelImport() {
  const { t, tr } = useI18n();
  const errText = useErrorText();
  const [file, setFile] = useState<File | null>(null);
  const [local, setLocal] = useState<CsvInspection | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [created, setCreated] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);

  const problemText = (code: string) => tr(`err.${code}`) ?? errText(new ApiError(400, { code }));

  async function choose(f: File | null) {
    setFile(f); setPreview(null); setCreated(null); setError(null); setLocal(null);
    if (f) setLocal(await inspectCsv(f, IMPORT_LIMITS));
  }
  async function check() {
    if (!file || local?.problem) return;
    setBusy(true); setError(null); setCreated(null); setPreview(null);
    try { setPreview(await upload<ImportPreview>("/personnel/import/preview/", "file", file)); }
    catch (err) { setError(err); }
    finally { setBusy(false); }
  }
  async function commit() {
    if (!preview) return;
    setBusy(true); setError(null);
    try {
      const r = await api<{ created: number }>("/personnel/import/commit/", { method: "POST", body: { batch_id: preview.batch_id } });
      setCreated(r.created); setPreview(null); setFile(null); setLocal(null);
    } catch (err) { setError(err); }
    finally { setBusy(false); }
  }
  function again() { setCreated(null); setError(null); }
  function template() {
    downloadText("personnel-import-template.csv", toCsv([IMPORT_COLUMNS, ["", "Example Person", "", "UNIT-CODE", "RANK-CODE", "active"]]));
  }
  function problemList() {
    if (!preview) return;
    downloadText("personnel-import-problems.csv", toCsv([
      [t("imp.rowCol"), t("imp.reportCol")],
      ...preview.rows.filter((r) => r.errors.length > 0).map((r) => [String(r.row), r.errors.map(problemText).join(" ")]),
    ]));
  }

  const problems = preview?.rows.filter((r) => r.errors.length > 0) ?? [];
  const step = created !== null ? 3 : preview ? 2 : 1;
  const stepClass = (n: number) => (step === n ? "on" : step > n ? "done" : "");

  return (
    <>
      <p><Link to="/personnel">{t("common.back")}</Link></p>
      <h1>{t("imp.title")}</h1>
      <p>{t("imp.intro")}</p>
      <ol className="steps" aria-label={t("imp.title")}>
        <li className={stepClass(1)}>{t("imp.steps.choose")}</li>
        <li className={stepClass(2)}>{t("imp.steps.check")}</li>
        <li className={stepClass(3)}>{t("imp.steps.add")}</li>
      </ol>
      <ErrorNotice error={error} />
      {created !== null && (
        <section className="card">
          <Notice>{t("imp.created", { n: created })}</Notice>
          <div className="row">
            <Link className="btn" to="/personnel">{t("imp.viewPeople")}</Link>
            <button className="secondary" onClick={again}>{t("imp.another")}</button>
          </div>
        </section>
      )}
      {created === null && (
        <section className="card">
          <div className={`dropzone${over ? " over" : ""}`}
               onDragOver={(e) => { e.preventDefault(); setOver(true); }}
               onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); void choose(e.dataTransfer.files?.[0] ?? null); }}>
            <Field label={t("imp.drop")}>
              <input type="file" accept=".csv,text/csv" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
            </Field>
            <p className="muted">{t("imp.limits")}</p>
          </div>
          {file && local && !local.problem && <p><b>{t("imp.selected", { name: file.name, rows: local.rows })}</b></p>}
          {local?.problem && <Notice kind="error">{t("imp.localProblem")} {problemText(local.problem)}</Notice>}
          <div className="row">
            <button type="button" onClick={() => void check()} disabled={busy || !file || !!local?.problem}>{t("imp.preview")}</button>
            <button type="button" className="secondary" onClick={template}>{t("imp.template")}</button>
          </div>
        </section>
      )}
      {preview && (
        <section className="card">
          <p><b>{t("imp.summary", { valid: preview.valid, total: preview.total })}</b></p>
          {problems.length > 0 && <Notice kind="error">{t("imp.fixFile")}</Notice>}
          {preview.can_commit && <Notice>{t("imp.ready")}</Notice>}
          <ul className="list">
            {problems.map((r) => (
              <li key={r.row} className="item">
                <b>{t("imp.row", { row: r.row })}</b>
                <div className="muted">{r.errors.map(problemText).join(" ")}</div>
              </li>
            ))}
          </ul>
          <div className="row">
            {preview.can_commit && <button onClick={() => void commit()} disabled={busy}>{t("imp.commit")}</button>}
            {problems.length > 0 && <button className="secondary" onClick={problemList}>{t("imp.errorReport")}</button>}
          </div>
        </section>
      )}
    </>
  );
}
