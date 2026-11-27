import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorNotice, Field, Notice } from "./ui";

/** Account page: change your own password (current password required; every other sign-in is ended by the server). */
export function ChangePassword() {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const mismatch = again !== "" && again !== next;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next !== again) return;
    setBusy(true); setError(null); setDone(false);
    try {
      await api("/auth/password/change/", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent(""); setNext(""); setAgain(""); setDone(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <section className="card">
      <h2>{t("pwchange.title")}</h2>
      <p className="muted">{t("pwchange.intro")}</p>
      {done && <Notice>{t("pwchange.done")}</Notice>}
      <ErrorNotice error={error} />
      <form onSubmit={(e) => void submit(e)}>
        <Field label={t("enrol.current")}>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
        </Field>
        <Field label={t("enrol.new")}>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={12} required />
        </Field>
        <Field label={t("pwchange.again")}>
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" minLength={12} required />
        </Field>
        {mismatch && <p className="muted" role="alert">{t("pwchange.mismatch")}</p>}
        <button type="submit" disabled={busy || !current || next.length < 12 || next !== again}>{t("enrol.changePw")}</button>
      </form>
    </section>
  );
}
