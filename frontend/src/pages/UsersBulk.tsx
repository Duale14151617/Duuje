import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, uploadForm } from "../api/client";
import type { BulkUsersReport, Role } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Field, formatDate, Notice, useErrorText } from "../components/ui";
import { useI18n } from "../i18n";
import { downloadText, inspectCsv, toCsv, type CsvInspection } from "../lib/csv";

const COLUMNS = ["full_name", "username", "email", "role", "unit", "branch", "service_number", "language"];
const LIMITS = { columns: COLUMNS, required: ["full_name", "role", "unit"], maxBytes: 200_000, maxRows: 50 };

/** Create several login accounts from one CSV. Check first, then create; the temporary passwords are shown once. */
export function UsersBulk() {
  const { t, tr, lang, name } = useI18n();
  const errText = useErrorText();
  const roles = useFetch<Role[]>("/roles/");
  const [file, setFile] = useState<File | null>(null);
  const [local, setLocal] = useState<CsvInspection | null>(null);
  const [report, setReport] = useState<BulkUsersReport | null>(null);
  const [created, setCreated] = useState<BulkUsersReport["created"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const problemText = (code: string) => tr(`err.${code}`) ?? errText(new ApiError(400, { code }));

  async function choose(f: File | null) {
    setFile(f); setReport(null); setCreated(null); setError(null); setLocal(null);
    if (f) setLocal(await inspectCsv(f, LIMITS));
  }
  async function send(dryRun: boolean) {
    if (!file || local?.problem) return;
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    try {
      const r = await uploadForm<BulkUsersReport>("/users/bulk/", form);
      if (dryRun) { setReport(r); setCreated(null); }
      else { setCreated(r.created ?? []); setReport(null); setFile(null); setLocal(null); }
    } catch (err) {
      setError(err);
      if (!dryRun) setReport(null);  // the file no longer passes: check it again
    } finally { setBusy(false); }
  }
  function template() {
    downloadText("new-users-template.csv", toCsv([COLUMNS,
      ["Ali Warsame", "", "", "read_only", "HQ", "", "A-0003", "so"],
      ["Fadumo Axmed", "fadumo.axmed", "fadumo@example.com", "read_only", "HQ", "", "", "en"]]));
  }
  function credentials() {
    if (!created) return;
    downloadText("new-user-passwords.csv", toCsv([
      [t("users.username"), t("users.fullName"), t("users.bulk.password"), t("users.bulk.expires")],
      ...created.map((c) => [c.username, c.full_name, c.temporary_password, c.expires_at]),
    ]));
  }
  function problemList() {
    if (!report?.rows) return;
    downloadText("new-users-problems.csv", toCsv([
      [t("imp.rowCol"), t("imp.reportCol")],
      ...report.rows.filter((r) => r.errors.length > 0).map((r) => [String(r.row), r.errors.map(problemText).join(" ")]),
    ]));
  }
  const problems = report?.rows?.filter((r) => r.errors.length > 0) ?? [];

  return (
    <>
      <p><Link to="/users">{t("common.back")}</Link></p>
      <h1>{t("users.bulk.title")}</h1>
      <p>{t("users.bulk.intro")}</p>
      <ErrorNotice error={error} />
      {created && (
        <section className="card">
          <Notice>{t("users.bulk.done", { n: created.length })}</Notice>
          <Notice kind="error">{t("users.bulk.once", { days: created[0]?.expires_at ? formatDate(created[0].expires_at, lang) : "" })}</Notice>
          <div className="row">
            <button type="button" onClick={credentials}>{t("users.bulk.download")}</button>
            <button type="button" className="secondary" onClick={() => setCreated(null)}>{t("imp.another")}</button>
          </div>
          <ul className="list">
            {created.map((c) => (
              <li key={c.username} className="item"><b>{c.username}</b> · {c.full_name} · <code>{c.temporary_password}</code></li>
            ))}
          </ul>
        </section>
      )}
      {!created && (
        <section className="card">
          <Field label={t("imp.drop")}>
            <input type="file" accept=".csv,text/csv" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
          </Field>
          <p className="muted">{t("users.bulk.limits")}</p>
          {file && local && !local.problem && <p><b>{t("imp.selected", { name: file.name, rows: local.rows })}</b></p>}
          {local?.problem && <Notice kind="error">{t("imp.localProblem")} {problemText(local.problem)}</Notice>}
          <div className="row">
            <button type="button" onClick={() => void send(true)} disabled={busy || !file || !!local?.problem}>{t("imp.preview")}</button>
            <button type="button" className="secondary" onClick={template}>{t("imp.template")}</button>
          </div>
          {roles.data && (
            <details className="mt-1">
              <summary>{t("users.bulk.roleCodes")}</summary>
              <ul className="list">
                {roles.data.map((r) => <li key={r.id} className="item"><code>{r.code}</code> · {name(r)}</li>)}
              </ul>
            </details>
          )}
        </section>
      )}
      {report && (
        <section className="card">
          <p><b>{t("imp.summary", { valid: report.valid ?? 0, total: report.total })}</b></p>
          {problems.length > 0 && <Notice kind="error">{t("imp.fixFile")}</Notice>}
          {report.can_commit && <Notice>{t("users.bulk.ready")}</Notice>}
          <ul className="list">
            {report.rows?.slice(0, 50).map((r) => (
              <li key={r.row} className="item">
                <b>{t("imp.rowCol")} {r.row}</b>
                {r.errors.length === 0 ? <> · <code>{r.username}</code></> : <>: {r.errors.map(problemText).join(" ")}</>}
              </li>
            ))}
          </ul>
          <div className="row">
            {report.can_commit && <button type="button" onClick={() => void send(false)} disabled={busy}>{t("users.bulk.apply")}</button>}
            {problems.length > 0 && <button type="button" className="secondary" onClick={problemList}>{t("replines.problems")}</button>}
          </div>
        </section>
      )}
    </>
  );
}
