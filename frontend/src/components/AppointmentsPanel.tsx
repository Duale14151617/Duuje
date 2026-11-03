import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { AppointmentOut, AppointmentTypeOut, Person } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { useI18n } from "../i18n";
import { Chip, ErrorNotice, Field, Notice } from "./ui";
import { UnitPicker } from "./UnitPicker";

/**
 * Command appointments (Taliye Qaybeed, Taliye Urur ...). An appointment is not a rank, not an assignment and not an
 * application role: it records who holds a command office, where and since when, and it never grants access by itself.
 * Ending one keeps the record and revokes any access that was linked to it. The server enforces every rule.
 */
export function AppointmentsPanel({ person }: { person: Person }) {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const serving = !["retired", "discharged", "died"].includes(person.status);
  const canManage = can("personnel.appointments_manage") && serving;
  const list = useFetch<{ results: AppointmentOut[] }>(`/personnel/${person.id}/appointments/`);
  const types = useFetch<{ results: AppointmentTypeOut[] }>(canManage ? "/personnel/appointment-types/" : null);
  const [adding, setAdding] = useState(false);
  const [unit, setUnit] = useState("");
  const [typeId, setTypeId] = useState("");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [to, setTo] = useState("");
  const [ref, setRef] = useState("");
  const [ending, setEnding] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const rows = list.data?.results ?? [];
  if (rows.length === 0 && !canManage) return null;

  async function run(fn: () => Promise<unknown>, after: () => void) {
    setBusy(true); setError(null);
    try { await fn(); list.reload(); after(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(() => api(`/personnel/${person.id}/appointments/add/`, { method: "POST", body: {
      org_unit: unit, appointment_type: typeId, effective_from: from, effective_to: to || null, authority_ref: ref } }),
    () => { setAdding(false); setUnit(""); setTypeId(""); setTo(""); setRef(""); });
  };
  const end = (e: FormEvent) => {
    e.preventDefault();
    void run(() => api(`/personnel/${person.id}/appointments/${ending}/end/`, { method: "POST", body: { reason } }),
      () => { setEnding(null); setReason(""); });
  };

  return (
    <section className="card">
      <h2>{t("appt.title")}</h2>
      <ErrorNotice error={error ?? list.error} />
      {rows.length === 0 && <p className="muted">{t("appt.none")}</p>}
      {rows.map((a) => (
        <div key={a.id} className="item">
          <div className="row">
            <b>{name(a.appointment_type)}</b>
            <Chip tone={a.current ? "approved" : "draft"}>{a.current ? t("appt.current") : t("appt.ended")}</Chip>
            {a.has_access_link && <Chip tone="draft">{t("appt.linked")}</Chip>}
          </div>
          <div className="stat"><span>{t("pers.unit")}</span><b>{name(a.org_unit)}</b></div>
          <div className="stat"><span>{t("appt.from")}</span><b>{a.effective_from}{a.effective_to ? ` → ${a.effective_to}` : ""}</b></div>
          {a.authority_ref && <p className="muted">{a.authority_ref}</p>}
          {a.end_reason && <p className="muted">{a.end_reason}</p>}
          {canManage && !a.ended_at && ending !== a.id && (
            <button type="button" className="secondary" onClick={() => setEnding(a.id)}>{t("appt.end")}</button>
          )}
          {ending === a.id && (
            <form onSubmit={end}>
              <Field label={t("appt.reason")}><input value={reason} maxLength={300} required onChange={(e) => setReason(e.target.value)} /></Field>
              <div className="row">
                <button type="submit" disabled={busy}>{t("appt.end")}</button>
                <button type="button" className="secondary" onClick={() => setEnding(null)}>{t("common.cancel")}</button>
              </div>
            </form>
          )}
        </div>
      ))}
      {canManage && !adding && (
        <div className="row" style={{ marginTop: "1rem" }}><button type="button" className="secondary" onClick={() => setAdding(true)}>{t("appt.add")}</button></div>
      )}
      {canManage && adding && (
        <form onSubmit={add} style={{ marginTop: "1rem" }}>
          <Notice>{t("appt.accessNote")}</Notice>
          <Field label={t("appt.type")}>
            <select value={typeId} required onChange={(e) => setTypeId(e.target.value)}>
              <option value="">—</option>
              {(types.data?.results ?? []).map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
            </select>
          </Field>
          <UnitPicker label={t("pers.unit")} value={unit} required onChange={(id) => setUnit(id)} params={{ placeable: 1 }} />
          <Field label={t("appt.from")}><input type="date" value={from} required onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={t("appt.to")}><input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
          <Field label={t("appt.authority")}><input value={ref} maxLength={150} onChange={(e) => setRef(e.target.value)} /></Field>
          <div className="row">
            <button type="submit" disabled={busy || !unit || !typeId}>{t("appt.add")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </section>
  );
}
