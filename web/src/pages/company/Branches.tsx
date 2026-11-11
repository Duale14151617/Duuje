import { useState } from "react";
import { post, put } from "../../api";
import { Msg, Status, useAction, useLoad } from "../../hooks";

export default function Branches({ companyId }: { companyId: string }) {
  const { data, error, reload } = useLoad<any[]>(`/companies/${companyId}/branches`);
  const staff = useLoad<any[]>(`/companies/${companyId}/members`);
  const [name, setName] = useState(""); const [address, setAddress] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const a = useAction();
  return (
    <>
      <div className="card">
        <table>
          <thead><tr><th>Branch</th><th>Address</th><th>Status</th><th>Staff</th><th></th></tr></thead>
          <tbody>
            {data?.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td><td>{b.address}</td><td><Status value={b.status} /></td><td>{b.memberCount}</td>
                <td className="row">
                  <button className="ghost" onClick={() => { setEditing(editing === b.id ? null : b.id); setPicked([]); }}>Assign staff</button>
                  <button className="ghost" disabled={a.busy} onClick={async () => { if (await a.run(() => post(`/companies/${companyId}/branches/${b.id}/status`, { active: b.status !== "Active" }))) reload(); }}>{b.status === "Active" ? "Close" : "Reopen"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <div className="error">{error}</div>}
        {editing && (
          <div className="card">
            <b>Staff in this branch</b> <span className="muted">(replaces the current list)</span>
            {staff.data?.map((m) => (
              <label key={m.id}><input type="checkbox" checked={picked.includes(m.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, m.id] : picked.filter((x) => x !== m.id))} /> {m.displayName} ({m.email})</label>
            ))}
            <button className="primary" disabled={a.busy} onClick={async () => { if (await a.run(() => put(`/companies/${companyId}/branches/${editing}/members`, { membershipIds: picked }), "Saved.")) { setEditing(null); reload(); } }}>Save</button>
          </div>
        )}
      </div>
      <form className="card" onSubmit={async (e) => { e.preventDefault(); if (await a.run(() => post(`/companies/${companyId}/branches`, { name, address }), "Branch created.")) { setName(""); setAddress(""); reload(); } }}>
        <h2>New branch</h2>
        <div className="row">
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
          <label>Address<input value={address} onChange={(e) => setAddress(e.target.value)} /></label>
          <button className="primary" disabled={a.busy}>Add</button>
        </div>
        <Msg error={a.error} notice={a.notice} />
      </form>
    </>
  );
}
