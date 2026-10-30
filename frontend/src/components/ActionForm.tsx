import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { ErrorNotice, Field } from "./ui";

export interface ActField { key: string; label: string; type?: "text" | "number" | "int" | "date"; options?: [string, string][]; required?: boolean }

/** A button that opens a small form and POSTs it to `path`. `int` fields are sent as whole numbers, `extra` is always added to the body.
 *  A rule the server refuses is shown as its message and nothing changes. */
export function Act({ title, path, fields, extra, onDone, submitLabel }: {
  title: string; path: string; fields: ActField[]; extra?: Record<string, unknown>; onDone: () => void; submitLabel: string;
}) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [v, setV] = useState<Record<string, string>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // Emergency override: offered only to the super administrator, and only after the server refused a different-person rule.
  const blocked = err instanceof ApiError && !!err.fieldCode?.endsWith("_must_differ") && can("system.full_access");
  async function go(e: FormEvent, override = false) {
    e.preventDefault(); setBusy(true); setErr(null);
    const body: Record<string, unknown> = { ...extra };
    for (const f of fields) { const x = v[f.key] ?? ""; if (x !== "") body[f.key] = f.type === "int" ? Number(x) : x; }
    try { await api(path, { method: "POST", body, headers: override ? { "X-Override-Reason": reason.trim() } : undefined }); setOpen(false); setV({}); setReason(""); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>{title}</button>;
  return (
    <form className="card" onSubmit={(e) => void go(e)}>
      <h3>{title}</h3>
      <ErrorNotice error={err} />
      {fields.map((f) => (
        <Field key={f.key} label={f.label}>
          {f.options
            ? <select value={v[f.key] ?? ""} required={f.required !== false} onChange={(e) => setV({ ...v, [f.key]: e.target.value })}><option value="">—</option>{f.options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            : <input type={f.type === "int" ? "number" : f.type ?? "text"} value={v[f.key] ?? ""} required={f.required !== false} step={f.type === "number" ? "0.01" : f.type === "int" ? "1" : undefined}
                     onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />}
        </Field>
      ))}
      {blocked && (
        <div className="card">
          <p className="muted">{t("bg.note")}</p>
          <Field label={t("bg.reason")}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
          <button type="button" disabled={busy || reason.trim().length < 15} onClick={(e) => void go(e as unknown as FormEvent, true)}>{t("bg.go")}</button>
        </div>
      )}
      <div className="row"><button type="submit" disabled={busy}>{submitLabel}</button><button type="button" className="secondary" onClick={() => setOpen(false)}>{t("common.cancel")}</button></div>
    </form>
  );
}
