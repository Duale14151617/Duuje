import { useState } from "react";
import { post } from "../api";
import { Msg, useAction, useMe } from "../hooks";
import VerifyBox from "./VerifyBox";

export default function Security() {
  const { me, reload } = useMe();
  const [setup, setSetup] = useState<{ secret: string; otpauthUri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState(""); const [password, setPassword] = useState("");
  const a = useAction();

  return (
    <>
      <h1>Security</h1>
      <div className="card">
        <h2>Email</h2>
        <p className="muted">{me.email}</p>
        <VerifyBox channel="email" verified={!!me.emailVerified} current={me.email} onVerified={reload} />
      </div>
      <div className="card">
        <h2>Two-factor authentication</h2>
        <p>Status: <b>{me.mfaEnabled ? "On" : "Off"}</b></p>
        {!me.mfaEnabled && !setup && <button onClick={() => a.run(async () => setSetup(await post("/auth/mfa/setup")))}>Set up authenticator app</button>}
        {!me.mfaEnabled && setup && (
          <>
            <p>Add this key to your authenticator app (Google Authenticator, Microsoft Authenticator, Aegis…), then enter the 6-digit code it shows.</p>
            <code className="secret">{setup.secret}</code>
            <p className="muted">Or open on your phone: <a href={setup.otpauthUri}>authenticator link</a></p>
            <div className="row">
              <label>Code<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} /></label>
              <button className="primary" disabled={a.busy} onClick={() => a.run(async () => { const r = await post<{ recoveryCodes: string[] }>("/auth/mfa/enable", { code }); setCodes(r.recoveryCodes); setSetup(null); reload(); })}>Turn on</button>
            </div>
          </>
        )}
        {codes && (
          <div className="card">
            <b>Save these recovery codes now. They are shown only once and each works one time.</b>
            <pre>{codes.join("\n")}</pre>
          </div>
        )}
        {me.mfaEnabled && (
          <div className="row">
            <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
            <label>Code<input value={code} onChange={(e) => setCode(e.target.value)} /></label>
            <button className="danger" disabled={a.busy} onClick={() => a.run(async () => { await post("/auth/mfa/disable", { password, code }); window.location.assign("/login"); })}>Turn off (signs you out everywhere)</button>
          </div>
        )}
        <Msg error={a.error} notice={a.notice} />
      </div>
    </>
  );
}
