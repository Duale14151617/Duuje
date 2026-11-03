import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ErrorNotice, Field } from "../components/ui";
import { useI18n } from "../i18n";

export function ForcedPassword() {
  const { reload, logout } = useAuth();
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/change/", { method: "POST", body: { current_password: current, new_password: next } });
      await reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <h1>{t("enrol.pwTitle")}</h1>
      <p>{t("enrol.pwIntro")}</p>
      <ErrorNotice error={error} />
      <form onSubmit={(e) => void submit(e)}>
        <Field label={t("enrol.current")}>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
        </Field>
        <Field label={t("enrol.new")}>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={12} required />
        </Field>
        <div className="row">
          <button type="submit" disabled={busy}>{t("enrol.changePw")}</button>
          <button type="button" className="secondary" onClick={() => void logout()}>{t("common.signOut")}</button>
        </div>
      </form>
    </div>
  );
}

export function MfaEnrol() {
  const { reload, logout } = useAuth();
  const { t } = useI18n();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setError(null);
    try {
      setSetup(await api<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup/", { method: "POST" }));
    } catch (err) {
      setError(err);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/mfa/confirm/", { method: "POST", body: { code } });
      await reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <h1>{t("enrol.mfaTitle")}</h1>
      <p>{t("enrol.mfaIntro")}</p>
      <ErrorNotice error={error} />
      {!setup ? (
        <div className="row">
          <button onClick={() => void start()}>{t("enrol.mfaStart")}</button>
          <button className="secondary" onClick={() => void logout()}>{t("common.signOut")}</button>
        </div>
      ) : (
        <form onSubmit={(e) => void confirm(e)}>
          <div className="card">
            <div className="muted">{t("enrol.secret")}</div>
            <div className="mono">{setup.secret}</div>
            <p style={{ marginTop: ".5rem" }}><a href={setup.otpauth_uri}>{t("enrol.mfaStart")}</a></p>
          </div>
          <Field label={t("enrol.code")}>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric"
                   autoComplete="one-time-code" maxLength={8} required />
          </Field>
          <button type="submit" disabled={busy}>{t("enrol.confirm")}</button>
        </form>
      )}
    </div>
  );
}
