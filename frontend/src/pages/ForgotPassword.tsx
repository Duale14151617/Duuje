import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

/** Forgot password, step 1: ask for a one-time code by email. The answer is the same whether or not the account exists. */
export function ForgotPassword() {
  const { t, lang, setLang } = useI18n();
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/forgot/", { method: "POST", body: { identifier: identifier.trim() } });
      setSent(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const typed = identifier.trim();
  // A username can be carried over to the next screen; an email address cannot (the reset step asks for the username).
  const resetHref = typed && !typed.includes("@") ? `/reset?u=${encodeURIComponent(typed.toLowerCase())}` : "/reset";
  return (
    <div className="auth">
      <div className="row row-between">
        <span className="brand">{t("app.name")}</span>
        <ThemeToggle />
        <button className="secondary" onClick={() => setLang(lang === "en" ? "so" : "en")}>{t("lang.other")}</button>
      </div>
      <h1 className="mt-15">{t("forgot.title")}</h1>
      {sent ? (
        <>
          <Notice>{t("forgot.sent")}</Notice>
          <div className="row">
            <a className="btn" href={resetHref}>{t("forgot.haveCode")}</a>
            <a className="btn secondary" href="/">{t("reset.backToLogin")}</a>
          </div>
        </>
      ) : (
        <>
          <p>{t("forgot.intro")}</p>
          <ErrorNotice error={error} />
          <form onSubmit={(e) => void submit(e)}>
            <Field label={t("forgot.identifier")}>
              <input value={identifier} autoCapitalize="none" autoComplete="username" onChange={(e) => setIdentifier(e.target.value)} required />
            </Field>
            <div className="row">
              <button type="submit" disabled={busy}>{t("forgot.send")}</button>
              <a className="btn secondary" href={resetHref}>{t("forgot.haveCode")}</a>
              <a className="btn secondary" href="/">{t("reset.backToLogin")}</a>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
