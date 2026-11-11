import { useState } from "react";
import { Link } from "react-router-dom";
import { post } from "../../api";
import { Msg, Status, useAction, useLoad, when } from "../../hooks";

function RatingBox({ companyId, jobId }: { companyId: string; jobId: string }) {
  const url = `/companies/${companyId}/jobs/${jobId}/rating`;
  const { data, error, reload } = useLoad<any>(url);
  const [stars, setStars] = useState(5); const [comment, setComment] = useState("");
  const a = useAction();
  if (error) return null;   // no permission to read ratings, or the job is not visible
  if (!data) return null;
  if (data.rated) return <div><h2>Rating</h2><div>{"★".repeat(data.stars)}{"☆".repeat(5 - data.stars)} {data.comment}</div></div>;
  return (
    <div>
      <h2>Rate the technician</h2>
      <div className="row">
        <label>Stars<select value={stars} onChange={(e) => setStars(Number(e.target.value))}>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        <label>Comment (optional)<input value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} /></label>
        <button className="primary" disabled={a.busy} onClick={async () => { if (await a.run(() => post(url, { stars, comment: comment || undefined }), "Rating saved.")) reload(); }}>Submit rating</button>
      </div>
      <Msg error={a.error} notice={a.notice} />
    </div>
  );
}

export default function Jobs({ companyId }: { companyId: string }) {
  const jobs = useLoad<any[]>(`/companies/${companyId}/jobs`);
  const customers = useLoad<any[]>(`/companies/${companyId}/customers`);
  const catalog = useLoad<any[]>("/catalog/trades");
  const [f, setF] = useState({ customerId: "", locationId: "", tradeId: "", description: "", priority: "Normal", start: "", end: "", skillIds: [] as string[] });
  const cust = useLoad<any>(f.customerId ? `/companies/${companyId}/customers/${f.customerId}` : null);
  const [open, setOpen] = useState<string | null>(null);
  const detail = useLoad<any>(open ? `/companies/${companyId}/jobs/${open}` : null);
  const cands = useLoad<any>(open ? `/companies/${companyId}/jobs/${open}/candidates?includeIneligible=true` : null);
  const a = useAction();
  const trade = catalog.data?.find((t) => t.id === f.tradeId);
  const refreshAll = () => { jobs.reload(); detail.reload(); cands.reload(); };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await a.run(() => post(`/companies/${companyId}/jobs`, {
      customerId: f.customerId, locationId: f.locationId, tradeId: f.tradeId, description: f.description, priority: f.priority,
      scheduledStart: new Date(f.start).toISOString(), scheduledEnd: new Date(f.end).toISOString(), requiredSkillIds: f.skillIds,
    }), "Job created.");
    if (ok) { setF({ ...f, description: "", skillIds: [] }); jobs.reload(); }
  };

  return (
    <>
      <div className="card">
        <table>
          <thead><tr><th>Reference</th><th>Status</th><th>Priority</th><th>Scheduled</th><th></th></tr></thead>
          <tbody>{jobs.data?.map((j) => (
            <tr key={j.id}><td>{j.reference}</td><td><Status value={j.status} /></td><td>{j.priority}</td><td>{when(j.scheduledStart)}</td>
              <td><button className="ghost" onClick={() => setOpen(open === j.id ? null : j.id)}>Dispatch</button></td></tr>))}</tbody>
        </table>
        {jobs.error && <div className="error">{jobs.error}</div>}
      </div>

      {open && detail.data && (
        <div className="card">
          <h2>{detail.data.reference}: {detail.data.description}</h2>
          <p>Status <Status value={detail.data.status} />. Recommendations are suggestions only; nothing is assigned until you send an offer.</p>
          {cands.data?.candidates?.length === 0 && <p className="muted">No candidates.</p>}
          <table>
            <thead><tr><th>Technician</th><th>Type</th><th>Score</th><th>Why</th><th></th></tr></thead>
            <tbody>{cands.data?.candidates?.map((c: any) => (
              <tr key={c.technicianId}><td>{c.name}</td><td>{c.relationshipType}</td><td>{c.eligible ? c.score : "—"}</td>
                <td>{(c.eligible ? c.reasons : c.blockers).map((r: string) => <div key={r} className={c.eligible ? "" : "muted"}>{r}</div>)}</td>
                <td>{c.eligible && ["Open", "Offered", "Accepted"].includes(detail.data.status) &&
                  <button className="primary" disabled={a.busy} onClick={async () => {
                    const path = detail.data.status === "Open" ? "offer" : "reassign";
                    const body = path === "offer" ? { technicianId: c.technicianId } : { technicianId: c.technicianId, reason: "Reassigned by dispatcher" };
                    if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/${path}`, body), "Offer sent.")) refreshAll();
                  }}>{detail.data.status === "Open" ? "Offer job" : "Reassign"}</button>}</td></tr>))}</tbody>
          </table>
          <h2>Assignments</h2>
          {detail.data.assignments.map((x: any) => <div key={x.id}>{x.technician} <Status value={x.status} /> <span className="muted">{when(x.offeredAt)} {x.reason}</span></div>)}
          <div className="row" style={{ marginTop: 10 }}>
            {["Offered"].includes(detail.data.status) && <button className="ghost" onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/withdraw`, { reason: "Withdrawn" }))) refreshAll(); }}>Withdraw offer</button>}
            {!["Cancelled", "Completed"].includes(detail.data.status) && <button className="danger" onClick={async () => { const reason = prompt("Reason for cancelling?"); if (reason && await a.run(() => post(`/companies/${companyId}/jobs/${open}/cancel`, { reason }))) refreshAll(); }}>Cancel job</button>}
          </div>
          {detail.data.status === "Completed" && <RatingBox companyId={companyId} jobId={open} />}
          <h2>History</h2>
          {detail.data.history.map((h: any, i: number) => <div key={i} className="muted">{when(h.at)}: {h.fromStatus ?? "—"} → {h.to} {h.reason}</div>)}
          <Msg error={a.error} notice={a.notice} />
        </div>
      )}

      <form className="card" onSubmit={create}>
        <h2>New job</h2>
        <div className="row">
          <label>Customer<select required value={f.customerId} onChange={(e) => setF({ ...f, customerId: e.target.value, locationId: "" })}><option value="">Select…</option>{customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label>Location<select required disabled={!f.customerId} value={f.locationId} onChange={(e) => setF({ ...f, locationId: e.target.value })}><option value="">{!f.customerId ? "Choose a customer first" : cust.data && cust.data.locations.length === 0 ? "No locations yet" : "Select…"}</option>{cust.data?.locations.map((l: any) => <option key={l.id} value={l.id}>{l.label}</option>)}</select></label>
          <label>Trade<select required value={f.tradeId} onChange={(e) => setF({ ...f, tradeId: e.target.value, skillIds: [] })}><option value="">Select…</option>{catalog.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label>Priority<select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{["Low", "Normal", "High", "Urgent"].map((p) => <option key={p}>{p}</option>)}</select></label>
        </div>
        {customers.data && customers.data.length === 0 && <p className="muted">There are no customers yet. <Link to={`/companies/${companyId}/customers`}>Add a customer</Link> first, then add a location for them.</p>}
        {f.customerId && cust.data && cust.data.locations.length === 0 && <p className="muted">This customer has no locations yet. <Link to={`/companies/${companyId}/customers`}>Open Customers</Link>, tap Locations, and add one (choose a service area such as Garowe).</p>}
        {trade && trade.skills.length > 0 && <div><label>Required skills</label>{trade.skills.map((s: any) => (
          <label key={s.id}><input type="checkbox" checked={f.skillIds.includes(s.id)} onChange={(e) => setF({ ...f, skillIds: e.target.checked ? [...f.skillIds, s.id] : f.skillIds.filter((x) => x !== s.id) })} /> {s.name}</label>))}</div>}
        <div className="row">
          <label>Starts<input type="datetime-local" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
          <label>Ends<input type="datetime-local" required value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>
        </div>
        <label>Description<textarea required rows={3} style={{ width: "100%" }} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <Msg error={a.error} notice={a.notice} />
        <button className="primary" disabled={a.busy}>Create job</button>
      </form>
    </>
  );
}
