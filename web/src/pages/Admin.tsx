import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { openFile, post } from "../api";
import { Msg, Status, useAction, useLoad, useMe, when } from "../hooks";
import { Icon } from "../icons";

const TAB_ICONS: Record<string, string> = { companies: "building", documents: "file", skills: "star", catalog: "list", support: "users" };

// Platform administration: verification queues, catalog, service areas and account support.
// The links shown depend on the signed-in user's platform permissions; the backend enforces them on every call.
export default function Admin() {
  const { me } = useMe(); const p = me.platform;
  const tabs = [p.companyVerify && "companies", p.technicianVerify && "documents", p.technicianVerify && "skills", p.catalog && "catalog", p.support && "support"].filter(Boolean) as string[];
  return (
    <>
      <h1>Platform administration</h1>
      <nav className="row" style={{ marginBottom: 12 }}>
        {tabs.map((t) => <NavLink key={t} to={`/admin/${t}`} className={({ isActive }) => (isActive ? "pill Active" : "pill")} style={{ padding: "6px 12px", textDecoration: "none", color: "inherit" }}><Icon name={TAB_ICONS[t]} size={16} />{t[0].toUpperCase() + t.slice(1)}</NavLink>)}
      </nav>
      <Routes>
        {p.companyVerify && <Route path="companies" element={<CompanyQueue />} />}
        {p.technicianVerify && <Route path="documents" element={<DocumentQueue />} />}
        {p.technicianVerify && <Route path="skills" element={<SkillQueue />} />}
        {p.catalog && <Route path="catalog" element={<Catalog />} />}
        {p.support && <Route path="support" element={<Support />} />}
        <Route path="*" element={<Navigate to={tabs[0] ?? "/companies"} replace />} />
      </Routes>
    </>
  );
}

function Decision({ onDecide, busy }: { onDecide: (decision: string, note: string) => void; busy: boolean }) {
  const [note, setNote] = useState("");
  return (
    <div className="row">
      <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="primary" disabled={busy} onClick={() => onDecide("approve", note)}><Icon name="check" size={16} />Approve</button>
      <button className="ghost" disabled={busy} onClick={() => onDecide("request_info", note)}>Request info</button>
      <button className="danger" disabled={busy} onClick={() => onDecide("reject", note)}><Icon name="x" size={16} />Reject</button>
    </div>
  );
}

function CompanyQueue() {
  const { data, error, reload } = useLoad<any[]>("/platform/companies?status=Pending");
  const a = useAction();
  return (
    <>
      <p className="muted">Evidence requirements for approval are a business decision that has not been defined yet; review against whatever policy your team agrees.</p>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">No companies waiting.</p>}
      {data?.map((c) => (
        <div className="card" key={c.id}>
          <b>{c.displayName}</b> <Status value={c.verification} />
          <div>{c.businessCategory} · {c.contactEmail} {c.contactPhone} · Registration: {c.registrationRef ?? "not provided"}</div>
          <Decision busy={a.busy} onDecide={async (decision, note) => { if (await a.run(() => post(`/platform/companies/${c.id}/decision`, { decision, note }))) reload(); }} />
        </div>
      ))}
      <Msg error={a.error} />
    </>
  );
}

function DocumentQueue() {
  const [status, setStatus] = useState("Pending");
  const { data, error, reload } = useLoad<any[]>(`/platform/technician-documents?status=${status}`);
  const a = useAction();
  return (
    <>
      <label>Show<select value={status} onChange={(e) => setStatus(e.target.value)}>{["Pending", "NeedsInfo", "Approved", "Rejected"].map((s) => <option key={s}>{s}</option>)}</select></label>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">Nothing here.</p>}
      {data?.map((d) => (
        <div className="card" key={d.id}>
          <b>{d.technician}</b>: {d.kind} · {d.fileName} · {(d.sizeBytes / 1024).toFixed(0)} KB · uploaded {when(d.uploadedAt)}
          <div className="row" style={{ margin: "8px 0" }}>
            <button className="ghost" onClick={() => a.run(async () => { const r = await post<{ url: string }>(`/platform/technician-documents/${d.id}/link`); await openFile(r.url); })}>Open document</button>
          </div>
          {d.status === "Pending" && <Decision busy={a.busy} onDecide={async (decision, note) => { if (await a.run(() => post(`/platform/technician-documents/${d.id}/decision`, { decision, note }))) reload(); }} />}
          {d.status !== "Pending" && <Status value={d.status} />}
        </div>
      ))}
      <Msg error={a.error} />
    </>
  );
}

function SkillQueue() {
  const { data, error, reload } = useLoad<any[]>("/platform/technician-skills?status=Pending");
  const [exp, setExp] = useState<Record<string, string>>({});
  const a = useAction();
  return (
    <>
      <p className="muted">Qualification requirements per trade are a business decision. Check the technician's uploaded documents before approving; set an expiry where the qualification has one.</p>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">No skills waiting.</p>}
      {data?.map((s) => {
        const k = s.technicianId + s.skillId;
        const decide = async (decision: string) => { if (await a.run(() => post(`/platform/technicians/${s.technicianId}/skills/${s.skillId}/decision`, { decision, expiresOn: exp[k] || undefined }))) reload(); };
        return (
          <div className="card" key={k}>
            <b>{s.technician}</b>: {s.trade} / {s.skill}
            <div className="row">
              <label>Expires on (optional)<input type="date" value={exp[k] ?? ""} onChange={(e) => setExp({ ...exp, [k]: e.target.value })} /></label>
              <button className="primary" disabled={a.busy} onClick={() => decide("approve")}>Approve</button>
              <button className="ghost" disabled={a.busy} onClick={() => decide("request_info")}>Request info</button>
              <button className="danger" disabled={a.busy} onClick={() => decide("reject")}>Reject</button>
            </div>
          </div>
        );
      })}
      <Msg error={a.error} />
    </>
  );
}

function Catalog() {
  const trades = useLoad<any[]>("/catalog/trades");
  const areas = useLoad<any[]>("/catalog/service-areas");
  const [trade, setTrade] = useState(""); const [skill, setSkill] = useState({ tradeId: "", name: "" }); const [area, setArea] = useState("");
  const a = useAction();
  return (
    <>
      <div className="card">
        <h2>Trades and skills</h2>
        {trades.data?.map((t) => <div key={t.id}><b>{t.name}</b>: {t.skills.map((s: any) => s.name).join(", ") || <span className="muted">no skills yet</span>}</div>)}
        <div className="row">
          <label>New trade<input value={trade} onChange={(e) => setTrade(e.target.value)} /></label>
          <button disabled={a.busy || !trade} onClick={async () => { if (await a.run(() => post("/platform/trades", { name: trade }))) { setTrade(""); trades.reload(); } }}>Add trade</button>
        </div>
        <div className="row">
          <label>Trade<select value={skill.tradeId} onChange={(e) => setSkill({ ...skill, tradeId: e.target.value })}><option value="">Select…</option>{trades.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label>New skill<input value={skill.name} onChange={(e) => setSkill({ ...skill, name: e.target.value })} /></label>
          <button disabled={a.busy || !skill.tradeId || !skill.name} onClick={async () => { if (await a.run(() => post(`/platform/trades/${skill.tradeId}/skills`, { name: skill.name }))) { setSkill({ ...skill, name: "" }); trades.reload(); } }}>Add skill</button>
        </div>
      </div>
      <div className="card">
        <h2>Service areas</h2>
        <p className="muted">The launch city and service radius are business decisions; add the areas you decide on.</p>
        <div>{areas.data?.map((s) => <span key={s.id} className="pill" style={{ marginRight: 6 }}>{s.name}</span>)}</div>
        <div className="row">
          <label>New area<input value={area} onChange={(e) => setArea(e.target.value)} /></label>
          <button disabled={a.busy || !area} onClick={async () => { if (await a.run(() => post("/platform/service-areas", { name: area }))) { setArea(""); areas.reload(); } }}>Add area</button>
        </div>
        <Msg error={a.error} />
      </div>
    </>
  );
}

function Support() {
  const [userId, setUserId] = useState("");
  const a = useAction();
  return (
    <div className="card">
      <h2>Reset a user's two-factor authentication</h2>
      <p className="muted">Only after you have verified the person's identity through your agreed out-of-band process. They are signed out everywhere, notified, and must set MFA up again. You cannot reset your own.</p>
      <div className="row">
        <label>User id<input value={userId} onChange={(e) => setUserId(e.target.value)} style={{ width: 340 }} /></label>
        <button className="danger" disabled={a.busy || !userId} onClick={() => confirm("Reset MFA for this user?") && a.run(() => post(`/platform/users/${userId.trim()}/mfa-reset`), "MFA reset.")}>Reset MFA</button>
      </div>
      <Msg error={a.error} notice={a.notice} />
    </div>
  );
}
