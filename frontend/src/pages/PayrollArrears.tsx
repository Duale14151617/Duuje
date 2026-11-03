import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Act } from "../components/ActionForm";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { PayForm } from "./PayrollPayments";
import { tone, type CaseLite, type Claim } from "./payrollShared";

interface Person { id: string; full_name: string; service_number: string | null; status: string }
interface Picture { unpaid_approved_lines: { line: string; period: string; outstanding: string }[] }

/** Arrears = earlier unpaid salary. Kept apart from payroll runs and survivor benefits; nothing expires or is forfeited.
 *  Every claim is recorded, verified and approved by three different people, and paid only through the payment workflow. */
export function Arrears({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const list = useFetch<{ results: Claim[] }>("/payroll/arrears/");
  const done = () => { list.reload(); onChanged(); };
  const rows = (list.data?.results ?? []).filter((c) => !status || c.status === status);
  return (
    <>
      <p className="muted">{t("arr.intro")}</p>
      <ErrorNotice error={list.error} />
      {can("arrears.manage") && <RecordClaim onDone={done} />}
      <Field label={t("pay.show")}>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("pay.all")}</option>
          {["recorded", "verified", "approved", "rejected"].map((s) => <option key={s} value={s}>{t(`arr.status.${s}` as Key)}</option>)}
        </select>
      </Field>
      {list.data && rows.length === 0 && <p className="muted">{t("arr.none")}</p>}
      <ul className="list">{rows.map((c) => <ClaimItem key={c.id} c={c} onChanged={done} />)}</ul>
    </>
  );
}

function ClaimItem({ c, onChanged }: { c: Claim; onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [pay, setPay] = useState(false);
  const [prepared, setPrepared] = useState(false);
  const base = `/payroll/arrears/${c.id}`;
  const chain = [`${t("arr.recordedBy")} ${c.recorded_by}`, c.verified_by && `${t("arr.verifiedBy")} ${c.verified_by}`, c.approved_by && `${t("arr.approvedBy")} ${c.approved_by}`].filter(Boolean).join(" · ");
  const open = c.status === "approved" && Number(c.outstanding ?? 0) > 0;
  const optional = [{ key: "comment", label: t("surv.comment"), required: false }], required = [{ key: "comment", label: t("surv.comment") }];
  return (
    <li className="item">
      <b>{c.personnel_name}</b> ({c.service_number ?? "—"})
      <div className="stat"><span>{c.periods.join(", ")}</span><b>{c.amount} {c.currency}</b></div>
      <div className="row"><Chip tone={tone(c.status)}>{t(`arr.status.${c.status}` as Key)}</Chip>
        {c.status === "approved" && <span className="muted">{t("pay.paid")} {c.paid} · {t("arr.outstanding")} {c.outstanding}</span>}</div>
      <p className="muted">{t("arr.evidence")}: {c.evidence_ref}{c.note ? ` · ${c.note}` : ""}</p>
      <p className="muted">{chain}</p>
      {c.decision_note && <p className="muted">{c.decision_note}</p>}
      {prepared && <Notice>{t("payx.prepared")}</Notice>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        {c.status === "recorded" && can("arrears.manage") && <>
          <Act title={t("arr.verify")} path={`${base}/verify/`} extra={{ verify: true }} fields={optional} onDone={onChanged} submitLabel={t("arr.verify")} />
          <Act title={t("surv.reject")} path={`${base}/verify/`} extra={{ verify: false }} fields={required} onDone={onChanged} submitLabel={t("surv.reject")} /></>}
        {c.status === "verified" && can("arrears.approve") && <>
          <Act title={t("surv.approve")} path={`${base}/approve/`} extra={{ approve: true }} fields={optional} onDone={onChanged} submitLabel={t("surv.approve")} />
          <Act title={t("surv.reject")} path={`${base}/approve/`} extra={{ approve: false }} fields={required} onDone={onChanged} submitLabel={t("surv.reject")} /></>}
        {open && can("payment.prepare") && !pay && <button type="button" className="secondary" onClick={() => { setPrepared(false); setPay(true); }}>{t("arr.pay")}</button>}
      </div>
      {pay && <PayForm startOpen preset={{ kind: "arrears", claim: c.id, personnel: c.personnel, amount: c.outstanding ?? "", label: `${c.personnel_name} · ${t("payx.kind.arrears")} · ${c.outstanding} ${c.currency}` }}
                       onDone={() => { setPay(false); setPrepared(true); onChanged(); }} onCancel={() => setPay(false)} />}
    </li>
  );
}

function RecordClaim({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [person, setPerson] = useState<Person | null>(null);
  const [picked, setPicked] = useState<Record<string, string>>({});  // line id -> period
  const [periods, setPeriods] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const found = useFetch<{ results: Person[] }>(open && !person && q.trim().length >= 2 ? "/payroll/profiles/people/" : null, { q: q.trim() });
  const deceased = useFetch<{ results: CaseLite[] }>(open && !person && can("survivor.view") ? "/survivor-cases/" : null);
  const pic = useFetch<Picture>(open && person ? `/payroll/personnel/${person.id}/` : null);
  if (!open) return <div className="row"><button type="button" onClick={() => setOpen(true)}>{t("arr.record")}</button></div>;

  function toggle(line: string, period: string, outstanding: string) {
    const next = { ...picked };
    if (next[line]) delete next[line]; else next[line] = period;
    setPicked(next);
    const ids = Object.keys(next);
    setPeriods([...new Set(Object.values(next))].sort().join(", "));
    const total = (pic.data?.unpaid_approved_lines ?? []).filter((l) => ids.includes(l.line)).reduce((s, l) => s + Number(l.outstanding), 0);
    setAmount(ids.length ? total.toFixed(2) : "");
    void outstanding;
  }
  function close() { setOpen(false); setPerson(null); setQ(""); setPicked({}); setPeriods(""); setAmount(""); setEvidence(""); setNote(""); setErr(null); }
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(null); setBusy(true);
    const body: Record<string, unknown> = { personnel: person?.id, periods: periods.split(/[\s,;]+/).filter(Boolean), amount, currency: currency.toUpperCase(), evidence_ref: evidence, source_lines: Object.keys(picked) };
    if (note.trim()) body.note = note.trim();
    try { await api("/payroll/arrears/", { method: "POST", body }); close(); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("arr.record")}</h3>
      <ErrorNotice error={err ?? found.error ?? deceased.error ?? pic.error} />
      {person
        ? <p><b>{person.full_name}</b> ({person.service_number ?? "—"}) <button type="button" className="secondary" onClick={() => { setPerson(null); setPicked({}); setPeriods(""); setAmount(""); }}>{t("pay.change")}</button></p>
        : <>
          <Field label={t("pay.findPerson")}><input value={q} maxLength={60} onChange={(e) => setQ(e.target.value)} /></Field>
          <ul className="list">{(found.data?.results ?? []).map((p) => <li key={p.id} className="item"><button type="button" className="secondary" onClick={() => setPerson(p)}>{p.full_name} ({p.service_number ?? "—"})</button></li>)}</ul>
          {can("survivor.view") && <Field label={t("arr.orDeceased")}>
            <select value="" onChange={(e) => { const c = (deceased.data?.results ?? []).find((x) => x.personnel === e.target.value); if (c) setPerson({ id: c.personnel, full_name: c.personnel_name, service_number: c.service_number, status: "died" }); }}>
              <option value="">—</option>
              {(deceased.data?.results ?? []).map((c) => <option key={c.id} value={c.personnel}>{c.personnel_name} ({c.service_number ?? "—"})</option>)}</select></Field>}</>}
      {person && <>
        {(pic.data?.unpaid_approved_lines.length ?? 0) > 0 && <>
          <p className="muted">{t("arr.unpaidLines")}</p>
          <ul className="list">{(pic.data?.unpaid_approved_lines ?? []).map((l) => (
            <li key={l.line} className="item"><label><input type="checkbox" checked={!!picked[l.line]} onChange={() => toggle(l.line, l.period, l.outstanding)} /> {l.period} · {l.outstanding}</label></li>
          ))}</ul></>}
        <Field label={t("arr.periods")}><input required value={periods} placeholder="2026-03, 2026-04" onChange={(e) => setPeriods(e.target.value)} /></Field>
        <Field label={t("payx.amount")}><input type="number" step="0.01" min="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label={t("surv.currency")}><input required maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value)} /></Field>
        <Field label={t("arr.evidence")}><input required maxLength={200} value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
        <Field label={t("payx.note")}><input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field></>}
      <div className="row"><button type="submit" disabled={busy || !person}>{t("arr.record")}</button><button type="button" className="secondary" onClick={close}>{t("common.cancel")}</button></div>
    </form>
  );
}
