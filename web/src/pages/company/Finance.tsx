import { useState } from "react";
import { post } from "../../api";
import { Msg, Status, useAction, useLoad, when } from "../../hooks";

const money = (n: number, c: string) => `${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })} ${c}`;

// Finance officers and owners. The server decides what each person may do (separation of duties included);
// buttons that the server refuses just show its reason.
export default function Finance({ companyId }: { companyId: string }) {
  const base = `/companies/${companyId}`;
  const payables = useLoad<any[]>(`${base}/payables`);
  const invoices = useLoad<any[]>(`${base}/invoices`);
  const payments = useLoad<any[]>(`${base}/payments`);
  const refunds = useLoad<any[]>(`${base}/refunds`);
  const rec = useLoad<any>(`${base}/finance/reconciliation`);
  const a = useAction();
  const [amount, setAmount] = useState<Record<string, string>>({});
  const refresh = () => { payables.reload(); invoices.reload(); payments.reload(); refunds.reload(); rec.reload(); };
  const act = async (fn: () => Promise<unknown>, ok: string) => { if (await a.run(fn, ok)) refresh(); };

  const forbidden = payables.error.includes("Forbidden") || payables.error.includes("403");
  if (payables.error && forbidden) return <p className="muted">Your role does not include finance access.</p>;

  return (
    <>
      <Msg error={a.error || payables.error} notice={a.notice} />
      <div className="card">
        <h2>Technician payables</h2>
        {payables.data?.length === 0 && <p className="muted">None yet. They appear when a job with approved financial terms is completed.</p>}
        <table><tbody>{payables.data?.map((p) => (
          <tr key={p.id}>
            <td>{p.jobReference}<div className="muted">{p.technician}</div></td>
            <td>{money(p.amount, p.currency)}<div className="muted">{p.payerType === "customer" ? "customer pays directly" : "company pays"}</div></td>
            <td><Status value={p.settlement} />{p.disputed && <> <Status value="Disputed" /></>}</td>
            <td>
              {p.payerType === "company" && p.status === "Accrued" && <button className="ghost" onClick={() => act(() => post(`${base}/payables/${p.id}/approve`), "Payable approved.")}>Approve</button>}
              {p.payerType === "company" && p.status === "Approved" && p.outstanding > 0 && !p.disputed && (
                <span className="row">
                  <input style={{ width: 90 }} placeholder={String(p.outstanding)} value={amount[p.id] ?? ""} onChange={(e) => setAmount({ ...amount, [p.id]: e.target.value })} />
                  <button className="ghost" onClick={() => act(() => post(`${base}/payments`, { payableId: p.id, method: prompt("Method: cash, bank, mobile_money or other", "bank"), amount: Number(amount[p.id] || p.outstanding), providerRef: prompt("Bank/provider reference (optional)") || undefined }), "Payment initiated. Someone else must confirm it.")}>Pay</button>
                </span>)}
            </td>
          </tr>))}</tbody></table>
      </div>

      <div className="card">
        <h2>Payments</h2>
        <table><tbody>{payments.data?.map((p) => (
          <tr key={p.id}>
            <td>{p.reference}<div className="muted">{p.kind.replaceAll("_", " ")} · {p.method}</div></td>
            <td>{money(p.amount, p.currency)}</td>
            <td><Status value={p.status} />{p.status === "Confirmed" && <div className="muted">{p.verified ? "provider-verified" : "self-reported"}{p.reconciled ? " · reconciled" : ""}</div>}</td>
            <td>
              {p.status === "Initiated" && <>
                <button className="ghost" onClick={() => act(() => post(`${base}/payments/${p.id}/confirm`, p.method === "cash" ? { acknowledgedBy: prompt("Who acknowledged the cash?") } : { providerRef: p.providerRef || prompt("Provider/bank reference?") }), "Confirmed.")}>Confirm</button>
                <button className="ghost" onClick={() => act(() => post(`${base}/payments/${p.id}/fail`, { note: prompt("Why did it fail?") }), "Marked failed.")}>Failed</button></>}
              {p.status === "Confirmed" && !p.reconciled && <button className="ghost" onClick={() => act(() => post(`${base}/payments/${p.id}/reconcile`, { note: prompt("Reconciliation note (optional)") || undefined }), "Reconciled.")}>Reconcile</button>}
              {p.status === "Confirmed" && <button className="ghost" onClick={() => act(() => post(`${base}/payments/${p.id}/reverse`, { reason: prompt("Reason for reversal?") }), "Reversed.")}>Reverse</button>}
            </td>
          </tr>))}</tbody></table>
      </div>

      <div className="card">
        <h2>Invoices</h2>
        {invoices.data?.length === 0 && <p className="muted">Issue an invoice from a completed job that has approved terms.</p>}
        <table><tbody>{invoices.data?.map((i) => (
          <tr key={i.id}>
            <td>{i.number}</td><td>{money(i.total, i.currency)}</td>
            <td><Status value={i.status === "Void" ? "Void" : i.settlement} /><div className="muted">outstanding {money(i.outstanding, i.currency)}</div></td>
            <td>{i.status === "Issued" && <>
              <button className="ghost" onClick={() => act(() => post(`${base}/payments`, { invoiceId: i.id, method: prompt("Method: cash, bank, mobile_money or other", "cash"), amount: Number(prompt("Amount", String(i.outstanding))) }), "Collection recorded. Someone else must confirm it.")}>Collect</button>
              <button className="ghost" onClick={() => act(() => post(`${base}/refunds`, { invoiceId: i.id, amount: Number(prompt("Refund amount?")), reason: prompt("Reason?") }), "Refund requested.")}>Refund</button></>}</td>
          </tr>))}</tbody></table>
      </div>

      <div className="card">
        <h2>Refunds</h2>
        {refunds.data?.length === 0 && <p className="muted">None.</p>}
        <table><tbody>{refunds.data?.map((r) => (
          <tr key={r.id}>
            <td>{money(r.amount, r.currency)}<div className="muted">{r.reason}</div></td><td><Status value={r.settlement} /></td><td>{when(r.requestedAt)}</td>
            <td>
              {r.status === "Requested" && <>
                <button className="ghost" onClick={() => act(() => post(`${base}/refunds/${r.id}/decision`, { decision: "approve" }), "Refund approved.")}>Approve</button>
                <button className="ghost" onClick={() => act(() => post(`${base}/refunds/${r.id}/decision`, { decision: "reject", note: prompt("Reason for rejecting?") }), "Refund rejected.")}>Reject</button></>}
              {r.status === "Approved" && r.paid < r.amount && <button className="ghost" onClick={() => act(() => post(`${base}/payments`, { refundId: r.id, method: prompt("Method", "cash"), amount: Number(r.amount - r.paid) }), "Refund payment initiated.")}>Pay refund</button>}
            </td>
          </tr>))}</tbody></table>
      </div>

      <div className="card">
        <h2>Reconciliation</h2>
        {rec.data && <>
          <p>Awaiting reconciliation: <b>{rec.data.awaitingReconciliation.length}</b> · self-reported (not independently verified): <b>{rec.data.selfReported.length}</b> · stuck initiated &gt;24h: <b>{rec.data.stuckInitiated.length}</b></p>
          <p className="muted">Ledger: {rec.data.balanceCheck.length === 0 ? "no entries yet" : rec.data.balanceCheck.map((b: any) => `${b.currency} ${b.balanced ? "balanced" : "OUT OF BALANCE"}`).join(", ")}</p>
          <table><thead><tr><th>Currency</th><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>
            {rec.data.trialBalance.map((t: any) => <tr key={t.currency + t.account}><td>{t.currency}</td><td>{t.account}</td><td>{t.debit}</td><td>{t.credit}</td></tr>)}
          </tbody></table></>}
      </div>
    </>
  );
}
