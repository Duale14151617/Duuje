import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { ThemeToggle } from "../theme/ThemeToggle";

export function ResetPassword() {
  const { t, lang, setLang } = useI18n();
  const [f, setF] = useState({ username: "", code: "", new_password: "" });
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/reset/", { method: "POST", body: f });
      setDone(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="auth">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="brand">{t("app.name")}</span>
        <ThemeToggle />
        <button className="secondary" onClick={() => setLang(lang === "en" ? "so" : "en")}>{t("lang.other")}</button>
      </div>
      <h1 style={{ marginTop: "1.5rem" }}>{t("reset.title")}</h1>
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
