import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, downloadCsv, fetchAll, upload } from "../api/client";
import type { HistoryEntry, ImportPreview, Page, Person, Rank, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Pager, useErrorText } from "../components/ui";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { PersonnelProfile } from "../components/PersonnelProfile";
import { UnitPicker } from "../components/UnitPicker";
import { useUnitTypes } from "../api/useUnitTypes";
import { useI18n, type Key } from "../i18n";
import { downloadText, inspectCsv, toCsv, type CsvInspection } from "../lib/csv";

const STATUSES = ["active", "on_leave", "suspended", "retired", "discharged"];
const today = () => new Date().toISOString().slice(0, 10);

function useApprovedRanks() {
  const r = useFetch<Page<Rank>>("/ranks/", { approval_status: "approved", page_size: 100 });
  return r.data?.results ?? [];
}

export function PersonnelList() {
  const { t, name } = useI18n();
  const { me, can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [unit, setUnit] = useState("");
  const [unitLabel, setUnitLabel] = useState("");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState<unknown>(null);
  const cat = useUnitTypes();
  const list = useFetch<Page<Person>>("/personnel/", { q, status, org_unit: unit, page });
  const canExport = can("personnel.export") && !!me?.features.personnel_export;

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

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("pers.title")}</h1>
        <div className="row">
          {can("personnel.manage") && <Link className="btn" to="/personnel/new">{t("pers.add")}</Link>}
          {can("personnel.import") && <Link className="btn secondary" to="/personnel/import">{t("pers.import")}</Link>}
          {canExport && <button className="secondary" onClick={() => void exportCsv()}>{t("pers.export")}</button>}
          {canExport && <ExportPdfButton filename="personnel.pdf" build={buildPdf} onError={setExportError} />}
        </div>
      </div>
      <div className="grid">
        <Field label={t("pers.search")}>
          <input type="search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </Field>
        <Field label={t("pers.status")}>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`pstatus.${s}` as Key)}</option>)}
          </select>
        </Field>
        <UnitPicker label={t("pers.unit")} value={unit} allowAll onChange={(id, u) => { setUnit(id); setUnitLabel(u ? name(u) : ""); setPage(1); }} />
      </div>
      <ErrorNotice error={list.error ?? exportError} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("pers.noResults")}</p>}
      <ul className="list">
        {list.data?.results.map((p) => (
          <li key={p.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link to={`/personnel/${p.id}`}><h2>{p.full_name}</h2></Link>
              <Chip tone={p.status === "active" ? "approved" : "draft"}>{t(`pstatus.${p.status}` as Key)}</Chip>
            </div>
            <span className="muted">{p.rank.code} {name(p.rank)} · {name(p.org_unit)}{p.org_unit.unit_type && cat.typeById.get(p.org_unit.unit_type) ? ` (${name(cat.typeById.get(p.org_unit.unit_type)!)})` : ""}{p.service_number ? ` · ${p.service_number}` : ""}</span>
          </li>
        ))}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
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
            {STATUSES.map((s) => <option key={s} value={s}>{t(`pstatus.${s}` as Key)}</option>)}
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
            {STATUSES.filter((s) => s !== person.status).map((s) => <option key={s} value={s}>{t(`pstatus.${s}` as Key)}</option>)}
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

export function PersonnelDetail() {
  const { id = "" } = useParams();
  const { t, lang, name, tr } = useI18n();
  const { can } = useAuth();
  const person = useFetch<Person>(`/personnel/${id}/`);
  const history = useFetch<HistoryEntry[]>(`/personnel/${id}/history/`);
  const [mode, setMode] = useState<Mode>(null);
  const p = person.data;
  const done = () => { setMode(null); person.reload(); history.reload(); };
  const label = (h: HistoryEntry, value: string) => (h.field === "status" ? tr(`pstatus.${value}`) ?? value : value);

  return (
    <>
      <p><Link to="/personnel">{t("common.back")}</Link></p>
      <ErrorNotice error={person.error} />
      {person.loading && !p ? <Loading /> : null}
      {p && (
        <section className="card">
          <h1>{p.full_name}</h1>
          <div className="row"><Chip tone={p.status === "active" ? "approved" : "draft"}>{t(`pstatus.${p.status}` as Key)}</Chip></div>
          <div className="stat"><span>{t("pers.rank")}</span><b>{p.rank.code} {name(p.rank)}</b></div>
          <div className="stat"><span>{t("pers.unit")}</span><b>{name(p.org_unit)}</b></div>
          <div className="stat"><span>{t("pers.branch")}</span><b>{name(p.branch)}</b></div>
          <div className="stat"><span>{t("pers.serviceNumber")}</span><b>{p.service_number ?? "-"}</b></div>
          <div className="stat"><span>{t("pers.phone")}</span><b>{p.phone || "-"}</b></div>
          {can("personnel.manage") && mode === null && (
            <div className="row" style={{ marginTop: "1rem" }}>
              <button className="secondary" onClick={() => setMode("edit")}>{t("pers.editBasics")}</button>
              <button className="secondary" onClick={() => setMode("transfer")}>{t("pers.transfer")}</button>
              <button className="secondary" onClick={() => setMode("rank")}>{t("pers.changeRank")}</button>
              <button className="secondary" onClick={() => setMode("status")}>{t("pers.changeStatus")}</button>
            </div>
          )}
        </section>
      )}
      {p && mode && <ChangeForm person={p} mode={mode} onDone={done} />}
      {p && <PersonnelProfile personId={p.id} canManage={can("personnel.manage")} />}
      <h2>{t("pers.history")}</h2>
      <ErrorNotice error={history.error} />
      <ul className="list">
        {history.data?.map((h) => (
          <li key={h.id} className="item">
            <b>{t(`hist.${h.field}` as Key)}</b>{" "}
            {h.old_label ? `${label(h, h.old_label)} → ${label(h, h.new_label)}` : label(h, h.new_label)}
            <div className="muted">
              {h.effective_date} · {h.recorded_by_username || "-"} · {formatDate(h.recorded_at, lang)}
              {h.reason ? ` · ${h.reason}` : ""}
            </div>
          </li>
        ))}
      </ul>
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
