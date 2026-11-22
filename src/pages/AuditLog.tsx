import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchAll } from "../api/client";
import type { AuditEvent, Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { Chip, ErrorNotice, formatDate, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { statusTone } from "../components/status";
import { useI18n } from "../i18n";

export function AuditLog() {
  const { t, lang } = useI18n();
  const [params] = useSearchParams();
  const [action, setAction] = useState(params.get("action") ?? "");
  const [outcome, setOutcome] = useState(["success", "failure", "denied"].includes(params.get("outcome") ?? "") ? params.get("outcome")! : "");
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

  const reset = () => { setAction(""); setOutcome(""); setPage(1); };
  const columns: Column<AuditEvent>[] = [
    { id: "when", header: t("audit.when"), width: 180, locked: true, sort: (e) => e.occurred_at, cell: (e) => formatDate(e.occurred_at, lang) },
    { id: "who", header: t("audit.who"), width: 150, sort: (e) => e.actor_username, cell: (e) => e.actor_username || "-" },
    { id: "action", header: t("audit.action"), width: 200, sort: (e) => e.action, cell: (e) => <span className="mono">{e.action}</span> },
    { id: "outcome", header: t("audit.outcome"), width: 120, sort: (e) => e.outcome, cell: (e) => <Chip tone={statusTone(e.outcome)}>{e.outcome}</Chip> },
    { id: "entity", header: t("audit.entity"), width: 200, sort: (e) => e.entity_type, cell: (e) => <span className="mono">{e.entity_type}{e.entity_id ? ` ${e.entity_id.slice(0, 8)}` : ""}</span> },
    { id: "corr", header: t("audit.correlation"), width: 160, hidden: true, cell: (e) => <span className="mono">{e.correlation_id.slice(0, 12)}</span> },
  ];

  return (
    <>
      <PageHeader title={t("audit.title")} actions={<ExportPdfButton filename="audit-log.pdf" build={buildPdf} onError={setExportError} />} />
      <FilterBar
        search={{ value: action, label: t("audit.filterAction"), onChange: (v) => { setAction(v); setPage(1); } }}
        filters={[{ id: "outcome", label: t("audit.outcome"), value: outcome, onChange: (v) => { setOutcome(v); setPage(1); },
          options: ["success", "failure", "denied"].map((o) => ({ value: o, label: o })) }]}
        onReset={reset} />
      <ErrorNotice error={events.error ?? exportError} />
      <DataTable id="audit" caption={t("audit.title")} columns={columns} rows={events.data?.results} rowKey={(e) => e.id}
                 loading={events.loading} filtered={!!(action || outcome)} onReset={reset}
                 empty={{ icon: "activity", title: t("audit.noEvents") }}
                 page={page} count={events.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}
