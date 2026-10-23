import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Course, Page, PersonBrief, TrainingRec, TrainingSummary } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Pager, Tabs } from "../components/ui";
import { useI18n, type Key } from "../i18n";

type Tab = "records" | "courses" | "summary";
const STATUSES = ["enrolled", "in_progress", "completed", "failed", "withdrawn"];
const tone = (s: string) => (s === "completed" ? "approved" : s === "failed" ? "bad" : "draft");
const today = () => new Date().toISOString().slice(0, 10);

function Enrol({ courses, onDone }: { courses: Course[]; onDone: (id: string) => void }) {
  const { t, name } = useI18n();
  const [q, setQ] = useState("");
  const people = useFetch<Page<PersonBrief>>(q.trim().length >= 2 ? "/training/people/" : null, { q });
  const [person, setPerson] = useState("");
  const [course, setCourse] = useState("");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api<TrainingRec>("/training/records/", { method: "POST", body: {
        personnel: person, course, start_date: start, end_date: end || null, notes } });
      onDone(r.id);
    } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("tr.enrol")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("tr.searchPerson")}><input value={q} onChange={(e) => { setQ(e.target.value); setPerson(""); }} /></Field>
      {people.data && (
        <Field label={t("tr.person")}>
          <select value={person} onChange={(e) => setPerson(e.target.value)} required>
            <option value="" />
            {people.data.results.map((p) => <option key={p.id} value={p.id}>{p.full_name} ({name(p.org_unit)})</option>)}
          </select>
        </Field>
      )}
      <Field label={t("tr.course")}>
        <select value={course} onChange={(e) => setCourse(e.target.value)} required>
          <option value="" />{courses.filter((c) => c.active).map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
        </select>
      </Field>
      <div className="grid">
        <Field label={t("tr.start")}><input type="date" value={start} onChange={(e) => setStart(e.target.value)} required /></Field>
        <Field label={t("tr.end")}><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
      <Field label={t("tr.notes")}><input value={notes} maxLength={300} onChange={(e) => setNotes(e.target.value)} /></Field>
      <button type="submit" disabled={!person}>{t("common.create")}</button>
    </form>
  );
}

function RecordsTab() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [course, setCourse] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const courses = useFetch<Course[]>("/training/courses/");
  const list = useFetch<Page<TrainingRec>>("/training/records/", { status, course, page });

  return (
    <>
      <div className="grid">
        <Field label={t("tr.status")}>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`tstatus.${s}` as Key)}</option>)}
          </select>
        </Field>
        <Field label={t("tr.course")}>
          <select value={course} onChange={(e) => { setCourse(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            {courses.data?.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
          </select>
        </Field>
      </div>
      {can("training.manage") && !adding && <button style={{ marginBottom: ".75rem" }} onClick={() => setAdding(true)}>{t("tr.enrol")}</button>}
      {adding && <Enrol courses={courses.data ?? []} onDone={(id) => navigate(`/training/records/${id}`)} />}
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("tr.noRecords")}</p>}
      <ul className="list">
        {list.data?.results.map((r) => (
          <li key={r.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link to={`/training/records/${r.id}`}><h2>{r.personnel.full_name}</h2></Link>
              <Chip tone={tone(r.status)}>{t(`tstatus.${r.status}` as Key)}</Chip>
            </div>
            <span className="muted">{name(r.course)} · {name(r.personnel.org_unit)} · {r.start_date}</span>
          </li>
        ))}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}

function CoursesTab() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const list = useFetch<Course[]>("/training/courses/");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ code: "", name_en: "", name_so: "", duration_days: "" });
  const [error, setError] = useState<unknown>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/training/courses/", { method: "POST", body: { ...f, duration_days: f.duration_days ? Number(f.duration_days) : null } });
      setAdding(false);
      list.reload();
    } catch (err) { setError(err); }
  }
  return (
    <>
      {can("training.configure") && !adding && <button style={{ marginBottom: ".75rem" }} onClick={() => setAdding(true)}>{t("tr.addCourse")}</button>}
      {adding && (
        <form className="card" onSubmit={(e) => void add(e)}>
          <ErrorNotice error={error} />
          <Field label={t("tr.code")}><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} required /></Field>
          <Field label={t("org.nameEn")}><input value={f.name_en} onChange={(e) => setF({ ...f, name_en: e.target.value })} required /></Field>
          <Field label={t("org.nameSo")}><input value={f.name_so} onChange={(e) => setF({ ...f, name_so: e.target.value })} /></Field>
          <Field label={t("tr.duration")}><input type="number" min={1} value={f.duration_days} onChange={(e) => setF({ ...f, duration_days: e.target.value })} /></Field>
          <div className="row">
            <button type="submit">{t("common.create")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      <ul className="list">
        {list.data?.map((c) => (
          <li key={c.id} className="item">
            <h2>{name(c)}</h2>
            <span className="muted">{c.code}{c.duration_days ? ` · ${c.duration_days} d` : ""}{!c.active ? ` · ${t("common.inactive")}` : ""}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function SummaryTab() {
  const { t, name } = useI18n();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const data = useFetch<TrainingSummary>("/training/summary/", { from, to });
  return (
    <>
      <div className="grid">
        <Field label={t("sum.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("sum.to")}><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <ErrorNotice error={data.error} />
      {data.loading && !data.data ? <Loading /> : null}
      {data.data && data.data.rows.length === 0 && <p>{t("sum.empty")}</p>}
      {data.data && data.data.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("tr.course")}</th><th>{t("sum.region")}</th>
              {STATUSES.map((s) => <th key={s}>{t(`tstatus.${s}` as Key)}</th>)}<th>{t("dash.total")}</th></tr></thead>
            <tbody>
              {data.data.rows.map((r) => (
                <tr key={`${r.course.id}-${r.region.id}`}>
                  <td>{name(r.course)}</td><td>{name(r.region)}</td>
                  {STATUSES.map((s) => <td key={s}>{r.counts[s] ?? 0}</td>)}<td>{r.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function TrainingHome() {
  const { t } = useI18n();
  const { can } = useAuth();
  const all: [Tab, Key, boolean][] = [
    ["records", "tr.tab.records", can("training.view")],
    ["courses", "tr.tab.courses", can("training.view") || can("training.configure")],
    ["summary", "tr.tab.summary", can("training.report")],
  ];
  const tabs = all.filter(([, , show]) => show).map(([id, label]) => ({ id, label: t(label) }));
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? "courses");
  return (
    <>
      <h1>{t("tr.title")}</h1>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "records" && <RecordsTab />}
      {tab === "courses" && <CoursesTab />}
      {tab === "summary" && <SummaryTab />}
    </>
  );
}

export function TrainingRecordDetail() {
  const { id = "" } = useParams();
  const { t, name } = useI18n();
  const { can } = useAuth();
  const rec = useFetch<TrainingRec>(`/training/records/${id}/`);
  const [completedOn, setCompletedOn] = useState(today());
  const [notes, setNotes] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const r = rec.data;
  const open = r && (r.status === "enrolled" || r.status === "in_progress");

  async function setStatus(status: string) {
    if (!r) return;
    setError(null);
    try {
      await api(`/training/records/${r.id}/status/`, { method: "POST", body: {
        status, version: r.version, completed_on: status === "completed" ? completedOn : undefined } });
      rec.reload();
    } catch (err) { setError(err); }
  }
  async function saveNotes(e: FormEvent) {
    e.preventDefault();
    if (!r || notes === null) return;
    setError(null);
    try { await api(`/training/records/${r.id}/`, { method: "PATCH", body: { notes, version: r.version } }); setNotes(null); rec.reload(); }
    catch (err) { setError(err); }
  }
  return (
    <>
      <p><Link to="/training">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? rec.error} />
      {rec.loading && !r ? <Loading /> : null}
      {r && (
        <section className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h1 style={{ margin: 0 }}>{r.personnel.full_name}</h1>
            <Chip tone={tone(r.status)}>{t(`tstatus.${r.status}` as Key)}</Chip>
          </div>
          <p className="muted">{name(r.personnel.org_unit)}</p>
          <div className="stat"><span>{t("tr.course")}</span><b>{name(r.course)}</b></div>
          <div className="stat"><span>{t("tr.start")}</span><b>{r.start_date}</b></div>
          <div className="stat"><span>{t("tr.end")}</span><b>{r.end_date ?? "-"}</b></div>
          <div className="stat"><span>{t("tr.completedOn")}</span><b>{r.completed_on ?? "-"}</b></div>
          <div className="stat"><span>{t("tr.notes")}</span><b>{r.notes || "-"}</b></div>
          {can("training.manage") && open && (
            <>
              <div className="row" style={{ marginTop: "1rem" }}>
                {r.status === "enrolled" && <button onClick={() => void setStatus("in_progress")}>{t("tr.markStart")}</button>}
                {r.status === "in_progress" && <button onClick={() => void setStatus("completed")}>{t("tr.markComplete")}</button>}
                {r.status === "in_progress" && <button className="danger" onClick={() => void setStatus("failed")}>{t("tr.markFail")}</button>}
                <button className="secondary" onClick={() => void setStatus("withdrawn")}>{t("tr.markWithdraw")}</button>
              </div>
              {r.status === "in_progress" && (
                <Field label={t("tr.completedOn")}><input type="date" max={today()} value={completedOn} onChange={(e) => setCompletedOn(e.target.value)} /></Field>
              )}
              <form onSubmit={(e) => void saveNotes(e)} style={{ marginTop: "1rem" }}>
                <Field label={t("tr.notes")}><input value={notes ?? r.notes} maxLength={300} onChange={(e) => setNotes(e.target.value)} /></Field>
                <button type="submit" className="secondary" disabled={notes === null}>{t("common.save")}</button>
              </form>
            </>
          )}
        </section>
      )}
    </>
  );
}
