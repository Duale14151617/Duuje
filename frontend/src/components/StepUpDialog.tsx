import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, api, setStepUpHandler } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorNotice, Field } from "./ui";

/**
 * Asks for a fresh authenticator code when the server requires one for a sensitive action (credential resets, role assignment,
 * exports). Mounted once; it registers itself with the API client, which then retries the action that was refused.
 */
export function StepUpDialog() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const settle = useRef<((ok: boolean) => void) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    setStepUpHandler(() => new Promise<boolean>((resolve) => {
      settle.current?.(false);  // a second prompt replaces the first
      settle.current = resolve;
      setCode("");
      setError(null);
      setOpen(true);
    }));
    return () => setStepUpHandler(null);
  }, []);

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  const finish = (ok: boolean) => {
    setOpen(false);
    settle.current?.(ok);
    settle.current = null;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/step-up/", { method: "POST", body: { code: code.trim() } });
      finish(true);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, { code: "network" }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className="stepup" aria-labelledby="stepup-title" onCancel={(e) => { e.preventDefault(); finish(false); }}>
      <form onSubmit={submit}>
        <h2 id="stepup-title">{t("stepup.title")}</h2>
        <p className="muted">{t("stepup.hint")}</p>
        <Field label={t("login.otp")}>
          <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code"
                 maxLength={8} autoFocus required />
        </Field>
        {error ? <ErrorNotice error={error} /> : null}
        <div className="row" style={{ gap: ".5rem", marginTop: ".75rem" }}>
          <button type="submit" disabled={busy || code.trim().length < 6}>{t("stepup.confirm")}</button>
          <button type="button" className="secondary" onClick={() => finish(false)}>{t("common.cancel")}</button>
        </div>
      </form>
    </dialog>
  );
}
