import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, uploadForm } from "../api/client";
import type { ReportingLinesReport } from "../api/types";
import { ErrorNotice, Field, Notice, useErrorText } from "../components/ui";
import { useI18n } from "../i18n";
import { downloadText, inspectCsv, toCsv, type CsvInspection } from "../lib/csv";

const COLUMNS = ["service_number", "supervisor_service_number", "account_username"];
const LIMITS = { columns: COLUMNS, required: ["service_number"], maxBytes: 1_000_000, maxRows: 1000 };

/** Fill in supervisors (and login links) for people who are already on file, from one CSV. Check first, then apply. */
export function ReportingLines() {
  const { t, tr } = useI18n();
  const errText = useErrorText();
  const [file, setFile] = useState<File | null>(null);
  const [local, setLocal] = useState<CsvInspection | null>(null);
  const [report, setReport] = useState<ReportingLinesReport | null>(null);
  const [updated, setUpdated] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const problemText = (code: string) => tr(`err.${code}`) ?? errText(new ApiError(400, { code }));

  async function choose(f: File | null) {
    setFile(f); setReport(null); setUpdated(null); setError(null); setLocal(null);
    if (f) setLocal(await inspectCsv(f, LIMITS));
  }
  async function send(dryRun: boolean) {
    if (!file || local?.problem) return;
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    try {
      const r = await uploadForm<ReportingLinesReport>("/personnel/reporting-lines/", form);
      if (dryRun) { setReport(r); setUpdated(null); }
      else { setUpdated(r.updated ?? 0); setReport(null); setFile(null); setLocal(null); }
    } catch (err) {
      setError(err);
      if (!dryRun) setReport(null);  // the file no longer passes: check it again
    } finally { setBusy(false); }
  }
  function template() {
    downloadText("reporting-lines-template.csv", toCsv([COLUMNS, ["A-0003", "A-0002", ""], ["A-0004", "clear", "login.name"]]));
  }
  function problemList() {
    if (!report?.rows) return;
    downloadText("reporting-lines-problems.csv", toCsv([
      [t("imp.rowCol"), t("imp.reportCol")],
      ...report.rows.filter((r) => r.errors.length > 0).map((r) => [String(r.row), r.errors.map(problemText).join(" ")]),
    ]));
  }
  const problems = report?.rows?.filter((r) => r.errors.length > 0) ?? [];

  return (
    <>
      <p><Link to="/personnel">{t("common.back")}</Link></p>
      <h1>{t("replines.title")}</h1>
      <p>{t("replines.intro")}</p>
      <ErrorNotice error={error} />
      {updated !== null && (
        <section className="card">
          <Notice>{t("replines.done", { n: updated })}</Notice>
          <div className="row">
            <Link className="btn" to="/personnel">{t("imp.viewPeople")}</Link>
            <button className="secondary" onClick={() => setUpdated(null)}>{t("imp.another")}</button>
          </div>
        </section>
      )}
      {updated === null && (
        <section className="card">
          <Field label={t("imp.drop")}>
            <input type="file" accept=".csv,text/csv" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
          </Field>
          <p className="muted">{t("replines.limits")}</p>
          {file && local && !local.problem && <p><b>{t("imp.selected", { name: file.name, rows: local.rows })}</b></p>}
          {local?.problem && <Notice kind="error">{t("imp.localProblem")} {problemText(local.problem)}</Notice>}
          <div className="row">
            <button type="button" onClick={() => void send(true)} disabled={busy || !file || !!local?.problem}>{t("imp.preview")}</button>
            <button type="button" className="secondary" onClick={template}>{t("imp.template")}</button>
          </div>
        </section>
      )}
      {report && (
        <section className="card">
          <p><b>{t("imp.summary", { valid: report.valid, total: report.total })}</b></p>
          {problems.length > 0 && <Notice kind="error">{t("imp.fixFile")}</Notice>}
          {report.can_commit && <Notice>{t("replines.ready")}</Notice>}
          <ul className="list">
            {problems.slice(0, 50).map((r) => (
              <li key={r.row} className="item"><b>{t("imp.rowCol")} {r.row}</b>: {r.errors.map(problemText).join(" ")}</li>
            ))}
          </ul>
          {problems.length > 50 && <p className="muted">{t("replines.more", { n: problems.length - 50 })}</p>}
          <div className="row">
            {report.can_commit && <button type="button" onClick={() => void send(false)} disabled={busy}>{t("replines.apply")}</button>}
            {problems.length > 0 && <button type="button" className="secondary" onClick={problemList}>{t("replines.problems")}</button>}
          </div>
        </section>
      )}
    </>
  );
}
