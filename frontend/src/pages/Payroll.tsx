import { useState } from "react";
import { api } from "../api/client";
import { Act } from "../components/ActionForm";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { Arrears } from "./PayrollArrears";
import { Decisions } from "./PayrollDecisions";
import { Payments } from "./PayrollPayments";

interface Summary { awaiting_approval: number; profiles_pending: number; serving_total: number; serving_with_approved_profile: number; serving_missing_profile: number; arrears_awaiting_decision?: number; pay_decisions_awaiting_approval?: number; runs_by_status: Record<string, number> }
interface RunRow { id: string; year: number; month: number; kind: string; status: string; prepared_by: string; exceptions: Exception[] }
interface Exception { personnel: string; service_number: string; code: string; severity: string }
interface Line { id: string; service_number: string | null; kind: string; reason: string; currency: string; gross: string; deductions: string; calculated_net: string; approved_net: string | null; paid: string; status_flag: string; status_flag_note: string; death_month: boolean }
interface RunFull extends RunRow { lines: Line[]; actions: { action: string; actor: string; comment: string; at: string }[] }
interface Profile { id: string; personnel_name: string; service_number: string | null; base_amount: string; currency: string; effective_from: string; authority_ref: string; status: string; created_by: string; decided_by: string | null; decision_note: string }
interface Scale { id: string; code: string; name: string; base_amount: string; currency: string }
interface Person { id: string; full_name: string; service_number: string | null; status: string }

const tone = (s: string) => (["approved", "paid"].includes(s) ? "approved" : ["rejected", "cancelled"].includes(s) ? "bad" : "draft");
const ym = (y: number, m: number) => `${y}-${String(m).padStart(2, "0")}`;

export function Payroll() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"runs" | "profiles" | "payments" | "arrears" | "decisions">("runs");
  const sum = useFetch<Summary>("/payroll/runs/summary/");
  return (
    <>
      <h1>{t("pay.title")}</h1>
      <ErrorNotice error={sum.error} />
      {sum.data && (
        <section className="card">
          <div className="stat"><span>{t("pay.awaitingApproval")}</span><b>{sum.data.awaiting_approval}</b></div>
          <div className="stat"><span>{t("pay.profilesPending")}</span><b>{sum.data.profiles_pending}</b></div>
          <div className="stat"><span>{t("pay.missingProfile")}</span><b>{sum.data.serving_missing_profile} / {sum.data.serving_total}</b></div>
          <div className="stat"><span>{t("pay.arrearsWaiting")}</span><b>{sum.data.arrears_awaiting_decision ?? 0}</b></div>
          <div className="stat"><span>{t("pay.decisionsWaiting")}</span><b>{sum.data.pay_decisions_awaiting_approval ?? 0}</b></div>
        </section>
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        {(["runs", "profiles", "payments", "arrears", "decisions"] as const).map((k) => (
          <button key={k} type="button" className={tab === k ? "" : "secondary"} onClick={() => setTab(k)}>{t(`pay.tab.${k}` as Key)}</button>
        ))}
      </div>
      {tab === "runs" ? <Runs onChanged={sum.reload} /> : tab === "profiles" ? <Profiles onChanged={sum.reload} />
        : tab === "payments" ? <Payments onChanged={sum.reload} /> : tab === "arrears" ? <Arrears onChanged={sum.reload} /> : <Decisions onChanged={sum.reload} />}
    </>
  );
}

function Runs({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const runs = useFetch<{ results: RunRow[] }>("/payroll/runs/");
  const [openId, setOpenId] = useState<string | null>(null);
  const done = () => { runs.reload(); onChanged(); };
  const now = new Date();
  return (
    <>
      <ErrorNotice error={runs.error} />
      {can("payroll.manage") && <Act title={t("pay.prepare")} path="/payroll/runs/prepare/" onDone={done} submitLabel={t("pay.prepare")}
        fields={[{ key: "year", label: t("pay.year"), type: "int" }, { key: "month", label: t("pay.month"), type: "int" }]} extra={{ year: now.getFullYear(), month: now.getMonth() + 1 }} />}
      {runs.data && runs.data.results.length === 0 && <p className="muted">{t("pay.noRuns")}</p>}
      <ul className="list">
        {(runs.data?.results ?? []).map((r) => (
          <li key={r.id} className="item">
            <button type="button" className="secondary" onClick={() => setOpenId(openId === r.id ? null : r.id)}><b>{ym(r.year, r.month)}</b> · {t(`pay.kind.${r.kind}` as Key)}</button>
            <div className="row"><Chip tone={tone(r.status)}>{t(`pay.rstatus.${r.status}` as Key)}</Chip><span className="muted">{t("pay.preparedBy")} {r.prepared_by}</span></div>
            {openId === r.id && <RunDetail id={r.id} onChanged={done} />}
          </li>
        ))}
      </ul>
    </>
  );
}

function RunDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { t, tr } = useI18n();
  const { can } = useAuth();
  const r = useFetch<RunFull>(`/payroll/runs/${id}/`);
  const d = r.data;
  const done = () => { r.reload(); onChanged(); };
  if (!d) return <ErrorNotice error={r.error} />;
  const base = `/payroll/runs/${id}`;
  const manage = can("payroll.manage"), approve = can("payroll.approve");
  const excluded = d.exceptions.filter((x) => x.severity === "excluded");
  const total = d.lines.reduce((s, l) => s + Number(l.approved_net ?? l.calculated_net), 0);
  return (
    <div className="card">
      <ErrorNotice error={r.error} />
      <div className="stat"><span>{t("pay.lines")}</span><b>{d.lines.length}</b></div>
      <div className="stat"><span>{t("pay.total")}</span><b>{total.toFixed(2)}</b></div>
      {excluded.length > 0 && <Notice kind="error">{t("pay.excluded", { n: excluded.length })}</Notice>}
      <ul className="list">
        {d.exceptions.map((x, i) => <li key={i} className="muted">{x.service_number || x.personnel.slice(0, 8)}: {tr(`pay.exc.${x.code}`) ?? x.code}</li>)}
      </ul>
      <h3>{t("pay.lines")}</h3>
      <ul className="list">
        {d.lines.slice(0, 300).map((l) => (
          <li key={l.id} className="item">
            <div className="stat"><span>{l.service_number ?? "—"} {l.kind !== "regular" ? `· ${t(`pay.lkind.${l.kind}` as Key)}` : ""}</span><b>{l.approved_net ?? l.calculated_net} {l.currency}</b></div>
            <p className="muted">{t("pay.gross")} {l.gross} · {t("pay.deductions")} {l.deductions} · {t("pay.paid")} {l.paid}{l.death_month ? ` · ${t("pay.deathMonth")}` : ""}{l.reason ? ` · ${l.reason}` : ""}</p>
            {l.status_flag && <p className="muted">{l.status_flag_note}</p>}
            {manage && l.kind === "regular" && ["approved", "paid"].includes(d.status) && <Act title={t("pay.adjust")} path="/payroll/runs/adjust/" extra={{ line: l.id }} onDone={done} submitLabel={t("pay.adjust")}
              fields={[{ key: "kind", label: t("pay.adjustKind"), options: [["reversal", t("pay.reversal")], ["adjustment", t("pay.adjustment")]] }, { key: "amount", label: t("pay.adjustAmount"), type: "number", required: false }, { key: "reason", label: t("surv.reason") }]} />}
          </li>
        ))}
      </ul>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {manage && d.status === "prepared" && <>
          <Act title={t("pay.prepareAgain")} path="/payroll/runs/prepare/" extra={{ year: d.year, month: d.month }} fields={[]} onDone={done} submitLabel={t("pay.prepareAgain")} />
          <Act title={t("pay.submit")} path={`${base}/submit/`} fields={[]} onDone={done} submitLabel={t("pay.submit")} /></>}
        {manage && ["prepared", "submitted"].includes(d.status) && <Act title={t("pay.cancel")} path={`${base}/cancel/`} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("pay.cancel")} />}
        {approve && d.status === "submitted" && <>
          <Act title={t("surv.approve")} path={`${base}/approve/`} fields={[]} onDone={done} submitLabel={t("surv.approve")} />
          <Act title={t("pay.return")} path={`${base}/return/`} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("pay.return")} /></>}
      </div>
      <h3>{t("pay.history")}</h3>
      <ul className="list">{d.actions.map((a, i) => <li key={i} className="muted">{new Date(a.at).toLocaleString()} · {t(`pay.act.${a.action}` as Key)} · {a.actor}{a.comment ? ` · ${a.comment}` : ""}</li>)}</ul>
    </div>
  );
}

function Profiles({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [status, setStatus] = useState("pending");
  const list = useFetch<{ results: Profile[] }>("/payroll/profiles/", { status: status || undefined });
  const done = () => { list.reload(); onChanged(); };
  return (
    <>
      <ErrorNotice error={list.error} />
      {can("payroll.manage") && <ProposeProfile onDone={done} />}
      <Field label={t("pay.show")}>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {["pending", "approved", "rejected", ""].map((s) => <option key={s} value={s}>{s ? t(`pay.pstatus.${s}` as Key) : t("pay.all")}</option>)}
        </select>
      </Field>
      {list.data && list.data.results.length === 0 && <p className="muted">{t("pay.noProfiles")}</p>}
      <ul className="list">
        {(list.data?.results ?? []).map((p) => (
          <li key={p.id} className="item">
            <b>{p.personnel_name}</b> ({p.service_number ?? "—"})
            <div className="stat"><span>{t("pay.effectiveFrom")} {p.effective_from}</span><b>{p.base_amount} {p.currency}</b></div>
            <div className="row"><Chip tone={tone(p.status)}>{t(`pay.pstatus.${p.status}` as Key)}</Chip><span className="muted">{p.authority_ref} · {p.created_by}{p.decided_by ? ` → ${p.decided_by}` : ""}</span></div>
            {p.decision_note && <p className="muted">{p.decision_note}</p>}
            {can("payroll.approve") && p.status === "pending" && <div className="row">
              <Act title={t("surv.approve")} path={`/payroll/profiles/${p.id}/approve/`} fields={[{ key: "comment", label: t("surv.comment"), required: false }]} onDone={done} submitLabel={t("surv.approve")} />
              <Act title={t("surv.reject")} path={`/payroll/profiles/${p.id}/reject/`} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("surv.reject")} /></div>}
          </li>
        ))}
      </ul>
    </>
  );
}

function ProposeProfile({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [person, setPerson] = useState<Person | null>(null);
  const [scale, setScale] = useState("");
  const [base, setBase] = useState("");
  const [currency, setCurrency] = useState("");
  const [eff, setEff] = useState("");
  const [ref, setRef] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const found = useFetch<{ results: Person[] }>(open && !person && q.trim().length >= 2 ? "/payroll/profiles/people/" : null, { q: q.trim() });
  const scales = useFetch<{ results: Scale[] }>(open ? "/payroll/profiles/scales/" : null);
  if (!open) return <button type="button" onClick={() => setOpen(true)}>{t("pay.propose")}</button>;
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(null);
    try {
      await api("/payroll/profiles/", { method: "POST", body: { personnel: person?.id, effective_from: eff, authority_ref: ref, ...(scale ? { scale } : { base_amount: base, currency }) } });
      setOpen(false); setPerson(null); setQ(""); onDone();
    } catch (x) { setErr(x); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("pay.propose")}</h3>
      <ErrorNotice error={err ?? found.error ?? scales.error} />
      {person
        ? <p><b>{person.full_name}</b> ({person.service_number ?? "—"}) <button type="button" className="secondary" onClick={() => setPerson(null)}>{t("pay.change")}</button></p>
        : <>
          <Field label={t("pay.findPerson")}><input value={q} maxLength={60} onChange={(e) => setQ(e.target.value)} /></Field>
          <ul className="list">{(found.data?.results ?? []).map((p) => <li key={p.id} className="item"><button type="button" className="secondary" onClick={() => setPerson(p)}>{p.full_name} ({p.service_number ?? "—"})</button></li>)}</ul></>}
      <Field label={t("pay.scale")}>
        <select value={scale} onChange={(e) => setScale(e.target.value)}><option value="">{t("pay.typeAmount")}</option>
          {(scales.data?.results ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}: {s.base_amount} {s.currency}</option>)}</select>
      </Field>
      {!scale && <>
        <Field label={t("pay.baseAmount")}><input type="number" step="0.01" min="0" required value={base} onChange={(e) => setBase(e.target.value)} /></Field>
        <Field label={t("surv.currency")}><input value={currency} required maxLength={3} onChange={(e) => setCurrency(e.target.value)} /></Field></>}
      <Field label={t("pay.effectiveFrom")}><input type="date" required value={eff} onChange={(e) => setEff(e.target.value)} /></Field>
      <Field label={t("pay.authorityRef")}><input value={ref} required maxLength={200} onChange={(e) => setRef(e.target.value)} /></Field>
      <div className="row"><button type="submit" disabled={!person}>{t("pay.propose")}</button><button type="button" className="secondary" onClick={() => setOpen(false)}>{t("common.cancel")}</button></div>
    </form>
  );
}
