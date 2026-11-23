import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import { ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

/** Redeem a one-time code (given by an administrator, or emailed after "Forgot your password?") and choose a new password. */
export function ResetPassword() {
  const { t, lang, setLang } = useI18n();
  const [f, setF] = useState({ username: new URLSearchParams(window.location.search).get("u") ?? "", code: new URLSearchParams(window.location.search).get("c") ?? "", new_password: "" });
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  // Keep the one-time code out of the address bar and history once the page has read it.
  useEffect(() => { if (window.location.search) window.history.replaceState(null, "", window.location.pathname); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/reset/", { method: "POST", body: { ...f, ...(needOtp ? { otp: otp.trim() } : {}) } });
      setDone(true);
    } catch (err) {
      // An emailed code on an account with an authenticator app also needs the app's current code. The reset code is not used up.
      if (err instanceof ApiError && err.code === "otp_required") setNeedOtp(true);
      else setError(err);
    } finally { setBusy(false); }
  }
  return (
    <div className="auth">
      <div className="row row-between">
        <span className="brand">{t("app.name")}</span>
        <ThemeToggle />
        <button className="secondary" onClick={() => setLang(lang === "en" ? "so" : "en")}>{t("lang.other")}</button>
      </div>
      <h1 className="mt-15">{t("reset.title")}</h1>
      {done ? (
        <>
          <Notice>{t("reset.done")}</Notice>
          <a className="btn" href="/">{t("reset.backToLogin")}</a>
        </>
      ) : (
        <>
          <p>{t("reset.intro")}</p>
          <ErrorNotice error={error} />
          <form onSubmit={(e) => void submit(e)}>
            <Field label={t("reset.username")}>
              <input value={f.username} autoCapitalize="none" autoComplete="username" onChange={(e) => setF({ ...f, username: e.target.value })} required />
            </Field>
            <Field label={t("reset.code")}>
              <input value={f.code} autoCapitalize="characters" autoComplete="one-time-code" onChange={(e) => setF({ ...f, code: e.target.value })} required />
            </Field>
            <Field label={t("reset.new")}>
              <input type="password" value={f.new_password} autoComplete="new-password" minLength={12} onChange={(e) => setF({ ...f, new_password: e.target.value })} required />
            </Field>
            {needOtp && (
              <>
                <Notice>{t("reset.otpHint")}</Notice>
                <Field label={t("reset.otp")}>
                  <input value={otp} inputMode="numeric" maxLength={8} autoComplete="one-time-code" onChange={(e) => setOtp(e.target.value)} required />
                </Field>
              </>
            )}
            <div className="row">
              <button type="submit" disabled={busy}>{t("reset.submit")}</button>
              <a className="btn secondary" href="/">{t("reset.backToLogin")}</a>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
