import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ErrorNotice, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

const icon = (children: ReactNode) => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const UserIcon = () => icon(<><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" /></>);
const LockIcon = () => icon(<><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>);
const EyeIcon = ({ off }: { off: boolean }) => icon(off
  ? <><path d="M3 3l18 18" /><path d="M10.6 6.2A9.8 9.8 0 0 1 12 6c5 0 8.5 4 9.5 6-.4.8-1.2 2-2.4 3.1M6.5 7.6C4.4 9 3 11 2.5 12c1 2 4.5 6 9.5 6 1.4 0 2.7-.3 3.8-.8" /><path d="M9.9 10a3 3 0 0 0 4.1 4.1" /></>
  : <><path d="M2.5 12c1-2 4.5-6 9.5-6s8.5 4 9.5 6c-1 2-4.5 6-9.5 6s-8.5-4-9.5-6z" /><circle cx="12" cy="12" r="3" /></>);
const GlobeIcon = () => icon(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.6 2.7 3.9 5.7 3.9 9s-1.3 6.3-3.9 9c-2.6-2.7-3.9-5.7-3.9-9S9.4 5.7 12 3z" /></>);

export function Login() {
  const { login, offline } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
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
    <div className="lp">
      <header className="lp-header">
        <img className="lp-header-crest" src="/defence-force.jpg" alt="" width={64} height={64} />
        <div className="lp-header-text">
          <div className="lp-header-title">{t("app.name")}</div>
          <div className="lp-header-tag">Integrated <i>·</i> Secure <i>·</i> Efficient</div>
        </div>
        <div className="lp-controls">
          <button type="button" className="lp-lang" onClick={() => setLang(lang === "en" ? "so" : "en")}
                  aria-label={t("lang.other")}>
            <GlobeIcon />
            <span>{lang === "en" ? "English" : "Soomaali"}</span>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <ThemeToggle />
        </div>
      </header>

      <main className="lp-main">
        <div className="lp-bg lp-bg-left" aria-hidden="true" />
        <div className="lp-bg lp-bg-right" aria-hidden="true" />

        <section className="lp-center">
          <img className="lp-crest" src="/defence-force.jpg" alt="Puntland Defence Force crest" width={176} height={176} />
          <h1 className="lp-title">{t("app.name")}</h1>
          <div className="lp-sub"><span>Headquarters Administration</span></div>
          <div className="lp-motto">Discipline <i>·</i> Readiness <i>·</i> Security</div>

          <div className="lp-card">
            <h2 className="lp-welcome">{t("login.welcome")}</h2>
            <p className="lp-welcome-sub">{t("login.welcomeSub")}</p>
            <img className="lp-avatar" src="/avatar-default.png" alt="" aria-hidden="true" width={80} height={80} />

            {offline && !error && <Notice kind="error">{t("err.network")}</Notice>}
            <ErrorNotice error={error} />

            <form onSubmit={(e) => void submit(e)}>
              <div className="lp-field">
                <label htmlFor="lp-username">{t("login.username")}</label>
                <div className="lp-input">
                  <UserIcon />
                  <input id="lp-username" value={username} onChange={(e) => setUsername(e.target.value)}
                         placeholder={t("login.usernamePh")} autoComplete="username" autoCapitalize="none" required />
                </div>
              </div>
              <div className="lp-field">
                <label htmlFor="lp-password">{t("login.password")}</label>
                <div className="lp-input">
                  <LockIcon />
                  <input id="lp-password" type={showPw ? "text" : "password"} value={password}
                         onChange={(e) => setPassword(e.target.value)} placeholder={t("login.passwordPh")}
                         autoComplete="current-password" required />
                  <button type="button" className="lp-eye" aria-pressed={showPw} onClick={() => setShowPw((v) => !v)}
                          aria-label={showPw ? t("login.hidePassword") : t("login.showPassword")}>
                    <EyeIcon off={!showPw} />
                  </button>
                </div>
              </div>
              {needOtp && (
                <div className="lp-field">
                  <label htmlFor="lp-otp">{t("login.otp")}</label>
                  <div className="lp-input">
                    <LockIcon />
                    <input id="lp-otp" value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric"
                           autoComplete="one-time-code" maxLength={8} required autoFocus // eslint-disable-line jsx-a11y/no-autofocus -- the code field appears after the password step
                           />
                  </div>
                  <small className="lp-hint">{t("login.otpHint")}</small>
                </div>
              )}
              <button type="submit" className="lp-submit" disabled={busy}>
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.2"
                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 12h16M14 6l6 6-6 6" /></svg>
                <span>{t("login.submit")}</span>
              </button>
            </form>

            <p className="lp-reset">
              <LockIcon />
              <a href="/reset">{t("reset.have")}</a>
            </p>

            <div className="lp-card-foot">
              <img src="/ministry.jpg" alt="Ministry of Security Puntland emblem" width={56} height={56} />
              <div>
                <div className="lp-foot-1">Ministry of Security Puntland</div>
                <div className="lp-foot-2">{t("app.name")} <i>·</i> Pilot Build</div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <svg className="lp-orn" viewBox="0 0 170 20" width="170" height="20" aria-hidden="true"><path d="M0 1l22 17h148" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>
        <span>{t("app.name")} <i>·</i> Pilot Build</span>
        <svg className="lp-orn lp-orn-r" viewBox="0 0 170 20" width="170" height="20" aria-hidden="true"><path d="M0 1l22 17h148" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>
      </footer>
    </div>
  );
}
