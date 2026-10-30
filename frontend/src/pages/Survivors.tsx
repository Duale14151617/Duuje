import { useState } from "react";
import { api } from "../api/client";
import { Act } from "../components/ActionForm";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";

interface Decision { id: string; allocation: string; kind: string; state: string; reason: string; effective_date: string; supporting_ref: string; previous_amount: string | null; new_amount: string | null; proposed_by: string; decided_by: string }
interface Allocation { id: string; amount: string; currency: string; status: string; basis_ref: string; basis_kind: string; effective_from: string | null; held_from: string | null; ended_on: string | null; paid_total: string; decisions: Decision[] }
interface Beneficiary { id: string; full_name: string; relationship: string; tier: number; state: string; identity_ref: string; evidence_ref: string; decision_note: string; allocations: Allocation[] }
interface CaseRow { id: string; personnel_name: string; service_number: string | null; date_of_death: string; status: string }
interface CaseFull extends CaseRow { outstanding_review: string; dispute_note: string; eligible_tier: number | null; closure_reason: string; beneficiaries: Beneficiary[] }
interface Deceased { personnel: string; full_name: string; service_number: string | null; date_of_death: string }

const tone = (s: string) => (["verified", "authorized", "approved"].includes(s) ? "approved" : ["rejected", "disputed", "terminated", "cancelled"].includes(s) ? "bad" : "draft");

export function Survivors() {
  const { t } = useI18n();
  const { can } = useAuth();
  const list = useFetch<{ results: CaseRow[] }>("/survivor-cases/");
  const [openId, setOpenId] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  return (
    <>
      <h1>{t("surv.title")}</h1>
      <p className="muted">{t("surv.indefinite")}</p>
      <ErrorNotice error={list.error} />
      {can("survivor.manage") && !opening && <div className="row"><button type="button" onClick={() => setOpening(true)}>{t("surv.openCase")}</button></div>}
      {opening && <OpenCase onDone={() => { setOpening(false); list.reload(); }} onCancel={() => setOpening(false)} />}
      {list.data && list.data.results.length === 0 && <p className="muted">{t("surv.none")}</p>}
      <ul className="list">
        {(list.data?.results ?? []).map((c) => (
          <li key={c.id} className="item">
            <button type="button" className="secondary" onClick={() => setOpenId(openId === c.id ? null : c.id)}>
              <b>{c.personnel_name}</b> ({c.service_number ?? "—"})
            </button>
            <div className="row"><Chip tone={tone(c.status)}>{t(`surv.status.${c.status}` as Key)}</Chip><span className="muted">{t("surv.died")}: {c.date_of_death}</span></div>
            {openId === c.id && <CaseDetail id={c.id} onChanged={list.reload} />}
          </li>
        ))}
      </ul>
    </>
  );
}

function OpenCase({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { t } = useI18n();
  const d = useFetch<{ results: Deceased[] }>("/survivor-cases/deceased/");
  const [err, setErr] = useState<unknown>(null);
  async function open(id: string) {
    setErr(null);
    try { await api("/survivor-cases/", { method: "POST", body: { personnel: id } }); onDone(); } catch (x) { setErr(x); }
  }
  return (
    <section className="card">
      <h3>{t("surv.pickDeceased")}</h3>
      <ErrorNotice error={err ?? d.error} />
      {d.data && d.data.results.length === 0 && <p className="muted">{t("surv.noDeceased")}</p>}
      <ul className="list">{(d.data?.results ?? []).map((p) => (
        <li key={p.personnel} className="item"><b>{p.full_name}</b> ({p.service_number ?? "—"}) · {p.date_of_death}
          <div className="row"><button type="button" onClick={() => void open(p.personnel)}>{t("surv.openCase")}</button></div></li>
      ))}</ul>
      <div className="row"><button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button></div>
    </section>
  );
}

function CaseDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const c = useFetch<CaseFull>(`/survivor-cases/${id}/`);
  const done = () => { c.reload(); onChanged(); };
  const base = `/survivor-cases/${id}`;
  const d = c.data;
  if (!d) return <ErrorNotice error={c.error} />;
  const live = d.status !== "closed";
  const manage = can("survivor.manage") && live, verify = can("survivor.verify") && live, approve = can("survivor.approve") && live;
  const rel = (["wife", "child", "parent", "sibling"] as const).map((r) => [r, t(`surv.rel.${r}` as Key)] as [string, string]);
  const allAllocs = d.beneficiaries.flatMap((b) => b.allocations.map((a) => ({ b, a })));
  return (
    <div className="card">
      <ErrorNotice error={c.error} />
      {d.eligible_tier && <Notice>{t("surv.eligibleTier")}: {t(`surv.tier.${d.eligible_tier}` as Key)}</Notice>}
      {d.status === "disputed" && <Notice kind="error">{t("surv.disputed")}: {d.dispute_note}</Notice>}
      {d.outstanding_review && <p className="muted">{t("surv.outstanding")}: {d.outstanding_review}</p>}
      {d.status === "closed" && <p className="muted">{t("surv.closedBecause")}: {d.closure_reason}</p>}
      <h3>{t("surv.beneficiaries")}</h3>
      {d.beneficiaries.length === 0 && <p className="muted">{t("surv.noBeneficiaries")}</p>}
      <ul className="list">
        {d.beneficiaries.map((b) => (
          <li key={b.id} className="item">
            <b>{b.full_name}</b> · {t(`surv.rel.${b.relationship}` as Key)}
            <div className="row"><Chip tone={tone(b.state)}>{t(`surv.bstate.${b.state}` as Key)}</Chip><span className="muted">{b.identity_ref} · {b.evidence_ref}</span></div>
            {b.decision_note && <p className="muted">{b.decision_note}</p>}
            {b.allocations.map((a) => (
              <div key={a.id} className="card">
                <div className="stat"><span>{t(a.basis_kind === "lump_sum" ? "surv.lumpSum" : "surv.perPeriod")}</span><b>{a.amount} {a.currency}</b></div>
                <div className="row"><Chip tone={tone(a.status)}>{t(`surv.astatus.${a.status}` as Key)}</Chip>
                  <span className="muted">{a.effective_from ? `${t("surv.effectiveFrom")} ${a.effective_from}` : ""}{a.held_from ? ` · ${t("surv.heldFrom")} ${a.held_from}` : ""}{a.ended_on ? ` · ${t("surv.endedOn")} ${a.ended_on}` : ""}</span></div>
                <p className="muted">{a.basis_ref} · {t("surv.paid")} {a.paid_total}</p>
                {a.decisions.map((x) => (
                  <p key={x.id} className="muted">{t(`surv.dkind.${x.kind}` as Key)} · {t(`surv.dstate.${x.state}` as Key)} · {x.effective_date} · {x.reason} ({x.supporting_ref}){x.new_amount ? ` → ${x.new_amount}` : ""}
                    {approve && x.state === "proposed" && <>
                      {" "}<Act title={t("surv.approve")} path={`${base}/decision/${x.id}/decide/`} extra={{ approve: true }} fields={[{ key: "comment", label: t("surv.comment"), required: false }]} onDone={done} submitLabel={t("surv.approve")} />
                      {" "}<Act title={t("surv.reject")} path={`${base}/decision/${x.id}/decide/`} extra={{ approve: false }} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("surv.reject")} /></>}
                  </p>
                ))}
                {approve && a.status === "proposed" && <Act title={t("surv.authorize")} path={`${base}/authorize/`} extra={{ allocation: a.id }} fields={[]} onDone={done} submitLabel={t("surv.authorize")} />}
              </div>
            ))}
            {verify && b.state === "pending" && <div className="row">
              <Act title={t("surv.verifyBeneficiary")} path={`${base}/beneficiary/${b.id}/decide/`} extra={{ verify: true }} fields={[{ key: "comment", label: t("surv.comment"), required: false }]} onDone={done} submitLabel={t("surv.verifyBeneficiary")} />
              <Act title={t("surv.reject")} path={`${base}/beneficiary/${b.id}/decide/`} extra={{ verify: false }} fields={[{ key: "comment", label: t("surv.comment") }]} onDone={done} submitLabel={t("surv.reject")} /></div>}
          </li>
        ))}
      </ul>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {manage && <Act title={t("surv.addBeneficiary")} path={`${base}/beneficiary/`} onDone={done} submitLabel={t("surv.addBeneficiary")}
          fields={[{ key: "full_name", label: t("surv.fullName") }, { key: "relationship", label: t("surv.relationship"), options: rel }, { key: "identity_ref", label: t("surv.identityRef") },
                   { key: "evidence_ref", label: t("surv.evidenceRef") }, { key: "payment_details", label: t("surv.paymentDetails"), required: false }]} />}
        {manage && d.beneficiaries.length > 0 && <Act title={t("surv.proposeAllocation")} path={`${base}/propose/`} onDone={done} submitLabel={t("surv.proposeAllocation")}
          fields={[{ key: "beneficiary", label: t("surv.beneficiary"), options: d.beneficiaries.filter((b) => b.state === "verified").map((b) => [b.id, b.full_name] as [string, string]) },
                   { key: "amount", label: t("surv.amount"), type: "number" }, { key: "currency", label: t("surv.currency") },
                   { key: "basis_kind", label: t("surv.basisKind"), options: [["per_period", t("surv.perPeriod")], ["lump_sum", t("surv.lumpSum")]] },
                   { key: "basis_ref", label: t("surv.basisRef") }, { key: "effective_from", label: t("surv.effectiveFrom"), type: "date", required: false }]} />}
        {manage && allAllocs.some(({ a }) => a.status === "authorized" || a.status === "suspended") && <Act title={t("surv.proposeDecision")} path={`${base}/decision/`} onDone={done} submitLabel={t("surv.proposeDecision")}
          fields={[{ key: "allocation", label: t("surv.allocation"), options: allAllocs.filter(({ a }) => a.status === "authorized" || a.status === "suspended").map(({ b, a }) => [a.id, `${b.full_name}: ${a.amount} ${a.currency}`] as [string, string]) },
                   { key: "kind", label: t("surv.decision"), options: (["change_amount", "suspend", "resume", "terminate"] as const).map((k) => [k, t(`surv.dkind.${k}` as Key)] as [string, string]) },
                   { key: "new_amount", label: t("surv.newAmount"), type: "number", required: false }, { key: "reason", label: t("surv.reason") },
                   { key: "effective_date", label: t("surv.effectiveDate"), type: "date" }, { key: "supporting_ref", label: t("surv.supportingRef") }]} />}
        {manage && <Act title={d.status === "disputed" ? t("surv.clearDispute") : t("surv.raiseDispute")} path={`${base}/dispute/`} extra={{ disputed: d.status !== "disputed" }} onDone={done}
          fields={[{ key: "comment", label: t("surv.comment") }]} submitLabel={t("surv.save")} />}
        {verify && d.status === "open" && <Act title={t("surv.markVerified")} path={`${base}/verify/`} onDone={done} submitLabel={t("surv.markVerified")} fields={[{ key: "outstanding_review", label: t("surv.outstanding") }]} />}
        {approve && <Act title={t("surv.closeCase")} path={`${base}/close/`} onDone={done} submitLabel={t("surv.closeCase")}
          fields={[{ key: "reason", label: t("surv.reason") }, { key: "effective_date", label: t("surv.effectiveDate"), type: "date" }, { key: "supporting_ref", label: t("surv.supportingRef") }]} />}
      </div>
    </div>
  );
}
