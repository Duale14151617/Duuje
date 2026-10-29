import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { TaskMember, UnitTaskOut } from "../api/types";
import { useFetch } from "../api/useFetch";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, ErrorNotice, Field, formatDate, Loading } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const B = "/operations/tasks";
const TONE = { open: "pending", in_progress: "in_review", completed: "approved", cancelled: "rejected" } as const;

function NewTask({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [unit, setUnit] = useState("");
  const [f, setF] = useState({ title: "", description: "", authority_ref: "", assigned_on: "", due_on: "", responsible: "" });
  const [error, setError] = useState<unknown>(null);
  const members = useFetch<{ results: TaskMember[] }>(unit ? `${B}/members/` : null, { org_unit: unit });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((c) => ({ ...c, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try {
      await api(`${B}/`, { method: "POST", body: { ...f, org_unit: unit, assigned_on: f.assigned_on || undefined, due_on: f.due_on || null, responsible: f.responsible || null } });
      setF({ title: "", description: "", authority_ref: "", assigned_on: "", due_on: "", responsible: "" }); onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>{t("tk.new")}</h2>
      <ErrorNotice error={error} />
      <UnitPicker label={t("tk.unit")} value={unit} onChange={(id) => { setUnit(id); setF((c) => ({ ...c, responsible: "" })); }} required />
      <Field label={t("tk.title.label" as Key)}><input value={f.title} maxLength={200} onChange={set("title")} required /></Field>
      <Field label={t("tk.description")}><textarea rows={3} value={f.description} maxLength={1000} onChange={set("description")} /></Field>
      <div className="grid">
        <Field label={t("cr.orderRef")}><input value={f.authority_ref} maxLength={150} onChange={set("authority_ref")} required /></Field>
        <Field label={t("tk.assignedOn")}><input type="date" value={f.assigned_on} onChange={set("assigned_on")} /></Field>
        <Field label={t("tk.dueOn")}><input type="date" value={f.due_on} onChange={set("due_on")} /></Field>
        <Field label={t("tk.responsible")}>
          <select value={f.responsible} onChange={set("responsible")}>
            <option value="" />
            {(members.data?.results ?? []).map((m) => <option key={m.id} value={m.id}>{m.rank} {m.full_name} · {m.service_number ?? "-"}</option>)}
          </select>
        </Field>
      </div>
      <button>{t("common.create")}</button>
    </form>
  );
}

function Row({ task, onChanged }: { task: UnitTaskOut; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const [report, setReport] = useState("");
  const [doc, setDoc] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const open = task.status === "open" || task.status === "in_progress";
  async function act(name: string, body: Record<string, unknown> = {}) {
    setError(null);
    try { await api(`${B}/${task.id}/${name}/`, { method: "POST", body: { version: task.version, ...body } }); onChanged(); }
    catch (err) { setError(err); }
  }
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{task.title}</strong>
        <span>{task.overdue && <Chip tone="rejected">{t("tk.overdue")}</Chip>} <Chip tone={TONE[task.status]}>{t(`tk.status.${task.status}` as Key)}</Chip></span>
      </div>
      <p className="muted">
        {task.org_unit_name} · {t("cr.order")}: {task.authority_ref} · {t("tk.assignedOn")} {task.assigned_on}{task.due_on ? ` · ${t("tk.dueOn")} ${task.due_on}` : ""}
        {task.responsible && <><br />{t("tk.responsible")}: {task.responsible.rank} {task.responsible.full_name} · {task.responsible.service_number ?? "-"}</>}
        {task.description && <><br />{task.description}</>}
        {task.completion_report && <><br />{t("tk.report")}: {task.completion_report}{task.document_ref ? ` (${task.document_ref})` : ""}{task.completed_at ? ` · ${formatDate(task.completed_at, lang)}` : ""}</>}
        {task.cancel_reason && <><br />{task.cancel_reason}</>}
      </p>
      <ErrorNotice error={error} />
      {open && (
        <div className="grid">
          <Field label={t("tk.report")}><input value={report} maxLength={2000} onChange={(e) => setReport(e.target.value)} /></Field>
          <Field label={t("tk.documentRef")}><input value={doc} maxLength={150} onChange={(e) => setDoc(e.target.value)} /></Field>
          <Field label={t("cr.reason")}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
          <div className="row">
            {task.status === "open" && <button className="secondary" onClick={() => void act("start")}>{t("tk.start")}</button>}
            <button onClick={() => void act("complete", { completion_report: report, document_ref: doc })}>{t("tk.complete")}</button>
            <button className="secondary" onClick={() => void act("cancel", { reason })}>{t("fd.cancel")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Tasks() {
  const { t } = useI18n();
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const list = useFetch<{ results: UnitTaskOut[] }>(`${B}/`, { status, overdue: overdue ? 1 : undefined });
  return (
    <main>
      <h1>{t("tk.title")}</h1>
      <p className="muted">{t("tk.intro")}</p>
      <NewTask onDone={list.reload} />
      <div className="row">
        <Field label={t("cr.status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("cr.all")}</option>
            {(["open", "in_progress", "completed", "cancelled"] as const).map((s) => <option key={s} value={s}>{t(`tk.status.${s}` as Key)}</option>)}
          </select>
        </Field>
        <label><input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /> {t("tk.overdue")}</label>
      </div>
      {list.loading ? <Loading /> : <ErrorNotice error={list.error} />}
      {list.data?.results.length === 0 && <p className="muted">{t("cr.empty")}</p>}
      {(list.data?.results ?? []).map((x) => <Row key={x.id} task={x} onChanged={list.reload} />)}
    </main>
  );
}
