import { FormEvent, useEffect, useState } from "react";
import { ApiError, post, put, upload } from "../api";
import { Msg, Status, errText, useAction, useLoad, useMe, when } from "../hooks";
import { useT } from "../i18n";
import VerifyBox from "./VerifyBox";

type Skill = { id: string; name: string; verification: string; expiresOn?: string | null; eligible: boolean };
type Profile = { id: string; displayName: string; phone?: string | null; phoneVerified?: boolean; skills: Skill[] };
type Trade = { id: string; name: string; skills: { id: string; name: string }[] };

export default function Technician() {
  const { me, reload: reloadMe } = useMe();
  const profile = useLoad<Profile>("/technicians/me");
  const missing = profile.error.includes("404") || profile.error === "Not found (404).";

  if (profile.loading && !profile.data) return <div className="card">Loading…</div>;
  if (missing) return <CreateProfile defaultName={me.displayName} onDone={() => { profile.reload(); reloadMe(); }} />;
  if (profile.error || !profile.data) return <div className="card"><Msg error={profile.error} /></div>;
  return <Dashboard profile={profile.data} reload={profile.reload} />;
}

function CreateProfile({ defaultName, onDone }: { defaultName: string; onDone: () => void }) {
  const { t } = useT();
  const [name, setName] = useState(defaultName); const [phone, setPhone] = useState("");
  const a = useAction();
  const submit = async (e: FormEvent) => { e.preventDefault(); if (await a.run(() => post("/technicians/me", { displayName: name, phone: phone || undefined }))) onDone(); };
  return (
    <form className="card narrow" onSubmit={submit}>
      <h1>{t("Register as a technician")}</h1>
      <p className="muted">Create your technician profile. Next you will choose your skills and upload your documents for review.</p>
      <label>{t("Full name")}<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <label>{t("Phone")}<input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+252 90 000 0000" required /></label>
      <Msg error={a.error} />
      <button className="primary" disabled={a.busy}>{t("Create technician profile")}</button>
    </form>
  );
}

function Dashboard({ profile, reload }: { profile: Profile; reload: () => void }) {
  const { t } = useT();
  const { me, reload: reloadMe } = useMe();
  const areas = useLoad<{ id: string }[]>("/technicians/me/service-areas");
  const docs = useLoad<any[]>("/technicians/me/documents");
  return (
    <>
      <section className="hero">
        <small>Technician</small>
        <h1>{profile.displayName}</h1>
        <p>Claim your skills and upload your documents. A reviewer verifies each skill before you can be matched to jobs.</p>
      </section>
      <Checklist profile={profile} areas={areas.data?.length ?? 0} hasId={!!docs.data?.some((d) => d.kind === "identity")} />
      <Ratings />
      <Details profile={profile} reload={reload} />
      <div className="card">
        <h2 style={{ marginTop: 0 }}>{t("Verification")}</h2>
        {/* Phone verification is hidden until an SMS provider is set up (see Phase8Endpoints /me/verify/phone). */}
        <VerifyBox channel="email" verified={!!me.emailVerified} current={me.email} onVerified={reloadMe} />
      </div>
      <Skills profile={profile} reload={reload} />
      <Areas mine={areas} />
      <Documents docs={docs} />
      <Invitations />
    </>
  );
}

function Checklist({ profile, areas, hasId }: { profile: Profile; areas: number; hasId: boolean }) {
  const { t } = useT();
  const steps = [
    { done: !!profile.displayName && !!profile.phone, label: "Name and phone added" },
    { done: profile.skills.length > 0, label: "Skills chosen" },
    { done: areas > 0, label: "Service areas chosen" },
    { done: hasId, label: "ID document uploaded" },
    { done: profile.skills.some((s) => s.eligible), label: "At least one skill verified (needed before companies can invite you)" },
  ];
  const n = steps.filter((x) => x.done).length;
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Profile progress")}: {n} / {steps.length}</h2>
      <div className="progress" aria-hidden="true"><span style={{ width: `${(n / steps.length) * 100}%`, animation: "none" }} /></div>
      <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0" }}>
        {steps.map((x) => <li key={x.label} style={{ padding: "4px 0" }}>{x.done ? "✓" : "○"} <span className={x.done ? "muted" : ""}>{t(x.label)}</span></li>)}
      </ul>
      {n === steps.length && <p className="notice">{t("Your profile is complete. Companies can now invite you.")}</p>}
    </div>
  );
}

function Ratings() {
  const { t } = useT();
  const r = useLoad<{ count: number; average: number | null; recent: { stars: number; comment?: string | null; company: string; jobReference: string }[] }>("/technicians/me/ratings");
  if (!r.data || r.data.count === 0) return null;
  const stars = (n: number) => "★".repeat(n) + "☆".repeat(5 - n);
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Ratings")}: ★ {r.data.average} ({r.data.count})</h2>
      {r.data.recent.map((x, i) => (
        <div key={i} style={{ padding: "4px 0" }}>
          <span aria-label={`${x.stars} / 5`}>{stars(x.stars)}</span> <span className="muted">{x.company} · {x.jobReference}</span>
          {x.comment && <div>{x.comment}</div>}
        </div>
      ))}
    </div>
  );
}

function Details({ profile, reload }: { profile: Profile; reload: () => void }) {
  const { t } = useT();
  const [name, setName] = useState(profile.displayName); const [phone, setPhone] = useState(profile.phone ?? "");
  const a = useAction();
  return (
    <form className="card" onSubmit={async (e) => { e.preventDefault(); if (await a.run(() => put("/technicians/me", { displayName: name, phone: phone || undefined }), t("Saved."))) reload(); }}>
      <h2 style={{ marginTop: 0 }}>{t("Your details")}</h2>
      <div className="row">
        <label>{t("Full name")}<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>{t("Phone")}<input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
      </div>
      <Msg error={a.error} notice={a.notice} />
      <button className="primary" disabled={a.busy}>{t("Save details")}</button>
    </form>
  );
}

function Skills({ profile, reload }: { profile: Profile; reload: () => void }) {
  const { t } = useT();
  const trades = useLoad<Trade[]>("/catalog/trades");
  const [picked, setPicked] = useState<Set<string>>(new Set(profile.skills.map((s) => s.id)));
  useEffect(() => setPicked(new Set(profile.skills.map((s) => s.id))), [profile]);
  const status = new Map(profile.skills.map((s) => [s.id, s]));
  const a = useAction();
  const toggle = (id: string) => { const n = new Set(picked); n.has(id) ? n.delete(id) : n.add(id); setPicked(n); };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Skills")}</h2>
      <p className="muted">Tick the skills you have. Each one is reviewed before you can receive jobs.</p>
      {trades.error && <div className="error">{trades.error}</div>}
      {trades.data?.filter((t) => t.skills.length > 0).map((t) => (
        <div key={t.id}>
          <b>{t.name}</b>
          {t.skills.map((s) => {
            const st = status.get(s.id);
            return (
              <label key={s.id}><input type="checkbox" checked={picked.has(s.id)} onChange={() => toggle(s.id)} />{s.name}
                {st && <> <Status value={st.verification} />{st.expiresOn ? ` expires ${st.expiresOn}` : ""}</>}
              </label>
            );
          })}
        </div>
      ))}
      {trades.data && trades.data.every((t) => t.skills.length === 0) && <p className="muted">No skills have been set up by the platform yet.</p>}
      <Msg error={a.error} notice={a.notice} />
      <button className="primary" disabled={a.busy} onClick={async () => { if (await a.run(() => put("/technicians/me/skills", { skillIds: [...picked] }), t("Skills saved."))) reload(); }}>{t("Save skills")}</button>
    </div>
  );
}

function Areas({ mine }: { mine: ReturnType<typeof useLoad<{ id: string }[]>> }) {
  const { t } = useT();
  const all = useLoad<{ id: string; name: string }[]>("/catalog/service-areas");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => { if (mine.data) setPicked(new Set(mine.data.map((x) => x.id))); }, [mine.data]);
  const a = useAction();
  const toggle = (id: string) => { const n = new Set(picked); n.has(id) ? n.delete(id) : n.add(id); setPicked(n); };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Service areas")}</h2>
      {all.data && all.data.length === 0 && <p className="muted">No service areas have been set up yet.</p>}
      {all.data?.map((x) => <label key={x.id}><input type="checkbox" checked={picked.has(x.id)} onChange={() => toggle(x.id)} />{x.name}</label>)}
      <Msg error={a.error || all.error || mine.error} notice={a.notice} />
      {all.data && all.data.length > 0 && <button className="primary" disabled={a.busy} onClick={async () => { if (await a.run(() => put("/technicians/me/service-areas", { serviceAreaIds: [...picked] }), t("Service areas saved."))) mine.reload(); }}>{t("Save service areas")}</button>}
    </div>
  );
}

function Documents({ docs }: { docs: ReturnType<typeof useLoad<any[]>> }) {
  const { t } = useT();
  const [kind, setKind] = useState("identity"); const [file, setFile] = useState<File | null>(null);
  const a = useAction();
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    if (file.size > 5_000_000) { a.run(async () => { throw new ApiError(413, "File is larger than 5 MB."); }); return; }
    const form = new FormData(); form.append("kind", kind); form.append("file", file);
    if (await a.run(() => upload("/technicians/me/documents", form), "Uploaded. A reviewer will check it.")) { setFile(null); (e.target as HTMLFormElement).reset(); docs.reload(); }
  };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Documents")}</h2>
      <p className="muted">Upload your ID and qualification documents (PDF, JPG or PNG, up to 5 MB). Only you and platform reviewers can see them.</p>
      <form onSubmit={send}>
        <div className="row">
          <label>{t("Type")}<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="identity">{t("Identity")}</option><option value="qualification">{t("Qualification")}</option><option value="other">{t("Other")}</option></select></label>
          <label>{t("File")}<input type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required /></label>
        </div>
        <Msg error={a.error} notice={a.notice} />
        <button className="primary" disabled={a.busy || !file}>{a.busy ? t("Uploading…") : t("Upload")}</button>
      </form>
      {docs.error && <div className="error">{docs.error}</div>}
      {docs.data && docs.data.length > 0 && (
        <table style={{ marginTop: 16 }}>
          <thead><tr><th>File</th><th>Type</th><th>Status</th><th>Uploaded</th><th>Reviewer note</th></tr></thead>
          <tbody>{docs.data.map((d) => <tr key={d.id}><td>{d.fileName}</td><td>{d.kind}</td><td><Status value={d.status} /></td><td>{when(d.uploadedAt)}</td><td>{d.reviewNote ?? ""}</td></tr>)}</tbody>
        </table>
      )}
    </div>
  );
}

function Invitations() {
  const { t } = useT();
  const rels = useLoad<any[]>("/technicians/me/relationships");
  const [err, setErr] = useState("");
  const respond = async (id: string, accept: boolean) => {
    try { await post(`/technicians/me/relationships/${id}/respond`, { accept }); setErr(""); rels.reload(); } catch (e) { setErr(errText(e)); }
  };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{t("Companies")}</h2>
      {rels.data && rels.data.length === 0 && <p className="muted">No company invitations yet. Companies can invite you once you have a verified skill.</p>}
      {rels.data && rels.data.length > 0 && (
        <table>
          <thead><tr><th>Company</th><th>Type</th><th>Status</th><th></th></tr></thead>
          <tbody>{rels.data.map((r) => (
            <tr key={r.id}><td>{r.company}</td><td>{r.type}</td><td><Status value={r.status} /></td>
              <td className="row">{r.status === "Invited" && <><button className="primary" onClick={() => respond(r.id, true)}>{t("Accept")}</button><button className="ghost" onClick={() => respond(r.id, false)}>{t("Decline")}</button></>}</td></tr>
          ))}</tbody>
        </table>
      )}
      <Msg error={err || rels.error} />
    </div>
  );
}
