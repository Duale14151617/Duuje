import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AlertPreferences } from "../components/AlertPreferences";
import { EnableMfa } from "../components/EnableMfa";
import { ChangePassword } from "../components/ChangePassword";
import { MyAccess } from "../components/MyAccess";
import { MySessions } from "../components/MySessions";
import { SecuritySummary } from "../components/SecuritySummary";
import { SecurityKeys } from "../components/SecurityKeys";
import { Avatar } from "../components/Avatar";
import { AvatarEditor } from "../components/AvatarEditor";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";

/** The signed-in user's own account. For now: confirm the email address with a code, which is what unlocks "Forgot your password?". */
export function Account() {
  const { me, reload, can, logout } = useAuth();
  const canSetPicture = can("users.manage"); // HQ administrators and super administrators; the server enforces who may change whose
  const { t } = useI18n();
  const current = me?.email ?? "";
  const verified = me?.email_verified === true;
  const enabled = me?.features.email_verification === true;
  const [editing, setEditing] = useState(false);
  const [email, setEmail] = useState(current);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const target = email.trim().toLowerCase();
  const changing = target !== current.toLowerCase(); // a different (or first) address also needs the current password

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await work(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const request = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    await api("/auth/email/verify/request/", { method: "POST", body: { email: target, ...(changing ? { password } : {}) } });
    setSentTo(target); setDone(false);
  }); };
  const confirm = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    await api("/auth/email/verify/confirm/", { method: "POST", body: { code: code.trim(), email: sentTo ?? target } });
    setSentTo(null); setCode(""); setPassword(""); setEditing(false); setDone(true);
    await reload();
  }); };
  const startOver = () => { setSentTo(null); setCode(""); setError(null); };

  return (
    <>
      <h1>{t("account.title")}</h1>
      <section className="card">
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          {!canSetPicture && <Avatar size={72} />}
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ margin: 0 }}>{me?.full_name}</h2>
            <p className="muted" style={{ margin: ".2rem 0" }}>{me?.username}</p>
            <p style={{ margin: 0 }}>
              {current || <span className="muted">{t("account.noEmail")}</span>}{" "}
              {current && (verified ? <Chip tone="ok">{t("account.verified")}</Chip> : <Chip tone="warn">{t("account.notVerified")}</Chip>)}
            </p>
          </div>
          <button type="button" className="secondary" onClick={() => void logout()}>{t("common.signOut")}</button>
        </div>
        {canSetPicture && me && <div className="mt-1"><AvatarEditor userId={me.id} onChanged={() => void reload()} /></div>}
        {!canSetPicture && <p className="muted" style={{ marginBottom: 0 }}>{t("account.pictureAdminOnly")}</p>}
      </section>
      <section className="card">
        <h2>{t("account.email")}</h2>
        {done && <Notice>{t("account.verifiedDone")}</Notice>}
        {!enabled ? (
          !verified && <Notice>{t("account.unavailable")}</Notice>
        ) : verified && !editing ? (
          <button type="button" className="secondary" onClick={() => { setEmail(""); setEditing(true); setDone(false); }}>{t("account.useOther")}</button>
        ) : (
          <>
            {!verified && !sentTo && <p>{t("account.verifyIntro")}</p>}
            <ErrorNotice error={error} />
            {sentTo ? (
              <form onSubmit={confirm}>
                <Notice>{t("account.codeSent", { email: sentTo })}</Notice>
                <Field label={t("account.code")}>
                  <input value={code} inputMode="numeric" maxLength={6} autoComplete="one-time-code" onChange={(e) => setCode(e.target.value)} required />
                </Field>
                <div className="row">
                  <button type="submit" disabled={busy || code.trim().length < 6}>{t("account.confirm")}</button>
                  <button type="button" className="secondary" disabled={busy} onClick={startOver}>{t("account.changeAddress")}</button>
                </div>
              </form>
            ) : (
              <form onSubmit={request}>
                <Field label={t("account.email")}>
                  <input type="email" value={email} autoComplete="email" inputMode="email" placeholder={t("account.emailPh")} onChange={(e) => setEmail(e.target.value)} required />
                </Field>
                {changing && (
                  <Field label={t("account.currentPassword")}>
                    <input type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} required />
                  </Field>
                )}
                <div className="row">
                  <button type="submit" disabled={busy || !target || (changing && !password)}>{t("account.sendCode")}</button>
                  {editing && <button type="button" className="secondary" disabled={busy} onClick={() => { setEditing(false); setEmail(current); setPassword(""); setError(null); }}>{t("common.cancel")}</button>}
                </div>
              </form>
            )}
          </>
        )}
      </section>
      <SecuritySummary />
      <EnableMfa />
      <ChangePassword />
      <SecurityKeys />
      <MySessions />
      <MyAccess />
      <AlertPreferences />
    </>
  );
}
