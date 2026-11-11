import { useState } from "react";
import { openFile, post } from "../../api";
import { Msg, Status, useAction, useLoad, when } from "../../hooks";

// Supervisor view: work waiting for review, its evidence, scope changes, and what happens after completion.
export default function Review({ companyId }: { companyId: string }) {
  const waiting = useLoad<any[]>(`/companies/${companyId}/jobs?status=AwaitingReview`);
  const done = useLoad<any[]>(`/companies/${companyId}/jobs?status=Completed&take=20`);
  const [open, setOpen] = useState<string | null>(null);
  const exec = useLoad<any>(open ? `/companies/${companyId}/jobs/${open}/execution` : null);
  const a = useAction();
  const [note, setNote] = useState("");
  const [complaint, setComplaint] = useState("");
  const refresh = () => { waiting.reload(); done.reload(); exec.reload(); };

  const view = async (eid: string) => {
    const l = await post<{ url: string }>(`/companies/${companyId}/evidence/${eid}/link`);
    await openFile(l.url);
  };
  const jobsTable = (rows: any[] | null, label: string) => (
    <div className="card">
      <h2>{label}</h2>
      {rows?.length === 0 && <p className="muted">Nothing here.</p>}
      <table><tbody>{rows?.map((j) => (
        <tr key={j.id}><td>{j.reference}</td><td><Status value={j.status} /></td><td>{when(j.scheduledStart)}</td>
          <td><button className="ghost" onClick={() => setOpen(open === j.id ? null : j.id)}>Open</button></td></tr>))}</tbody></table>
    </div>
  );

  return (
    <>
      {jobsTable(waiting.data, "Awaiting review")}
      {jobsTable(done.data, "Recently completed")}
      {open && exec.data && (
        <div className="card">
          <h2>{exec.data.job.reference} <Status value={exec.data.job.status} /></h2>
          {exec.data.reports.map((r: any) => <p key={r.id}><b>Report v{r.version}</b> ({when(r.submittedAt)}{r.hoursWorked != null ? `, ${r.hoursWorked} h` : ""}): {r.summary}</p>)}
          <h2>Evidence</h2>
          {exec.data.evidence.length === 0 && <p className="muted">No evidence uploaded.</p>}
          {exec.data.evidence.map((e: any) => <div key={e.id}>{e.kind}: {e.fileName} <button className="ghost" onClick={() => a.run(() => view(e.id))}>View</button></div>)}
          <h2>Scope changes</h2>
          {exec.data.scopeChanges.length === 0 && <p className="muted">None reported.</p>}
          {exec.data.scopeChanges.map((s: any) => (
            <div key={s.id}>{s.description} <Status value={s.status} />
              {s.status === "Pending" && <>
                <button className="ghost" onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/scope-changes/${s.id}/decision`, { decision: "approve" }))) refresh(); }}>Approve</button>
                <button className="ghost" onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/scope-changes/${s.id}/decision`, { decision: "reject" }))) refresh(); }}>Reject</button></>}
            </div>))}
          {exec.data.job.status === "AwaitingReview" && (
            <div style={{ marginTop: 10 }}>
              <label>Note (required to return)<input style={{ width: "100%" }} value={note} onChange={(e) => setNote(e.target.value)} /></label>
              <div className="row">
                <button className="primary" disabled={a.busy} onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/review`, { decision: "approve", note }), "Approved.")) { setNote(""); refresh(); } }}>Approve work</button>
                <button className="danger" disabled={a.busy} onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/review`, { decision: "return", note }), "Returned to the technician.")) { setNote(""); refresh(); } }}>Return for correction</button>
              </div>
            </div>)}
          <h2>Complaints and callbacks</h2>
          {exec.data.job.warrantyEndsAt && <p className="muted">Warranty until {when(exec.data.job.warrantyEndsAt)}</p>}
          {exec.data.complaints.map((c: any) => (
            <div key={c.id}>{c.description} <Status value={c.status} /> {c.resolution}
              {c.status === "Open" && <button className="ghost" onClick={async () => { const r = prompt("Resolution?"); if (r && await a.run(() => post(`/companies/${companyId}/jobs/${open}/complaints/${c.id}/resolve`, { resolution: r }))) refresh(); }}>Resolve</button>}
            </div>))}
          {exec.data.related.map((r: any) => <div key={r.id} className="muted">{r.type}: responsibility {r.reworkResponsibility}{r.underWarranty ? ", under warranty" : ", outside warranty"}</div>)}
          {exec.data.job.status !== "Open" && (
            <div className="row" style={{ marginTop: 8 }}>
              <input placeholder="Describe a complaint" value={complaint} onChange={(e) => setComplaint(e.target.value)} />
              <button className="ghost" disabled={!complaint} onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/complaints`, { description: complaint }))) { setComplaint(""); refresh(); } }}>Record complaint</button>
              {exec.data.job.status === "Completed" && <button className="ghost" onClick={async () => {
                const days = Number(prompt("Callback in how many days?", "3")); if (!days) return;
                const resp = prompt("Who is responsible for the rework? technician, company, customer or undetermined", "undetermined") || "undetermined";
                const start = new Date(Date.now() + days * 86400000); const end = new Date(start.getTime() + 2 * 3600000);
                if (await a.run(() => post(`/companies/${companyId}/jobs/${open}/callback`, { scheduledStart: start.toISOString(), scheduledEnd: end.toISOString(), responsibility: resp }), "Callback job created.")) refresh();
              }}>Create callback job</button>}
            </div>)}
          <Msg error={a.error} notice={a.notice} />
        </div>
      )}
    </>
  );
}
