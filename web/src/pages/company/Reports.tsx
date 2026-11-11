import { useState } from "react";
import { useLoad } from "../../hooks";

const pct = (n: number | null | undefined) => (n == null ? "–" : `${Math.round(n * 100)}%`);

export default function Reports({ companyId }: { companyId: string }) {
  const [days, setDays] = useState(30);
  const since = new Date(Date.now() - days * 86400000).toISOString();
  const q = `?since=${encodeURIComponent(since)}`;
  const jobs = useLoad<any>(`/companies/${companyId}/reports/jobs${q}`);
  const techs = useLoad<any>(`/companies/${companyId}/reports/technicians${q}`);
  const fin = useLoad<any>(`/companies/${companyId}/reports/finance${q}`);   // finance.read only; other roles see the reason

  return (
    <>
      <div className="row"><label>Period <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select></label></div>
      {jobs.error && <div className="error">{jobs.error}</div>}
      {jobs.data && (
        <div className="card">
          <h2>Jobs</h2>
          <p><b>{jobs.data.total}</b> created · <b>{jobs.data.completed}</b> completed · cancellation rate <b>{pct(jobs.data.cancellationRate)}</b> · offer acceptance <b>{pct(jobs.data.offers.acceptanceRate)}</b> · average time to complete <b>{jobs.data.avgHoursToComplete ?? "–"} h</b></p>
          <p>{Object.entries(jobs.data.byStatus).map(([s, n]) => `${s}: ${n}`).join(" · ") || "No jobs in this period."}</p>
          <p className="muted">Complaints {jobs.data.complaints.total} ({jobs.data.complaints.open} open) · callbacks {jobs.data.callbacks}</p>
        </div>)}
      {techs.data && (
        <div className="card">
          <h2>Technicians</h2>
          <table><thead><tr><th>Name</th><th>Type</th><th>Offered</th><th>Accepted</th><th>Declined</th><th>Completed</th><th>Utilization</th></tr></thead><tbody>
            {techs.data.technicians.map((t: any) => <tr key={t.technicianId}><td>{t.name}</td><td>{t.relationship}</td><td>{t.offered}</td><td>{t.accepted}</td><td>{t.declined}</td><td>{t.completed}</td><td>{pct(t.utilization)} <span className="muted">({t.scheduledHours}/{t.availableHours} h)</span></td></tr>)}
          </tbody></table>
        </div>)}
      {fin.data && fin.data.currencies.map((c: any) => (
        <div className="card" key={c.currency}>
          <h2>Finance · {c.currency}</h2>
          <p>Invoiced <b>{c.receivables.invoiced}</b> · collected <b>{c.receivables.collected}</b> · outstanding <b>{c.receivables.outstanding}</b> · pending collections {c.receivables.pendingCollections}</p>
          <p>Technician payables accrued <b>{c.technicianPayables.accrued}</b> · paid <b>{c.technicianPayables.paid}</b> · outstanding <b>{c.technicianPayables.outstanding}</b></p>
          <p>Direct customer payments agreed <b>{c.directPayments.agreed}</b> · confirmed {c.directPayments.confirmed} (self-reported, unverified {c.directPayments.selfReportedUnverified})</p>
          <p>Refunds requested {c.refunds.requested} · approved {c.refunds.approved} · paid {c.refunds.paid} · disputed {c.disputed.amount} · platform fees accrued {c.platformFees.accrued}, settled {c.platformFees.settled}, waived {c.platformFees.waived}</p>
          <p className="muted">Payments by status: {Object.entries(c.paymentsByStatus).map(([s, v]: any) => `${s} ${v.count} (${v.amount})`).join(" · ") || "none"} · unreconciled {c.unreconciled.count} ({c.unreconciled.amount})</p>
        </div>))}
      {fin.error && <p className="muted">Finance figures: {fin.error}</p>}
    </>
  );
}
