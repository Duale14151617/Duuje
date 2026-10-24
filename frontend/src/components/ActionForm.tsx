import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorNotice, Field } from "./ui";

export interface ActField { key: string; label: string; type?: "text" | "number" | "int" | "date"; options?: [string, string][]; required?: boolean }

/** A button that opens a small form and POSTs it to `path`. `int` fields are sent as whole numbers, `extra` is always added to the body.
 *  A rule the server refuses is shown as its message and nothing changes. */
export function Act({ title, path, fields, extra, onDone, submitLabel }: {
  title: string; path: string; fields: ActField[]; extra?: Record<string, unknown>; onDone: () => void; submitLabel: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState<Record<string, string>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function go(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    const body: Record<string, unknown> = { ...extra };
    for (const f of fields) { const x = v[f.key] ?? ""; if (x !== "") body[f.key] = f.type === "int" ? Number(x) : x; }
    try { await api(path, { method: "POST", body }); setOpen(false); setV({}); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); }
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
      <div className="row"><button type="submit" disabled={busy}>{submitLabel}</button><button type="button" className="secondary" onClick={() => setOpen(false)}>{t("common.cancel")}</button></div>
    </form>
  );
}
