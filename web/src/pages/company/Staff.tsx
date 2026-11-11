import { useState } from "react";
import { api, post } from "../../api";
import { Msg, useAction, useLoad } from "../../hooks";

const ROLES = ["company_owner", "dispatcher", "supervisor", "company_finance", "auditor"];

export default function Staff({ companyId }: { companyId: string }) {
  const { data, error, reload } = useLoad<any[]>(`/companies/${companyId}/members`);
  const [email, setEmail] = useState(""); const [role, setRole] = useState("dispatcher");
  const a = useAction();
  return (
    <>
      <div className="card">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th></th></tr></thead>
          <tbody>
            {data?.map((m) => (
              <tr key={m.id}><td>{m.displayName}</td><td>{m.email}</td><td>{m.roles.join(", ")}</td>
                <td><button className="ghost" disabled={a.busy} onClick={async () => { if (confirm(`Remove ${m.email}?`) && await a.run(() => api("DELETE", `/companies/${companyId}/members/${m.id}`))) reload(); }}>Remove</button></td></tr>
            ))}
          </tbody>
        </table>
        {error && <div className="error">{error}</div>}
      </div>
      <form className="card" onSubmit={async (e) => { e.preventDefault(); if (await a.run(() => post(`/companies/${companyId}/members`, { email, roleCode: role }), "Staff member added.")) { setEmail(""); reload(); } }}>
        <h2>Add staff</h2>
        <p className="muted">The person must already have an account.</p>
        <div className="row">
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Role<select value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label>
          <button className="primary" disabled={a.busy}>Add</button>
        </div>
        <Msg error={a.error} notice={a.notice} />
      </form>
    </>
  );
}
