import { useState } from "react";
import { post } from "../../api";
import { Msg, useAction, useLoad } from "../../hooks";

export default function Customers({ companyId }: { companyId: string }) {
  const [q, setQ] = useState("");
  const { data, error, reload } = useLoad<any[]>(`/companies/${companyId}/customers?q=${encodeURIComponent(q)}`);
  const [open, setOpen] = useState<string | null>(null);
  const detail = useLoad<any>(open ? `/companies/${companyId}/customers/${open}` : null);
  const areas = useLoad<any[]>("/catalog/service-areas");
  const empty = { name: "", phone: "", email: "", locLabel: "", address: "", serviceAreaId: "" };
  const [c, setC] = useState(empty);
  const [l, setL] = useState({ label: "", address: "", serviceAreaId: "" });
  const a = useAction();
  const al = useAction();   // location messages show inside the location panel, next to the button
  return (
    <>
      <div className="card">
        <label>Search<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name or phone" /></label>
        <table>
          <thead><tr><th>Name</th><th>Phone</th><th></th></tr></thead>
          <tbody>{data?.map((x) => <tr key={x.id}><td>{x.name}</td><td>{x.phone}</td><td><button className="ghost" onClick={() => setOpen(open === x.id ? null : x.id)}>Locations</button></td></tr>)}</tbody>
        </table>
        {error && <div className="error">{error}</div>}
        {open && detail.data && (
          <div className="card">
            <b>{detail.data.name}</b>
            <ul>{detail.data.locations.map((x: any) => <li key={x.id}>{x.label}: {x.address}</li>)}</ul>
            {detail.data.locations.length === 0 && <p className="muted">No locations yet. Add one below. Jobs can only be created for a customer location.</p>}
            <div className="row">
              <label>Label<input value={l.label} onChange={(e) => setL({ ...l, label: e.target.value })} /></label>
              <label>Address<input value={l.address} onChange={(e) => setL({ ...l, address: e.target.value })} /></label>
              <label>Service area<select value={l.serviceAreaId} onChange={(e) => setL({ ...l, serviceAreaId: e.target.value })}><option value="">(none)</option>{areas.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
              <button disabled={al.busy} onClick={async () => { if (await al.run(() => post(`/companies/${companyId}/customers/${open}/locations`, { ...l, serviceAreaId: l.serviceAreaId || null }), "Location added.")) { setL({ label: "", address: "", serviceAreaId: "" }); detail.reload(); } }}>Add location</button>
            </div>
            <Msg error={al.error} notice={al.notice} />
          </div>
        )}
      </div>
      <form className="card" onSubmit={async (e) => {
        e.preventDefault();
        const ok = await a.run(async () => {
          const created = await post<any>(`/companies/${companyId}/customers`, { name: c.name, phone: c.phone, email: c.email });
          const cid = created?.id ?? created?.Id;
          try {
            await post(`/companies/${companyId}/customers/${cid}/locations`, { label: c.locLabel || "Main", address: c.address, serviceAreaId: c.serviceAreaId || null });
          } catch (err) {
            reload();
            throw new Error("Customer saved, but the location was not: " + (err instanceof Error ? err.message : "add it with the Locations button."));
          }
        }, "Customer and location added. You can now create jobs for them.");
        if (ok) { setC(empty); reload(); }
      }}>
        <h2>New customer</h2>
        <div className="row">
          <label>Name<input value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} required /></label>
          <label>Phone<input type="tel" value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} placeholder="+252 90 000 0000" required /></label>
          <label>Email<input type="email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} /></label>
        </div>
        <h2>Location</h2>
        <div className="row">
          <label>Service area<select required value={c.serviceAreaId} onChange={(e) => setC({ ...c, serviceAreaId: e.target.value })}><option value="">Select…</option>{areas.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>Address<input value={c.address} onChange={(e) => setC({ ...c, address: e.target.value })} placeholder="Neighbourhood, street, landmark" required /></label>
          <label>Location name (optional)<input value={c.locLabel} onChange={(e) => setC({ ...c, locLabel: e.target.value })} placeholder="e.g. Home or Shop" /></label>
        </div>
        <Msg error={a.error} notice={a.notice} />
        <button className="primary" disabled={a.busy}>Add customer</button>
      </form>
    </>
  );
}
