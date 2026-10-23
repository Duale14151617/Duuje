import { useState, type FormEvent } from "react";
import { api, uploadForm } from "../api/client";
import type { DeathRecordOut, Person } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { useI18n, type Key } from "../i18n";
import { Chip, ErrorNotice, Field, Notice } from "./ui";

/**
 * Death record on a personnel file: report -> attach evidence -> a different officer confirms. A death is a status, never
 * a deletion: the file, history and documents stay. Buttons show only to officers holding the matching permission, but the
 * server enforces every rule (separation of duties, evidence required, scope) regardless of what this screen shows.
 */
export function DeathPanel({ person, onChanged }: { person: Person; onChanged: () => void }) {
  const { t } = useI18n();
  const { me, can } = useAuth();
  const canReport = can("personnel.record_death");
  const canConfirm = can("personnel.confirm_death");
  const death = useFetch<{ results: DeathRecordOut[] }>(`/personnel/${person.id}/death/`);
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [withdrawing, setWithdrawing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const records = death.data?.results ?? [];
  const open = records.find((r) => r.state !== "withdrawn");
  const deceased = person.status === "died";
  const mayReport = canReport && !open && !deceased;
  if (!open && records.length === 0 && !mayReport) return null;  // nothing to show this reader

  async function run(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true); setError(null);
    try { await fn(); death.reload(); after?.(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const report = (e: FormEvent) => { e.preventDefault(); void run(() => api(`/personnel/${person.id}/death/report/`, { method: "POST", body: { date_of_death: day, note } }), () => { setDay(""); setNote(""); }); };
  const attach = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("title", title); form.append("category", "death_evidence"); form.append("file", file);
    void run(() => uploadForm(`/personnel/${person.id}/documents/upload/`, form), () => { setTitle(""); setFile(null); });
  };
  const confirm = () => void run(() => api(`/personnel/${person.id}/death/confirm/`, { method: "POST", body: { version: person.version } }), onChanged);
  const withdraw = (e: FormEvent) => { e.preventDefault(); void run(() => api(`/personnel/${person.id}/death/withdraw/`, { method: "POST", body: { reason } }), () => { setWithdrawing(false); setReason(""); }); };

  const own = open?.reported_by === me?.username;
  return (
    <section className="card">
      <h2>{t("death.title")}</h2>
      <ErrorNotice error={error ?? death.error} />
      {records.map((r) => (
        <div key={r.id} className="item">
          <div className="row"><Chip tone={r.state === "confirmed" ? "bad" : "draft"}>{t(`death.state.${r.state}` as Key)}</Chip></div>
          <div className="stat"><span>{t("death.date")}</span><b>{r.date_of_death}</b></div>
          <div className="stat"><span>{t("death.reportedBy")}</span><b>{r.reported_by}</b></div>
          {r.confirmed_by && <div className="stat"><span>{t("death.confirmedBy")}</span><b>{r.confirmed_by}</b></div>}
          {r.note && <p className="muted">{r.note}</p>}
          {r.withdrawn_reason && <p className="muted">{r.withdrawn_reason}</p>}
          {r.evidence && (
            <>
              <b>{t("death.evidence")}</b>
              {r.evidence.length === 0 ? <p className="muted">{t("death.noEvidence")}</p>
                : <ul className="list">{r.evidence.map((d) => <li key={d.id} className="item">{d.title}</li>)}</ul>}
            </>
          )}
        </div>
      ))}

      {open?.state === "reported" && (canReport || canConfirm) && (
        <>
          {canReport && (
            <form onSubmit={attach} style={{ marginTop: "1rem" }}>
              <Field label={t("doc.name")}><input value={title} maxLength={150} required onChange={(e) => setTitle(e.target.value)} /></Field>
              <Field label={t("doc.file")}><input type="file" accept="application/pdf,image/jpeg,image/png" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
              <button type="submit" className="secondary" disabled={busy}>{t("death.addEvidence")}</button>
            </form>
          )}
          {canConfirm && (own ? <Notice>{t("death.sameOfficer")}</Notice> : (
            <div style={{ marginTop: "1rem" }}>
              <Notice>{t("death.confirmWarn")}</Notice>
              <button type="button" onClick={confirm} disabled={busy}>{t("death.confirm")}</button>
            </div>
          ))}
          {!withdrawing && <div className="row" style={{ marginTop: "1rem" }}><button type="button" className="secondary" onClick={() => setWithdrawing(true)}>{t("death.withdraw")}</button></div>}
          {withdrawing && (
            <form onSubmit={withdraw} style={{ marginTop: "1rem" }}>
              <Field label={t("death.reason")}><input value={reason} maxLength={300} required onChange={(e) => setReason(e.target.value)} /></Field>
              <div className="row">
                <button type="submit" disabled={busy}>{t("death.withdraw")}</button>
                <button type="button" className="secondary" onClick={() => setWithdrawing(false)}>{t("common.cancel")}</button>
              </div>
            </form>
          )}
        </>
      )}

      {mayReport && (
        <form onSubmit={report} style={{ marginTop: "1rem" }}>
          <Field label={t("death.date")}><input type="date" value={day} max={new Date().toISOString().slice(0, 10)} required onChange={(e) => setDay(e.target.value)} /></Field>
          <Field label={t("death.note")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
          <button type="submit" disabled={busy}>{t("death.report")}</button>
        </form>
      )}
    </section>
  );
}
