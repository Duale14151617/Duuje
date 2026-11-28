import { useState } from "react";
import { uploadForm } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorNotice, Field, Notice } from "./ui";

type Row = { file: string; username: string; status: string };
type Report = { total: number; valid: number; applied: number | null; rows: Row[] };

/** User import page: a zip of photos named by username (ali.warsame.jpg). Preview first, then apply. */
export function BulkAvatars() {
  const { t, tr } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function send(dryRun: boolean) {
    if (!file) return;
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    try { setReport(await uploadForm<Report>("/users/avatars/bulk/", form)); if (!dryRun) setFile(null); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const skipped = report?.rows.filter((r) => r.status !== "ok") ?? [];

  return (
    <section className="card">
      <h2>{t("avbulk.title")}</h2>
      <p className="muted">{t("avbulk.intro")}</p>
      <ErrorNotice error={error} />
      <Field label={t("avbulk.zip")}>
        <input type="file" accept=".zip,application/zip" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); setError(null); }} />
      </Field>
      <div className="row">
        <button type="button" disabled={busy || !file} onClick={() => void send(true)}>{t("imp.preview")}</button>
        {report && report.applied == null && report.valid > 0 && file &&
          <button type="button" disabled={busy} onClick={() => void send(false)}>{t("avbulk.apply", { n: report.valid })}</button>}
      </div>
      {report && (
        <>
          {report.applied != null
            ? <Notice>{t("avbulk.done", { n: report.applied })}</Notice>
            : <p><b>{t("avbulk.summary", { valid: report.valid, total: report.total })}</b></p>}
          {skipped.length > 0 && (
            <>
              <Notice kind="warn">{t("avbulk.skipped", { n: skipped.length })}</Notice>
              <ul className="list">
                {skipped.map((r) => <li key={r.file} className="item"><code>{r.file}</code> · {tr(`avbulk.status.${r.status}`) ?? r.status}</li>)}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
