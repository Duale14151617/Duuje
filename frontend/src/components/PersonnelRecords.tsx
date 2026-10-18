import { useState, type FormEvent } from "react";
import { api, downloadFile, uploadForm } from "../api/client";
import type { DisciplinaryEntry, PersonnelDocument } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Field, formatDate, Loading } from "./ui";
import { useI18n, type Key } from "../i18n";

const DIS_CATS = ["verbal_warning", "written_warning", "reprimand", "fine", "suspension", "demotion", "dismissal", "other"];
const DOC_CATS = ["service_record", "appointment", "training_certificate", "commendation", "identity", "other"];
const today = () => new Date().toISOString().slice(0, 10);

/** Disciplinary history. Entries are permanent; a correction is a new entry. Every view and change is logged by the server. */
export function DisciplinaryPanel({ personId, canManage }: { personId: string; canManage: boolean }) {
  const { t, lang } = useI18n();
  const list = useFetch<{ results: DisciplinaryEntry[] }>(`/personnel/${personId}/disciplinary/`);
  const [open, setOpen] = useState<null | "new" | string>(null);   // "new" or the id being corrected
  const [form, setForm] = useState({ category: "written_warning", incident_date: today(), summary: "", outcome: "", voided: false });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api(`/personnel/${personId}/disciplinary/add/`, { method: "POST", body: {
        ...form, ...(open && open !== "new" ? { corrects: open } : {}) } });
      setOpen(null); setForm({ category: "written_warning", incident_date: today(), summary: "", outcome: "", voided: false });
      list.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ marginTop: "1rem" }}>
      <h2>{t("dis.title")}</h2>
      <p className="muted small">{t("dis.hint")}</p>
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("dis.none")}</p>}
      <ul className="list">
        {list.data?.results.map((d) => (
          <li key={d.id} className="item" style={d.superseded ? { opacity: 0.65 } : undefined}>
            <b>{t(`dis.cat.${d.category}` as Key)}</b> · {d.incident_date}
            {d.corrects && <span className="muted"> · {d.voided ? t("dis.withdrawn") : t("dis.correction")}</span>}
            {d.superseded && <span className="muted"> · {t("dis.superseded")}</span>}
            <div style={{ whiteSpace: "pre-wrap" }}>{d.summary}</div>
            {d.outcome && <div className="muted" style={{ whiteSpace: "pre-wrap" }}>{d.outcome}</div>}
            <div className="muted small">{t("dis.by")} {d.recorded_by_username || "-"} · {formatDate(d.recorded_at, lang)}</div>
            {canManage && !d.superseded && open === null && (
              <button className="secondary" onClick={() => { setOpen(d.id); setForm({ category: d.category, incident_date: d.incident_date ?? today(), summary: d.summary, outcome: d.outcome, voided: false }); setErr(null); }}>
                {t("dis.correct")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {canManage && open === null && <button className="secondary" onClick={() => { setOpen("new"); setErr(null); }}>{t("dis.add")}</button>}
      {canManage && open !== null && (
        <form onSubmit={(e) => void save(e)}>
          <Field label={t("dis.category")}>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {DIS_CATS.map((c) => <option key={c} value={c}>{t(`dis.cat.${c}` as Key)}</option>)}
            </select>
          </Field>
          <Field label={t("dis.date")}><input type="date" max={today()} required value={form.incident_date} onChange={(e) => setForm({ ...form, incident_date: e.target.value })} /></Field>
          <Field label={t("dis.summary")}><textarea rows={4} maxLength={4000} required value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></Field>
          <Field label={t("dis.outcome")}><textarea rows={2} maxLength={1000} value={form.outcome} onChange={(e) => setForm({ ...form, outcome: e.target.value })} /></Field>
          {open !== "new" && (
            <label><input type="checkbox" checked={form.voided} onChange={(e) => setForm({ ...form, voided: e.target.checked })} /> {t("dis.voided")}</label>
          )}
          <ErrorNotice error={err} />
          <div className="row">
            <button type="submit" disabled={busy}>{t("dis.save")}</button>
            <button type="button" className="secondary" onClick={() => setOpen(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Service documents: upload, download, withdraw. Stored encrypted; every list, upload and download is logged by the server. */
export function DocumentsPanel({ personId, canManage }: { personId: string; canManage: boolean }) {
  const { t, lang } = useI18n();
  const list = useFetch<{ results: PersonnelDocument[] }>(`/personnel/${personId}/documents/`);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("service_record");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [withdrawing, setWithdrawing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const body = new FormData();
      body.append("title", title); body.append("category", category); body.append("note", note); body.append("file", file);
      await uploadForm(`/personnel/${personId}/documents/upload/`, body);
      setAdding(false); setTitle(""); setNote(""); setFile(null); list.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  async function download(d: PersonnelDocument) {
    setErr(null);
    const ext = d.content_type === "application/pdf" ? "pdf" : d.content_type === "image/png" ? "png" : "jpg";
    try { await downloadFile(`/personnel/${personId}/documents/${d.id}/download/`, `${d.title}.${ext}`); } catch (x) { setErr(x); }
  }
  async function withdraw(e: FormEvent) {
    e.preventDefault();
    if (!withdrawing) return;
    setBusy(true); setErr(null);
    try {
      await api(`/personnel/${personId}/documents/${withdrawing}/withdraw/`, { method: "POST", body: { reason } });
      setWithdrawing(null); setReason(""); list.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ marginTop: "1rem" }}>
      <h2>{t("doc.title")}</h2>
      <p className="muted small">{t("doc.hint")}</p>
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("doc.none")}</p>}
      <ul className="list">
        {list.data?.results.map((d) => (
          <li key={d.id} className="item">
            <b>{d.title}</b> · {t(`doc.cat.${d.category}` as Key)} · {Math.max(1, Math.round(d.size_bytes / 1024))} KB
            {d.note && <div className="muted">{d.note}</div>}
            <div className="muted small">{t("doc.uploadedBy")} {d.uploaded_by_username || "-"} · {formatDate(d.uploaded_at, lang)}</div>
            <div className="row">
              <button className="secondary" onClick={() => void download(d)}>{t("doc.download")}</button>
              {canManage && <button className="secondary" onClick={() => { setWithdrawing(d.id); setErr(null); }}>{t("doc.withdraw")}</button>}
            </div>
            {withdrawing === d.id && (
              <form onSubmit={(e) => void withdraw(e)}>
                <p className="muted small">{t("doc.withdrawHint")}</p>
                <Field label={t("doc.withdrawReason")}><input value={reason} maxLength={300} required onChange={(e) => setReason(e.target.value)} /></Field>
                <div className="row">
                  <button type="submit" disabled={busy}>{t("doc.withdraw")}</button>
                  <button type="button" className="secondary" onClick={() => setWithdrawing(null)}>{t("common.cancel")}</button>
                </div>
              </form>
            )}
          </li>
        ))}
      </ul>
      {canManage && !adding && <button className="secondary" onClick={() => { setAdding(true); setErr(null); }}>{t("doc.upload")}</button>}
      {canManage && adding && (
        <form onSubmit={(e) => void send(e)}>
          <Field label={t("doc.name")}><input value={title} maxLength={150} required onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label={t("doc.category")}>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {DOC_CATS.map((c) => <option key={c} value={c}>{t(`doc.cat.${c}` as Key)}</option>)}
            </select>
          </Field>
          <Field label={t("doc.note")}><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
          <Field label={t("doc.file")}><input type="file" accept="application/pdf,image/jpeg,image/png" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <div className="row">
            <button type="submit" disabled={busy || !file}>{t("doc.upload")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <ErrorNotice error={err} />
    </section>
  );
}
