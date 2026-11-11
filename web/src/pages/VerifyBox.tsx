import { useState } from "react";
import { post } from "../api";
import { Msg, useAction } from "../hooks";
import { useT } from "../i18n";

// Email or phone verification: ask for a code, then confirm it. If the server has no email/SMS provider yet it says so (503).
// Email: the person types the address to verify; confirming a different address makes it their account email.
export default function VerifyBox({ channel, verified, current, onVerified }: { channel: "email" | "phone"; verified: boolean; current?: string; onVerified: () => void }) {
  const { t } = useT();
  const [sent, setSent] = useState(false); const [code, setCode] = useState("");
  const [email, setEmail] = useState(current ?? "");
  const [editing, setEditing] = useState(false);
  const [password, setPassword] = useState("");
  const a = useAction();
  const isEmail = channel === "email";
  const label = isEmail ? t("Email") : t("Phone");
  const changing = isEmail && email.trim().toLowerCase() !== (current ?? "").toLowerCase();   // a different address also needs the password
  const body = isEmail ? { email: email.trim(), ...(changing ? { password } : {}) } : undefined;
  const reset = () => { setSent(false); setCode(""); setEditing(false); setPassword(""); };

  if (verified && !editing) return (
    <div style={{ marginBottom: 12 }}>
      <p style={{ marginBottom: 4 }}>✓ {label}: <b>{t("Verified")}</b>{isEmail && current ? <span className="muted"> ({current})</span> : null}</p>
      {isEmail && <button type="button" className="ghost" onClick={() => { setEmail(""); setEditing(true); }}>{t("Use a different email")}</button>}
    </div>
  );

  return (
    <div style={{ marginBottom: 12 }}>
      {!editing && <p style={{ marginBottom: 4 }}>{label}: <b>{t("Not verified")}</b></p>}
      {isEmail && (
        <label>{t("Email address")}
          <input type="email" value={email} disabled={sent} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="email" inputMode="email" />
        </label>
      )}
      {changing && !sent && (
        <label>{t("Current password")}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
      )}
      {!sent ? (
        <button type="button" className="ghost" disabled={a.busy || (isEmail && !email.trim()) || (changing && !password)}
          onClick={async () => { if (await a.run(() => post(`/me/verify/${channel}/request`, body))) setSent(true); }}>{t("Send code")}</button>
      ) : (
        <div className="row">
          <label>{t("Code")}<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} autoComplete="one-time-code" /></label>
          <button type="button" className="primary" disabled={a.busy || code.trim().length < 6}
            onClick={async () => { if (await a.run(() => post(`/me/verify/${channel}/confirm`, { code: code.trim(), ...(isEmail ? { email: email.trim() } : {}) }))) { reset(); onVerified(); } }}>{t("Confirm")}</button>
          <button type="button" className="ghost" disabled={a.busy} onClick={() => { setSent(false); setCode(""); }}>{t("Change address")}</button>
        </div>
      )}
      {isEmail && editing && !sent && <button type="button" className="ghost" onClick={reset}>{t("Cancel")}</button>}
      <Msg error={a.error} />
    </div>
  );
}
