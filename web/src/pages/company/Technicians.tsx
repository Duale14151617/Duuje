import { ChangeEvent, useState } from "react";
import { post } from "../../api";
import { Msg, Status, errText, useAction, useLoad, when } from "../../hooks";
import { useT } from "../../i18n";

type Row = { email: string; type: string; result: "ok" | "error" | "unregistered"; message: string };

// One invitation per line: "email" or "email,Employed|Independent". A header row and blank lines are ignored.
function parseCsv(text: string): { email: string; type: string }[] {
  return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const [email, type] = l.split(/[;,\t]/).map((x) => x.trim().replace(/^"|"$/g, ""));
    return { email: (email ?? "").toLowerCase(), type: /^employed$/i.test(type ?? "") ? "Employed" : "Independent" };
  }).filter((r) => r.email.includes("@"));
}

function CsvImport({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const { t } = useT();
  const [text, setText] = useState(""); const [rows, setRows] = useState<Row[]>([]); const [busy, setBusy] = useState(false);
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); };
  const run = async () => {
    const items = parseCsv(text).slice(0, 200);
    setBusy(true); setRows([]);
    const out: Row[] = [];
    for (const it of items) {
      try {
        await post(`/companies/${companyId}/relationships`, { technicianEmail: it.email, type: it.type });
        out.push({ ...it, result: "ok", message: "Invited" });
      } catch (e) {
        const m = errText(e);
        out.push({ ...it, result: m.includes("No technician profile") ? "unregistered" : "error", message: m });
      }
      setRows([...out]);
    }
    setBusy(false); onDone();
  };
  const unregistered = rows.filter((r) => r.result === "unregistered");
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Import technicians from CSV")}</h2>
      <p className="muted">One technician per line: <code>email</code> or <code>email,Employed</code> (default Independent). Up to 200 lines. Each person is invited separately.</p>
      <label>CSV file<input type="file" accept=".csv,text/csv,text/plain" onChange={onFile} /></label>
      <label>Or paste lines<textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={"amina@example.com\nabdi@example.com,Employed"} /></label>
      <button className="primary" disabled={busy || parseCsv(text).length === 0} onClick={run}>{busy ? "…" : `${t("Import")} (${parseCsv(text).length})`}</button>
      {rows.length > 0 && (
        <>
          <p>{rows.filter((r) => r.result === "ok").length} invited · {unregistered.length} not registered yet · {rows.filter((r) => r.result === "error").length} failed</p>
          <table>
            <thead><tr><th>Email</th><th>Type</th><th>Result</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.email}><td>{r.email}</td><td>{r.type}</td><td>{r.result === "ok" ? "✓ Invited" : r.message}</td></tr>)}</tbody>
          </table>
          {unregistered.length > 0 && (
            <div className="notice">
              <p style={{ marginTop: 0 }}>These people have no technician profile yet. Send them this sign-up link, then invite them again:</p>
              <input readOnly value={`${window.location.origin}/login?role=technician`} onFocus={(e) => e.target.select()} aria-label="Technician sign-up link" />
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Technicians({ companyId }: { companyId: string }) {
  const { data, error, reload } = useLoad<any[]>(`/companies/${companyId}/relationships`);
  const [email, setEmail] = useState(""); const [type, setType] = useState("Independent");
  const a = useAction();
  const [copied, setCopied] = useState(false);
  const notRegistered = a.error.includes("No technician profile");
  const signupLink = `${window.location.origin}/login?role=technician&email=${encodeURIComponent(email.trim())}`;
  const copy = async () => { try { await navigator.clipboard.writeText(signupLink); setCopied(true); } catch { window.prompt("Copy this link", signupLink); } };
  const act = async (id: string, action: string) => { if (await a.run(() => post(`/companies/${companyId}/relationships/${id}/action`, { action }))) reload(); };
  return (
    <>
      <div className="card">
        <table>
          <thead><tr><th>Technician</th><th>Type</th><th>Status</th><th>Rating</th><th>Valid from</th><th></th></tr></thead>
          <tbody>
            {data?.map((r) => (
              <tr key={r.id}><td>{r.technician}</td><td>{r.type}</td><td><Status value={r.status} />{r.phoneVerified && <span className="muted" title="Phone number verified"> ✓ phone</span>}</td><td>{r.ratingCount > 0 ? `★ ${r.rating} (${r.ratingCount})` : "–"}</td><td>{when(r.validFrom)}</td>
                <td className="row">
                  {r.status === "Active" && <button className="ghost" onClick={() => act(r.id, "suspend")}>Suspend</button>}
                  {r.status === "Suspended" && <button className="ghost" onClick={() => act(r.id, "reactivate")}>Reactivate</button>}
                  {["Invited", "Active", "Suspended"].includes(r.status) && <button className="ghost" onClick={() => act(r.id, "end")}>End</button>}
                </td></tr>
            ))}
          </tbody>
        </table>
        {error && <div className="error">{error}</div>}
      </div>
      <form className="card" onSubmit={async (e) => { e.preventDefault(); if (await a.run(() => post(`/companies/${companyId}/relationships`, { technicianEmail: email, type }), "Invitation sent.")) { setEmail(""); reload(); } }}>
        <h2>Invite a technician</h2>
        <p className="muted">They need a technician profile with at least one verified skill.</p>
        <div className="row">
          <label>Technician email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Relationship<select value={type} onChange={(e) => setType(e.target.value)}><option>Independent</option><option>Employed</option></select></label>
          <button className="primary" disabled={a.busy}>Invite</button>
        </div>
        <Msg error={a.error} notice={a.notice} />
        {notRegistered && (
          <div className="notice">
            <p style={{ marginTop: 0 }}>This person has not registered as a technician yet. Send them this sign-up link. Once they have registered and have a verified skill, invite them again.</p>
            <input readOnly value={signupLink} onFocus={(e) => e.target.select()} aria-label="Technician sign-up link" />
            <button type="button" className="ghost" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
          </div>
        )}
      </form>
      <CsvImport companyId={companyId} onDone={reload} />
    </>
  );
}
