import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Act } from "../components/ActionForm";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { tone, type Claim } from "./payrollShared";

interface Decision {
  id: string; status_at_decision: string; kind: string; decision_text: string; deduction_percent: number; reason: string; effective_date: string; supporting_ref: string;
  state: string; recorded_by: string; decided_by: string | null; decision_note: string;
}
interface Row { personnel: string; service_number: string | null; full_name: string; status: string; latest_decision: Decision | null; needs_decision: boolean }
interface Picture {
  personnel: string; full_name: string; status: string;
  salary_profile: { base_amount: string; currency: string; effective_from: string } | null;
  lines: { id: string; period: string; kind: string; calculated_net: string; approved_net: string | null; paid: string; status_flag: string }[];
  unpaid_approved_lines: { line: string; period: string; outstanding: string }[];
  arrears_claims: Claim[]; survivor_cases: { id: string; status: string }[]; pay_decisions: Decision[];
}

/** Pay decisions for suspended and jailed members. A decision is only a record until a DIFFERENT officer approves it; nothing is stopped or
 *  reduced automatically. An approved formal decision with a deduction takes effect on payroll runs prepared after its effective date. */
export function Decisions({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const q = useFetch<{ results: Row[] }>("/payroll/personnel/");
  const [openId, setOpenId] = useState<string | null>(null);
  const done = () => { q.reload(); onChanged(); };
  return (
    <>
      <p className="muted">{t("pdec.intro")}</p>
      <ErrorNotice error={q.error} />
      {q.data && q.data.results.length === 0 && <p className="muted">{t("pdec.none")}</p>}
      <ul className="list">
        {(q.data?.results ?? []).map((r) => (
          <li key={r.personnel} className="item">
            <button type="button" className="secondary" onClick={() => setOpenId(openId === r.personnel ? null : r.personnel)}><b>{r.full_name}</b> ({r.service_number ?? "—"})</button>
            <div className="row">
              <Chip tone="draft">{t(`pdec.pstatus.${r.status}` as Key)}</Chip>
              {r.needs_decision && <Chip tone="bad">{t("pdec.needsDecision")}</Chip>}
              {r.latest_decision && <span className="muted">{t(`pdec.kind.${r.latest_decision.kind}` as Key)} · {t(`pdec.state.${r.latest_decision.state}` as Key)}{r.latest_decision.deduction_percent ? ` · ${r.latest_decision.deduction_percent}%` : ""}</span>}
            </div>
            <p className="muted">{t("pdec.flag")}</p>
            {openId === r.personnel && <Person id={r.personnel} onChanged={done} />}
          </li>
        ))}
      </ul>
    </>
  );
}

function Person({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const p = useFetch<Picture>(`/payroll/personnel/${id}/`);
  const done = () => { p.reload(); onChanged(); };
  const d = p.data;
  if (!d) return <ErrorNotice error={p.error} />;
  const base = `/payroll/personnel/${id}`;
  return (
    <div className="card">
      <ErrorNotice error={p.error} />
      <div className="stat"><span>{t("pdec.profile")}</span><b>{d.salary_profile ? `${d.salary_profile.base_amount} ${d.salary_profile.currency}` : t("pdec.noProfile")}</b></div>
      {d.salary_profile && <p className="muted">{t("pay.effectiveFrom")} {d.salary_profile.effective_from}</p>}
      {can("payroll.review") && <RecordDecision base={base} onDone={done} />}
      <h3>{t("pdec.decisions")}</h3>
      {d.pay_decisions.length === 0 && <p className="muted">{t("pdec.noDecisions")}</p>}
      <ul className="list">{d.pay_decisions.map((x) => (
        <li key={x.id} className="item">
          <div className="stat"><span>{t(`pdec.kind.${x.kind}` as Key)} · {x.effective_date}</span><b>{x.deduction_percent ? `${x.deduction_percent}%` : t("pdec.noDeduction")}</b></div>
          <div className="row"><Chip tone={tone(x.state)}>{t(`pdec.state.${x.state}` as Key)}</Chip><span className="muted">{t("pdec.statusThen")}: {t(`pdec.pstatus.${x.status_at_decision}` as Key)} · {x.recorded_by}{x.decided_by ? ` → ${x.decided_by}` : ""}</span></div>
          <p className="muted">{x.reason}</p>
          {x.decision_text && <p className="muted">{x.decision_text}</p>}
          {x.supporting_ref && <p className="muted">{t("surv.supportingRef")}: {x.supporting_ref}</p>}
          {x.decision_note && <p className="muted">{x.decision_note}</p>}
          {x.state === "recorded" && can("payroll.decide") && <div className="row" style={{ flexWrap: "wrap" }}>
            <Act title={t("surv.approve")} path={`${base}/decisions/${x.id}/decide/`} extra={{ approve: true }} fields={[{ key: "comment", label: t("surv.comment"), required: false }]} onDone={done} submitLabel={t("surv.approve")} />
            <Act title={t("surv.reject")} path={`${base}/decisions/${x.id}/decide/`} extra={{ approve: false }} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("surv.reject")} /></div>}
        </li>
      ))}</ul>
      <h3>{t("pdec.recentPay")}</h3>
      <ul className="list">{d.lines.slice(0, 12).map((l) => (
        <li key={l.id} className="muted">{l.period} · {l.kind !== "regular" ? `${t(`pay.lkind.${l.kind}` as Key)} · ` : ""}{l.approved_net ?? l.calculated_net} · {t("pay.paid")} {l.paid}{l.status_flag ? ` · ${t("pdec.flagged")}` : ""}</li>
      ))}</ul>
      {d.unpaid_approved_lines.length > 0 && <>
        <h3>{t("pdec.unpaid")}</h3>
        <ul className="list">{d.unpaid_approved_lines.map((l) => <li key={l.line} className="muted">{l.period} · {l.outstanding}</li>)}</ul>
        <p className="muted">{t("pdec.unpaidNote")}</p></>}
      {d.arrears_claims.length > 0 && <>
        <h3>{t("arr.title")}</h3>
        <ul className="list">{d.arrears_claims.map((c) => <li key={c.id} className="muted">{c.periods.join(", ")} · {c.amount} {c.currency} · {t(`arr.status.${c.status}` as Key)}</li>)}</ul></>}
    </div>
  );
}

function RecordDecision({ base, onDone }: { base: string; onDone: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("retain_existing");
  const [reason, setReason] = useState("");
  const [eff, setEff] = useState("");
  const [text, setText] = useState("");
  const [ref, setRef] = useState("");
  const [pct, setPct] = useState("0");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const policy = useFetch<{ results: { key: string; value: string }[] }>(open ? "/payroll/policy/" : null);
  if (!open) return <div className="row"><button type="button" onClick={() => setOpen(true)}>{t("pdec.record")}</button></div>;
  const raw = policy.data?.results.find((x) => x.key === "suspended_jailed_deduction_tiers")?.value ?? "5,10,20";
  const tiers = [...new Set(raw.split(",").map((x) => Number(x.trim())).filter((n) => Number.isInteger(n) && n > 0 && n < 100))].sort((a, b) => a - b);
  const formal = kind === "formal_decision";
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(null); setBusy(true);
    const body: Record<string, unknown> = { kind, reason, effective_date: eff };
    if (formal) { body.decision_text = text; body.supporting_ref = ref; body.deduction_percent = Number(pct); }
    try { await api(`${base}/decisions/`, { method: "POST", body }); setOpen(false); setReason(""); setEff(""); setText(""); setRef(""); setPct("0"); setKind("retain_existing"); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("pdec.record")}</h3>
      <ErrorNotice error={err ?? policy.error} />
      <Notice>{t("pdec.deductionRule")}</Notice>
      <Field label={t("pdec.kindLabel")}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>{(["retain_existing", "formal_decision"] as const).map((k) => <option key={k} value={k}>{t(`pdec.kind.${k}` as Key)}</option>)}</select></Field>
      <Field label={t("surv.reason")}><input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <Field label={t("surv.effectiveDate")}><input type="date" required value={eff} onChange={(e) => setEff(e.target.value)} /></Field>
      {formal && <>
        <Field label={t("pdec.text")}><input required maxLength={500} value={text} onChange={(e) => setText(e.target.value)} /></Field>
        <Field label={t("surv.supportingRef")}><input required maxLength={200} value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
        <Field label={t("pdec.deduction")}>
          <select value={pct} onChange={(e) => setPct(e.target.value)}><option value="0">{t("pdec.noDeduction")}</option>{tiers.map((n) => <option key={n} value={n}>{n}%</option>)}</select></Field></>}
      <div className="row"><button type="submit" disabled={busy}>{t("pdec.record")}</button><button type="button" className="secondary" onClick={() => setOpen(false)}>{t("common.cancel")}</button></div>
    </form>
  );
}
