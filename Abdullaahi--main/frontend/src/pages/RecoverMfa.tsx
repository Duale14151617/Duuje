import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

type Step = "ask" | "code" | "done";

/** Lost authenticator app: email a one-time code (password required), then use it to clear the old enrolment. */
export function RecoverMfa() {
  const { t, lang, setLang } = useI18n();
  const [step, setStep] = useState<Step>("ask");
  const [f, setF] = useState({ username: "", password: "", code: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: FormEvent, path: string, body: object, next: Step) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST", body });
      setStep(next);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const creds = { username: f.username, password: f.password };
  return (
    <div className="auth">
      <div className="row row-between">
        <span className="brand">{t("app.name")}</span>
        <ThemeToggle />
        <button className="secondary" onClick={() => setLang(lang === "en" ? "so" : "en")}>{t("lang.other")}</button>
      </div>
      <h1 className="mt-15">{t("recover.title")}</h1>
      {step === "done" ? (
        <>
          <Notice>{t("recover.done")}</Notice>
          <a className="btn" href="/">{t("reset.backToLogin")}</a>
        </>
      ) : (
        <>
          <p>{step === "ask" ? t("recover.introAsk") : t("recover.introCode")}</p>
          <ErrorNotice error={error} />
          <form onSubmit={(e) => void (step === "ask"
            ? run(e, "/auth/mfa/recover/request/", creds, "code")
            : run(e, "/auth/mfa/recover/redeem/", { ...creds, code: f.code }, "done"))}>
            <Field label={t("reset.username")}>
              <input value={f.username} autoCapitalize="none" autoComplete="username" onChange={(e) => setF({ ...f, username: e.target.value })} required />
            </Field>
            <Field label={t("login.password")}>
              <input type="password" value={f.password} autoComplete="current-password" onChange={(e) => setF({ ...f, password: e.target.value })} required />
            </Field>
            {step === "code" && <>
              <Notice>{t("recover.sent")}</Notice>
              <Field label={t("reset.code")}>
                <input value={f.code} autoCapitalize="characters" autoComplete="one-time-code" onChange={(e) => setF({ ...f, code: e.target.value })} required />
              </Field>
            </>}
            <div className="row">
              <button type="submit" disabled={busy}>{step === "ask" ? t("recover.send") : t("recover.submit")}</button>
              <a className="btn secondary" href="/">{t("reset.backToLogin")}</a>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
