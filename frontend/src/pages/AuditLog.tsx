import { useState } from "react";
import { fetchAll } from "../api/client";
import type { AuditEvent, Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { Chip, ErrorNotice, Field, formatDate, Loading, Pager } from "../components/ui";
import { useI18n } from "../i18n";

export function AuditLog() {
  const { t, lang } = useI18n();
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState<unknown>(null);
  const events = useFetch<Page<AuditEvent>>("/audit-events/", { action, outcome, page });

  async function buildPdf() {
    const all = await fetchAll<AuditEvent>("/audit-events/", { action, outcome }, 1000);
    return {
      title: t("audit.title"), landscape: true,
      subtitle: [action && `${t("audit.action")}: ${action}`, outcome && `${t("audit.outcome")}: ${outcome}`, t("pdf.rowsCount", { n: all.length })].filter(Boolean).join("  |  "),
      sections: [{
        columns: [{ header: t("audit.when"), width: 2 }, { header: t("audit.who"), width: 1.6 }, { header: t("audit.action"), width: 2.4 },
          { header: t("audit.outcome"), width: 1 }, { header: t("audit.entity"), width: 2 }, { header: t("audit.correlation"), width: 1.8 }],
        rows: all.map((e) => [formatDate(e.occurred_at, lang), e.actor_username || "-", e.action, e.outcome,
          `${e.entity_type}${e.entity_id ? ` ${e.entity_id.slice(0, 8)}` : ""}`, e.correlation_id.slice(0, 12)]),
      }],
    };
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("audit.title")}</h1>
        <ExportPdfButton filename="audit-log.pdf" build={buildPdf} onError={setExportError} />
      </div>
      <div className="grid">
        <Field label={t("audit.filterAction")}>
          <input value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} placeholder="auth.login" />
        </Field>
        <Field label={t("audit.outcome")}>
          <select value={outcome} onChange={(e) => { setOutcome(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            <option value="success">success</option><option value="failure">failure</option><option value="denied">denied</option>
          </select>
        </Field>
      </div>
      <ErrorNotice error={events.error ?? exportError} />
      {events.loading && !events.data ? <Loading /> : null}
      {events.data && events.data.results.length === 0 && <p>{t("audit.noEvents")}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("audit.when")}</th><th>{t("audit.who")}</th><th>{t("audit.action")}</th>
              <th>{t("audit.outcome")}</th><th>{t("audit.entity")}</th><th>{t("audit.correlation")}</th>
            </tr>
          </thead>
          <tbody>
            {events.data?.results.map((e) => (
              <tr key={e.id}>
                <td>{formatDate(e.occurred_at, lang)}</td>
                <td>{e.actor_username || "-"}</td>
                <td className="mono">{e.action}</td>
                <td><Chip tone={e.outcome}>{e.outcome}</Chip></td>
                <td className="mono">{e.entity_type}{e.entity_id ? ` ${e.entity_id.slice(0, 8)}` : ""}</td>
                <td className="mono">{e.correlation_id.slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {events.data && <Pager page={page} count={events.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}
