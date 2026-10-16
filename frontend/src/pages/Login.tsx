import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

export function Login() {
  const { login, offline } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password, needOtp ? otp : undefined);
    } catch (err) {
      if (err instanceof ApiError && err.code === "otp_required") setNeedOtp(true);
      else setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="brand">{t("app.name")}</span>
        <ThemeToggle />
        <button className="secondary" onClick={() => setLang(lang === "en" ? "so" : "en")}>{t("lang.other")}</button>
      </div>
      <div style={{ textAlign: "center", marginTop: "1.5rem" }}>
        <img src="/defence-force.jpg" alt="Puntland Defence Force emblem" width={112} height={112} style={{ borderRadius: 8 }} />
        <div style={{ marginTop: ".6rem", fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase" }}>Puntland Defence Force</div>
        <div className="muted">Headquarters Administration</div>
      </div>
      <h1 style={{ marginTop: "1.5rem" }}>{t("login.title")}</h1>
      <p className="muted">{t("app.tagline")}</p>
      <Notice>{t("common.demoBuild")}</Notice>
      {offline && !error && <Notice kind="error">{t("err.network")}</Notice>}
      <ErrorNotice error={error} />
      <form onSubmit={(e) => void submit(e)}>
        <Field label={t("login.username")}>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
                 autoCapitalize="none" required />
        </Field>
        <Field label={t("login.password")}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required />
        </Field>
        {needOtp && (
          <Field label={t("login.otp")}>
            <input value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric" autoComplete="one-time-code"
                   maxLength={8} required autoFocus // eslint-disable-line jsx-a11y/no-autofocus -- moved here deliberately: the code field appears after the password step
                   />
            <small>{t("login.otpHint")}</small>
          </Field>
        )}
        <button type="submit" disabled={busy} style={{ width: "100%" }}>{t("login.submit")}</button>
      </form>
      <p style={{ marginTop: "1rem" }}><a href="/reset">{t("reset.have")}</a></p>
      <div style={{ marginTop: "2rem", paddingTop: "1rem", borderTop: "1px solid currentColor", opacity: .85, display: "flex", alignItems: "center", gap: ".75rem" }}>
        <img src="/ministry.jpg" alt="Ministry of Security Puntland emblem" width={48} height={48} style={{ borderRadius: 4 }} />
        <small>Ministry of Security Puntland</small>
      </div>
    </div>
  );
}
