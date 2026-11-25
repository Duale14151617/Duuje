import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { downloadCsv, fetchAll } from "../api/client";
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
  const [who, setWho] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState<unknown>(null);
  const [exporting, setExporting] = useState(false);
  // the search box looks in the person, the action, the record type and the record id at once
  const filters = { q: action, who, from, to, outcome };
  const events = useFetch<Page<AuditEvent>>("/audit-events/", { ...filters, page });

  async function exportCsv() {
    setExporting(true); setExportError(null);
    try { await downloadCsv("/audit-events/export/", { q: action, who, from, to, outcome }, "audit-log.csv"); }
    catch (e) { setExportError(e); } finally { setExporting(false); }
  }

  async function buildPdf() {
    const all = await fetchAll<AuditEvent>("/audit-events/", filters, 1000);
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

  const reset = () => { setAction(""); setOutcome(""); setWho(""); setFrom(""); setTo(""); setPage(1); };
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
      <PageHeader title={t("audit.title")} actions={<>
        <button type="button" className="secondary" disabled={exporting} onClick={() => void exportCsv()}>{t("audit.exportCsv")}</button>
        <ExportPdfButton filename="audit-log.pdf" build={buildPdf} onError={setExportError} />
      </>} />
      <FilterBar
        search={{ value: action, label: t("audit.filterAction"), onChange: (v) => { setAction(v); setPage(1); } }}
        filters={[{ id: "outcome", label: t("audit.outcome"), value: outcome, onChange: (v) => { setOutcome(v); setPage(1); },
          options: ["success", "failure", "denied"].map((o) => ({ value: o, label: o })) }]}
        onReset={reset} />
      <div className="row audit-extra" style={{ gap: ".75rem", flexWrap: "wrap", margin: ".5rem 0" }}>
        <label>{t("audit.who")}<br /><input value={who} onChange={(e) => { setWho(e.target.value); setPage(1); }} placeholder={t("audit.whoPlaceholder")} /></label>
        <label>{t("audit.from")}<br /><input type="date" value={from} max={to || undefined} onChange={(e) => { setFrom(e.target.value); setPage(1); }} /></label>
        <label>{t("audit.to")}<br /><input type="date" value={to} min={from || undefined} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></label>
      </div>
      <ErrorNotice error={events.error ?? exportError} />
      <DataTable id="audit" caption={t("audit.title")} columns={columns} rows={events.data?.results} rowKey={(e) => e.id}
                 loading={events.loading} filtered={!!(action || outcome || who || from || to)} onReset={reset}
                 empty={{ icon: "activity", title: t("audit.noEvents") }}
                 page={page} count={events.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}
