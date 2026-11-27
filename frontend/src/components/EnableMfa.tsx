import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { BackupCodesPanel } from "./BackupCodesPanel";
import { ErrorNotice, Field, Notice } from "./ui";

/** Account page: any signed-in user can turn on two-step sign-in (authenticator app). Optional for ordinary roles,
 *  already required for privileged ones. Ends by showing the backup codes once. */
export function EnableMfa() {
  const { me, reload } = useAuth();
  const { t } = useI18n();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // After confirming, mfa_enabled flips to true: keep the backup codes on screen until the person has saved them.
  if (codes) return <BackupCodesPanel codes={codes} onDone={() => { setCodes(null); void reload(); }} />;
  if (!me || me.mfa_enabled) return null;

  async function start() {
    setBusy(true); setError(null);
    try { setSetup(await api<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup/", { method: "POST" })); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api<{ backup_codes?: string[] }>("/auth/mfa/confirm/", { method: "POST", body: { code: code.trim() } });
      setSetup(null); setCode("");
      if (r.backup_codes?.length) setCodes(r.backup_codes); else await reload();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <section className="card">
      <h2>{t("mfa.enableTitle")}</h2>
      <p className="muted">{t("mfa.enableIntro")}</p>
      <ErrorNotice error={error} />
      {!setup ? (
        <button type="button" disabled={busy} onClick={() => void start()}>{t("mfa.enableStart")}</button>
      ) : (
        <form onSubmit={(e) => void confirm(e)}>
          <Notice>{t("mfa.enableSteps")}</Notice>
          <div className="card">
            <div className="muted">{t("enrol.secret")}</div>
            <div className="mono" style={{ wordBreak: "break-all" }}>{setup.secret}</div>
            <p className="mt-05"><a href={setup.otpauth_uri}>{t("mfa.openApp")}</a></p>
          </div>
          <Field label={t("enrol.code")}>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required />
          </Field>
          <div className="row">
            <button type="submit" disabled={busy || code.trim().length < 6}>{t("mfa.enableConfirm")}</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => { setSetup(null); setCode(""); setError(null); }}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </section>
  );
}
