import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Act } from "../components/ActionForm";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { left, tone, type CaseLite, type Claim, type PaySummary } from "./payrollShared";

interface Payment {
  id: string; kind: "salary" | "arrears" | "survivor"; line: string | null; claim: string | null; allocation: string | null; personnel: string; personnel_name: string;
  service_number: string | null; beneficiary: string | null; period: string; method: "sahal" | "bank_transfer"; recipient_name: string; recipient_display: string;
  amount: string; currency: string; transaction_reference: string; status: string; failure_reason: string; note: string; paid_on: string | null;
  reconciliation_status: string; statement_ref: string; reconciliation_note: string; prepared_by: string; authorized_by: string | null; executed_by: string | null;
  reconciled_by: string | null; retry_of: string | null;
}
interface PaymentFull extends Payment { events: { action: string; from: string; to: string; actor: string; comment: string; at: string }[] }
interface RunLite { id: string; year: number; month: number; status: string }
interface LineLite { id: string; personnel: string; service_number: string | null; kind: string; approved_net: string | null; paid: string; currency: string; death_month: boolean }

/** What a payment form starts with. A retry or an "arrears -> pay" shortcut fixes the target; the rest can still be edited. */
export interface PayPreset {
  kind: "salary" | "arrears" | "survivor"; line?: string; claim?: string; allocation?: string; personnel?: string; beneficiary?: string;
  year?: number; month?: number; amount?: string; method?: string; recipient_name?: string; retry_of?: string; label?: string;
}

export function Payments({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [recon, setRecon] = useState("");
  const sum = useFetch<PaySummary>("/payroll/runs/summary/");
  const list = useFetch<{ results: Payment[] }>("/payroll/payments/", { status: status || undefined, reconciliation: recon || undefined });
  const done = () => { list.reload(); sum.reload(); onChanged(); };
  return (
    <>
      <Notice>{t("payx.noIntegration")}</Notice>
      <ErrorNotice error={list.error ?? sum.error} />
      {sum.data && (
        <section className="card">
          <div className="stat"><span>{t("payx.unreconciled")}</span><b>{sum.data.payments_unreconciled}</b></div>
          <div className="stat"><span>{t("payx.discrepancies")}</span><b>{sum.data.payments_with_discrepancy}</b></div>
        </section>
      )}
      {can("payment.prepare") && <PayForm onDone={done} />}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <Field label={t("payx.filterStatus")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("pay.all")}</option>
            {["prepared", "authorized", "processing", "pending", "paid", "failed", "cancelled"].map((s) => <option key={s} value={s}>{t(`payx.status.${s}` as Key)}</option>)}
          </select>
        </Field>
        <Field label={t("payx.filterRecon")}>
          <select value={recon} onChange={(e) => setRecon(e.target.value)}>
            <option value="">{t("pay.all")}</option>
            {["unreconciled", "reconciled", "discrepancy"].map((s) => <option key={s} value={s}>{t(`payx.recon.${s}` as Key)}</option>)}
          </select>
        </Field>
      </div>
      {list.data && list.data.results.length === 0 && <p className="muted">{t("payx.none")}</p>}
      <ul className="list">{(list.data?.results ?? []).map((p) => <PaymentItem key={p.id} p={p} onChanged={done} />)}</ul>
    </>
  );
}

function PaymentItem({ p, onChanged }: { p: Payment; onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [retry, setRetry] = useState(false);
  const base = `/payroll/payments/${p.id}`;
  const chain = [p.prepared_by && `${t("payx.preparedBy")} ${p.prepared_by}`, p.authorized_by && `${t("payx.authorizedBy")} ${p.authorized_by}`,
    p.executed_by && `${t("payx.sentBy")} ${p.executed_by}`, p.reconciled_by && `${t("payx.reconciledBy")} ${p.reconciled_by}`].filter(Boolean).join(" · ");
  const comment = [{ key: "comment", label: t("surv.comment") }];
  const actPrepare = can("payment.prepare"), actAuth = can("payment.authorize"), actExec = can("payment.execute"), actRecon = can("payment.reconcile");
  const preset: PayPreset = { kind: p.kind, line: p.line ?? undefined, claim: p.claim ?? undefined, allocation: p.allocation ?? undefined, personnel: p.personnel,
    beneficiary: p.beneficiary ?? undefined, year: Number(p.period.slice(0, 4)), month: Number(p.period.slice(5, 7)), amount: p.amount, method: p.method,
    recipient_name: p.recipient_name, retry_of: p.id, label: `${p.personnel_name} · ${t(`payx.kind.${p.kind}` as Key)} ${p.period}` };
  return (
    <li className="item">
      <button type="button" className="secondary" onClick={() => setOpen(!open)}>
        <b>{p.personnel_name}</b> ({p.service_number ?? "—"}) · {t(`payx.kind.${p.kind}` as Key)} · {p.period}
      </button>
      <div className="stat"><span>{t(`payx.method.${p.method}` as Key)} · {p.recipient_name} · {p.recipient_display}</span><b>{p.amount} {p.currency}</b></div>
      <div className="row">
        <Chip tone={tone(p.status)}>{t(`payx.status.${p.status}` as Key)}</Chip>
        {p.status === "paid" && <Chip tone={tone(p.reconciliation_status)}>{t(`payx.recon.${p.reconciliation_status}` as Key)}</Chip>}
        {p.transaction_reference && <span className="muted">{t("payx.reference")}: {p.transaction_reference}{p.paid_on ? ` · ${p.paid_on}` : ""}</span>}
      </div>
      <p className="muted">{chain}</p>
      {p.failure_reason && <p className="muted">{t("payx.reason")}: {p.failure_reason}</p>}
      {p.reconciliation_note && <p className="muted">{p.reconciliation_note}</p>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        {p.status === "prepared" && actAuth && <Act title={t("payx.authorize")} path={`${base}/authorize/`} fields={[]} onDone={onChanged} submitLabel={t("payx.authorize")} />}
        {p.status === "authorized" && actExec && <Act title={t("payx.process")} path={`${base}/process/`} fields={[]} onDone={onChanged} submitLabel={t("payx.process")} />}
        {p.status === "processing" && actExec && <Act title={t("payx.markPending")} path={`${base}/pending/`} fields={[{ key: "comment", label: t("surv.comment"), required: false }]} onDone={onChanged} submitLabel={t("payx.markPending")} />}
        {["processing", "pending"].includes(p.status) && actExec && <>
          <Act title={t("payx.complete")} path={`${base}/complete/`} onDone={onChanged} submitLabel={t("payx.complete")}
            fields={[{ key: "transaction_reference", label: t("payx.reference") }, { key: "paid_on", label: t("payx.paidOn"), type: "date" }]} />
          <Act title={t("payx.fail")} path={`${base}/fail/`} fields={[{ key: "reason", label: t("payx.failReason") }]} onDone={onChanged} submitLabel={t("payx.fail")} /></>}
        {["prepared", "authorized"].includes(p.status) && (actPrepare || actAuth) && <Act title={t("payx.cancel")} path={`${base}/cancel/`} fields={comment} onDone={onChanged} submitLabel={t("payx.cancel")} />}
        {p.status === "paid" && p.reconciliation_status !== "reconciled" && actRecon && <Act title={t("payx.reconcile")} path={`${base}/reconcile/`} onDone={onChanged} submitLabel={t("payx.reconcile")}
          fields={[{ key: "statement_ref", label: t("payx.statementRef") }, { key: "statement_amount", label: t("payx.statementAmount"), type: "number" },
                   { key: "statement_date", label: t("payx.statementDate"), type: "date" }, { key: "note", label: t("payx.reconNote"), required: false }]} />}
        {p.status === "failed" && actPrepare && !retry && <button type="button" className="secondary" onClick={() => setRetry(true)}>{t("payx.retry")}</button>}
      </div>
      {retry && <PayForm preset={preset} startOpen onDone={() => { setRetry(false); onChanged(); }} onCancel={() => setRetry(false)} />}
      {open && <PaymentDetail id={p.id} />}
    </li>
  );
}

function PaymentDetail({ id }: { id: string }) {
  const { t, tr } = useI18n();
  const { can } = useAuth();
  const d = useFetch<PaymentFull>(`/payroll/payments/${id}/`);
  const [shown, setShown] = useState<Record<string, string> | null>(null);
  const [err, setErr] = useState<unknown>(null);
  async function reveal() {
    setErr(null);
    try { const r = await api<{ recipient: Record<string, string> }>(`/payroll/payments/${id}/reveal/`); setShown(r.recipient); } catch (x) { setErr(x); }
  }
  if (!d.data) return <ErrorNotice error={d.error} />;
  return (
    <div className="card">
      <ErrorNotice error={err} />
      {can("payment.details") && (shown
        ? <div><p className="muted">{t("payx.revealNote")}</p>
            {Object.entries(shown).map(([k, v]) => <div key={k} className="stat"><span>{tr(`payx.field.${k}`) ?? k}</span><b>{v}</b></div>)}
            <button type="button" className="secondary" onClick={() => setShown(null)}>{t("payx.hide")}</button></div>
        : <button type="button" className="secondary" onClick={() => void reveal()}>{t("payx.reveal")}</button>)}
      {d.data.note && <p className="muted">{d.data.note}</p>}
      <h3>{t("pay.history")}</h3>
      <ul className="list">{d.data.events.map((e, i) => (
        <li key={i} className="muted">{new Date(e.at).toLocaleString()} · {tr(`payx.act.${e.action}`) ?? e.action} · {e.actor}{e.comment ? ` · ${e.comment}` : ""}</li>
      ))}</ul>
    </div>
  );
}

/** Prepare a payment instruction against an amount that is already approved (a salary line, an arrears claim or a survivor benefit).
 *  Preparing does not send money: another officer authorizes it, then an executor sends it outside the system and records the reference. */
export function PayForm({ preset, startOpen, onDone, onCancel }: { preset?: PayPreset; startOpen?: boolean; onDone: () => void; onCancel?: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [open, setOpen] = useState(!!startOpen);
  const [kind, setKind] = useState<"salary" | "arrears" | "survivor">(preset?.kind ?? "salary");
  const [runId, setRunId] = useState("");
  const [line, setLine] = useState(preset?.line ?? "");
  const [claim, setClaim] = useState(preset?.claim ?? "");
  const [caseId, setCaseId] = useState("");
  const [alloc, setAlloc] = useState(preset?.allocation ?? "");
  const [ben, setBen] = useState(preset?.beneficiary ?? "");
  const now = new Date();
  const [year, setYear] = useState(String(preset?.year ?? now.getFullYear()));
  const [month, setMonth] = useState(String(preset?.month ?? now.getMonth() + 1));
  const [amount, setAmount] = useState(preset?.amount ?? "");
  const [method, setMethod] = useState(preset?.method ?? "sahal");
  const [mobile, setMobile] = useState("");
  const [bankName, setBankName] = useState("");
  const [account, setAccount] = useState("");
  const [rname, setRname] = useState(preset?.recipient_name ?? "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const locked = !!preset && !!(preset.line || preset.claim || preset.allocation);

  const runs = useFetch<{ results: RunLite[] }>(open && kind === "salary" && !locked ? "/payroll/runs/" : null);
  const run = useFetch<{ lines: LineLite[] }>(open && kind === "salary" && runId ? `/payroll/runs/${runId}/` : null);
  const claims = useFetch<{ results: Claim[] }>(open && kind === "arrears" && !locked ? "/payroll/arrears/" : null);
  const cases = useFetch<{ results: CaseLite[] }>(open && can("survivor.view") ? "/survivor-cases/" : null);

  const lines = (run.data?.lines ?? []).filter((l) => l.approved_net !== null && Number(left(l.approved_net, l.paid)) > 0);
  const approvedClaims = (claims.data?.results ?? []).filter((c) => c.status === "approved" && Number(c.outstanding ?? 0) > 0);
  const chosenLine = lines.find((l) => l.id === line);
  const chosenClaim = approvedClaims.find((c) => c.id === claim);
  const personnel = preset?.personnel ?? (kind === "salary" ? chosenLine?.personnel : kind === "arrears" ? chosenClaim?.personnel : undefined);
  const personCases = (cases.data?.results ?? []).filter((c) => c.personnel === personnel);
  const needBen = kind !== "survivor" && (kind === "salary" ? (chosenLine?.death_month ?? false) || !!(preset?.beneficiary) : personCases.length > 0 || !!preset?.beneficiary);
  const benOptions = personCases.flatMap((c) => c.beneficiaries.filter((b) => b.state === "verified"));
  const liveCases = (cases.data?.results ?? []).filter((c) => c.status === "verified");
  const allocs = (liveCases.find((c) => c.id === caseId)?.beneficiaries ?? []).flatMap((b) => b.allocations.filter((a) => a.status === "authorized").map((a) => ({ b, a })));
  const chosenAlloc = allocs.find(({ a }) => a.id === alloc)?.a;
  const perPeriod = kind === "survivor" && (chosenAlloc ? chosenAlloc.basis_kind === "per_period" : !!preset?.year);

  function reset() { setOpen(false); setLine(""); setClaim(""); setAlloc(""); setCaseId(""); setAmount(""); setMobile(""); setBankName(""); setAccount(""); setNote(""); setBen(""); setRname(""); }
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(null); setBusy(true);
    const body: Record<string, unknown> = { kind, method, amount, recipient: method === "sahal" ? { mobile_number: mobile } : { bank_name: bankName, account_number: account } };
    if (rname.trim()) body.recipient_name = rname.trim();
    if (note.trim()) body.note = note.trim();
    if (kind === "salary") body.line = line;
    if (kind === "arrears") body.claim = claim;
    if (kind === "survivor") { body.allocation = alloc; if (perPeriod) { body.period_year = Number(year); body.period_month = Number(month); } }
    if (needBen) body.beneficiary = ben;
    if (preset?.retry_of) body.retry_of = preset.retry_of;
    try { await api("/payroll/payments/", { method: "POST", body }); setSent(true); reset(); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  if (!open) return (
    <>
      {sent && <Notice>{t("payx.prepared")}</Notice>}
      <div className="row"><button type="button" onClick={() => { setSent(false); setOpen(true); }}>{t("payx.prepare")}</button></div>
    </>
  );
  const ready = method === "sahal" ? !!mobile : !!(bankName && account);
  const target = kind === "salary" ? !!line : kind === "arrears" ? !!claim : !!alloc;
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{preset?.retry_of ? t("payx.retry") : t("payx.prepare")}</h3>
      <ErrorNotice error={err ?? runs.error ?? run.error ?? claims.error ?? cases.error} />
      {preset?.label && <p className="muted">{preset.label}</p>}
      {!locked && <Field label={t("payx.kind")}>
        <select value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setLine(""); setClaim(""); setAlloc(""); setAmount(""); setBen(""); }}>
          {(["salary", "arrears", "survivor"] as const).map((k) => <option key={k} value={k}>{t(`payx.kind.${k}` as Key)}</option>)}
        </select></Field>}
      {!locked && kind === "salary" && <>
        <Field label={t("payx.run")}>
          <select value={runId} onChange={(e) => { setRunId(e.target.value); setLine(""); setAmount(""); }}><option value="">—</option>
            {(runs.data?.results ?? []).filter((r) => ["approved", "paid"].includes(r.status)).map((r) => <option key={r.id} value={r.id}>{r.year}-{String(r.month).padStart(2, "0")} · {t(`pay.rstatus.${r.status}` as Key)}</option>)}</select></Field>
        {runId && run.data && lines.length === 0 && <p className="muted">{t("payx.noLines")}</p>}
        {lines.length > 0 && <Field label={t("payx.line")}>
          <select value={line} required onChange={(e) => { setLine(e.target.value); const l = lines.find((x) => x.id === e.target.value); setAmount(l ? left(l.approved_net, l.paid) : ""); setBen(""); }}><option value="">—</option>
            {lines.map((l) => <option key={l.id} value={l.id}>{l.service_number ?? l.id.slice(0, 8)} · {left(l.approved_net, l.paid)} {l.currency} {t("payx.left")}{l.death_month ? ` · ${t("pay.deathMonth")}` : ""}</option>)}</select></Field>}</>}
      {!locked && kind === "arrears" && <Field label={t("payx.claim")}>
        <select value={claim} required onChange={(e) => { setClaim(e.target.value); const c = approvedClaims.find((x) => x.id === e.target.value); setAmount(c?.outstanding ?? ""); setBen(""); }}><option value="">—</option>
          {approvedClaims.map((c) => <option key={c.id} value={c.id}>{c.personnel_name} · {c.outstanding} {c.currency} {t("payx.left")}</option>)}</select></Field>}
      {!locked && kind === "survivor" && <>
        <Field label={t("payx.case")}>
          <select value={caseId} onChange={(e) => { setCaseId(e.target.value); setAlloc(""); setAmount(""); }}><option value="">—</option>
            {liveCases.map((c) => <option key={c.id} value={c.id}>{c.personnel_name} ({c.service_number ?? "—"})</option>)}</select></Field>
        {caseId && <Field label={t("payx.allocation")}>
          <select value={alloc} required onChange={(e) => { setAlloc(e.target.value); setAmount(allocs.find(({ a }) => a.id === e.target.value)?.a.amount ?? ""); }}><option value="">—</option>
            {allocs.map(({ b, a }) => <option key={a.id} value={a.id}>{b.full_name} · {a.amount} {a.currency}</option>)}</select></Field>}</>}
      {perPeriod && <div className="row">
        <Field label={t("pay.year")}><input type="number" min={2000} max={2100} required value={year} onChange={(e) => setYear(e.target.value)} /></Field>
        <Field label={t("pay.month")}><input type="number" min={1} max={12} required value={month} onChange={(e) => setMonth(e.target.value)} /></Field></div>}
      {needBen && <Field label={t("payx.beneficiary")}>
        <select value={ben} required onChange={(e) => setBen(e.target.value)}><option value="">—</option>
          {benOptions.map((b) => <option key={b.id} value={b.id}>{b.full_name} · {t(`surv.tier.${b.tier}` as Key)}</option>)}</select></Field>}
      <Field label={t("payx.amount")}><input type="number" step="0.01" min="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <Field label={t("payx.method")}>
        <select value={method} onChange={(e) => setMethod(e.target.value)}>{(["sahal", "bank_transfer"] as const).map((m) => <option key={m} value={m}>{t(`payx.method.${m}` as Key)}</option>)}</select></Field>
      {method === "sahal"
        ? <Field label={t("payx.mobile")}><input inputMode="tel" required maxLength={20} value={mobile} onChange={(e) => setMobile(e.target.value)} /></Field>
        : <><Field label={t("payx.bankName")}><input required maxLength={100} value={bankName} onChange={(e) => setBankName(e.target.value)} /></Field>
            <Field label={t("payx.account")}><input required maxLength={40} value={account} onChange={(e) => setAccount(e.target.value)} /></Field></>}
      <Field label={t("payx.recipientName")}><input maxLength={150} value={rname} onChange={(e) => setRname(e.target.value)} /></Field>
      <Field label={t("payx.note")}><input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <div className="row">
        <button type="submit" disabled={busy || !ready || !target}>{t("payx.prepare")}</button>
        <button type="button" className="secondary" onClick={() => { reset(); onCancel?.(); }}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}
